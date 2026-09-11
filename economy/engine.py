"""Round orchestration: planning -> trading/settlement -> market update."""

from .agents import default_roster
from .config import (
    CHRONICLE_LIMIT,
    COLLATERAL_RATIO,
    DAY_PHASES,
    DEATH_THRESHOLD,
    LIQUIDATION_THRESHOLD,
    OWN_HISTORY_LIMIT,
    PRIVATE_HISTORY_LIMIT,
    ROUNDS,
    SURVIVAL_NEEDS,
)
from .crisis import apply_crisis, maybe_trigger_crisis
from .ledger import (
    close_debt_position,
    init_db,
    save_agent_state,
    save_crisis,
    save_death,
    save_debt_position,
    save_prices,
    save_transaction,
)
from .llm import get_agent_action
from .market import Market
from .state import load_state, save_state

TX_COLUMNS = [
    "round", "agent", "role", "action", "target_agent", "resource", "amount", "price_per_unit",
    "reasoning", "public_message", "dm_target", "private_message", "stance", "stance_target",
    "location", "blocked",
]


def phase_and_day(round_num: int) -> tuple[str, int]:
    """Maps an absolute round number to (time-of-day phase, day number). E.g. with 3
    phases, round 1 -> (Morning, day 1), round 4 -> (Morning, day 2)."""
    index = (round_num - 1) % len(DAY_PHASES)
    day_number = (round_num - 1) // len(DAY_PHASES) + 1
    return DAY_PHASES[index], day_number


def _apply_survival_needs(agent) -> bool:
    """Automatic food/water consumption per round (no LLM involved).

    Returns True if the agent just died this round (DEATH_THRESHOLD consecutive
    rounds in critical — both food and water negative).
    """
    for resource, need in SURVIVAL_NEEDS.items():
        agent.resources[resource] = agent.resources.get(resource, 0) - need

    food, water = agent.resources.get("food", 0), agent.resources.get("water", 0)
    is_critical_now = food < 0 and water < 0
    agent.critical_streak = agent.critical_streak + 1 if is_critical_now else 0

    if agent.critical_streak >= DEATH_THRESHOLD:
        agent.status = "dead"
        return True

    if is_critical_now:
        agent.status = "critical"
    elif food < 0:
        agent.status = "hungry"
    elif water < 0:
        agent.status = "thirsty"
    else:
        agent.status = "ok"
    return False


PUBLIC_STANCES = {"endorse", "denounce", "vote_leader"}
STANCE_VERBS = {"endorse": "publicly endorsed", "denounce": "publicly denounced", "vote_leader": "voted for"}


def _apply_action(
    agent, action, agents_by_name, boycotts: set, market, current_leader: str | None,
) -> tuple[bool, dict | None]:
    """Applies the resource effect of an action.

    Returns (blocked, new_position): `blocked` is True if it was stopped by an active
    boycott (cooperative actions only — force ignores boycotts) or by 'decree' being
    used by someone who isn't the elected leader; `new_position` describes a freshly
    opened collateralized debt position (issue_debt), or None for every other action.
    """
    target = agents_by_name.get(action.target_agent)
    if action.action == "do_nothing" or target is None or not target.is_alive():
        return False, None

    coercive = action.action in ("raid", "decree")
    if not coercive and frozenset((agent.name, target.name)) in boycotts:
        return True, None

    if action.action == "decree" and agent.name != current_leader:
        return True, None  # no mandate — the town doesn't recognize this as legitimate

    if action.action in ("raid", "decree"):
        available = target.resources.get(action.resource, 0)
        seized = min(action.amount, max(available, 0))
        target.resources[action.resource] = available - seized
        agent.resources[action.resource] = agent.resources.get(action.resource, 0) + seized
        return False, None

    if action.action == "trade":
        available = agent.resources.get(action.resource, 0)
        amount = min(action.amount, max(available, 0))
        agent.resources[action.resource] = available - amount
        target.resources[action.resource] = target.resources.get(action.resource, 0) + amount

    elif action.action == "issue_debt":
        # Collateralized loan (DeFi-style): the borrower (agent) locks gold worth
        # COLLATERAL_RATIO times the debt's market value. The requested amount is
        # capped by how much gold they actually have to back it.
        debt_price = market.prices.get("debt_note", 1.0)
        available_gold = agent.resources.get("gold", 0)
        max_principal = available_gold / (debt_price * COLLATERAL_RATIO) if debt_price > 0 else 0
        principal = min(action.amount, max(max_principal, 0))
        if principal <= 0:
            return False, None

        collateral = principal * debt_price * COLLATERAL_RATIO
        agent.resources["gold"] = available_gold - collateral
        agent.resources["debt_note"] = agent.resources.get("debt_note", 0) - principal
        target.resources["debt_note"] = target.resources.get("debt_note", 0) + principal
        return False, {
            "borrower": agent.name, "lender": target.name,
            "principal": principal, "collateral_gold": collateral,
        }

    elif action.action == "buy_futures":
        agent.resources[action.resource] = agent.resources.get(action.resource, 0) + action.amount

    return False, None


class SimulationEngine:
    def __init__(self, rounds: int = ROUNDS, resume: bool = True):
        self.rounds = rounds
        self.conn = init_db()

        checkpoint = load_state() if resume else None
        if checkpoint:
            self.agents, market_prices, self.start_round = checkpoint
            self.market = Market()
            self.market.prices = market_prices
            print(f"📂 Resuming town from round {self.start_round} (town_state.json found).")
        else:
            self.agents = default_roster()
            self.market = Market()
            self.start_round = 0
            print("🆕 Starting a brand-new town at round 1.")

        self.agents_by_name = {a.name: a for a in self.agents}
        self.transactions: list[dict] = self._load_past_transactions()
        self.open_positions: list[dict] = self._load_open_positions()

    def _load_past_transactions(self) -> list[dict]:
        """Loads all prior rounds from economy.db so memory, alliances, and boycotts
        stay continuous across separate runs, not just within a single one."""
        cur = self.conn.execute(f"SELECT {', '.join(TX_COLUMNS)} FROM transactions ORDER BY id")
        return [dict(zip(TX_COLUMNS, row)) for row in cur.fetchall()]

    def _load_open_positions(self) -> list[dict]:
        """Loads still-open collateralized debt positions so liquidation checks and
        prompt context stay continuous across separate runs."""
        cols = ["id", "borrower", "lender", "principal", "collateral_gold"]
        cur = self.conn.execute(f"SELECT {', '.join(cols)} FROM debt_positions WHERE status = 'open'")
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def run(self) -> list[dict]:
        last_round_run = self.start_round
        for round_num in range(self.start_round + 1, self.start_round + self.rounds + 1):
            last_round_run = round_num
            phase_label, day_number = phase_and_day(round_num)
            print(f"\n=== Day {day_number}, {phase_label} (round {round_num}) ===")

            crisis = maybe_trigger_crisis(round_num, day_number)
            if crisis:
                print(f"⚠️  Event: {crisis.description}")
                apply_crisis(self.agents, crisis)
                save_crisis(self.conn, crisis)

            for agent in self.agents:
                if not agent.is_alive():
                    continue
                just_died = _apply_survival_needs(agent)
                if just_died:
                    cause = f"exhaustion: {DEATH_THRESHOLD} consecutive time-of-day phases without food or water"
                    print(f"💀 {agent.name} ({agent.role.value}) did not survive this round — {cause}")
                    save_death(self.conn, round_num, agent, cause)

            round_transactions = self._planning_and_trading_phase(round_num, phase_label, day_number, crisis)

            self.market.update(round_transactions)
            save_prices(self.conn, round_num, self.market.snapshot())
            print(f"💰 Prices after this round: {self.market.snapshot()}")

            self._check_liquidations(round_num)

            for agent in self.agents:
                save_agent_state(self.conn, round_num, agent)

        save_state(self.agents, self.market.snapshot(), last_round_run)
        self.conn.close()
        return self.transactions

    def _own_history(self, agent) -> list[str]:
        mine = [t for t in self.transactions if t["agent"] == agent.name]
        lines = []
        for t in mine[-OWN_HISTORY_LIMIT:]:
            failed_note = " [this FAILED — had no effect]" if t.get("blocked") else ""
            lines.append(
                f"Round {t['round']}: {t['action']} -> {t['target_agent']} "
                f"({t['resource']} x{t['amount']}){failed_note} — {t['reasoning']}"
            )
        return lines

    def _public_chronicle(self) -> list[str]:
        lines = []
        for t in self.transactions:
            if t.get("public_message"):
                lines.append(f"Round {t['round']}, {t['agent']} ({t['role']}): {t['public_message']}")
            if t.get("action") in ("raid", "decree") and t.get("target_agent") and not t.get("blocked"):
                verb = "RAIDED" if t["action"] == "raid" else "issued a DECREE against"
                lines.append(
                    f"Round {t['round']}, {t['agent']} ({t['role']}) {verb} {t['target_agent']} "
                    f"and took {t['amount']} {t['resource']} — the whole town knows about it."
                )
        return lines[-CHRONICLE_LIMIT:]

    def _private_context(self, agent) -> list[str]:
        mine = [
            t for t in self.transactions
            if t.get("private_message") and (t["agent"] == agent.name or t.get("dm_target") == agent.name)
        ]
        lines = []
        for t in mine[-PRIVATE_HISTORY_LIMIT:]:
            if t["agent"] == agent.name:
                lines.append(f"Round {t['round']}, you -> {t['dm_target']} (private): {t['private_message']}")
            else:
                lines.append(f"Round {t['round']}, {t['agent']} -> you (private): {t['private_message']}")
        return lines

    def _political_events(self) -> list[str]:
        events = [t for t in self.transactions if t.get("stance") in PUBLIC_STANCES and t.get("stance_target")]
        lines = []
        for t in events[-CHRONICLE_LIMIT:]:
            suffix = " as town leader" if t["stance"] == "vote_leader" else ""
            lines.append(f"Round {t['round']}, {t['agent']} {STANCE_VERBS[t['stance']]} {t['stance_target']}{suffix}.")
        return lines

    def _alliances_for(self, agent) -> set[str]:
        proposed_by: dict[str, set[str]] = {}
        for t in self.transactions:
            if t.get("stance") == "propose_alliance" and t.get("stance_target"):
                proposed_by.setdefault(t["agent"], set()).add(t["stance_target"])
        mine = proposed_by.get(agent.name, set())
        return {other for other in mine if agent.name in proposed_by.get(other, set())}

    def _active_boycotts(self) -> set[frozenset]:
        return {
            frozenset((t["agent"], t["stance_target"]))
            for t in self.transactions
            if t.get("stance") == "boycott" and t.get("stance_target")
        }

    def _current_leader(self) -> str | None:
        """Whoever has the most cumulative vote_leader stances so far. None if nobody
        has ever voted — in which case 'decree' has no legitimate wielder yet."""
        votes = [t for t in self.transactions if t.get("stance") == "vote_leader" and t.get("stance_target")]
        if not votes:
            return None
        tally: dict[str, int] = {}
        for t in votes:
            tally[t["stance_target"]] = tally.get(t["stance_target"], 0) + 1
        return max(tally, key=tally.get)

    def _social_context(self, agent, boycotts: set, current_leader: str | None) -> list[str]:
        lines = list(self._political_events())
        allies = self._alliances_for(agent)
        if allies:
            lines.append(f"You are allied with: {', '.join(sorted(allies))}.")
        for pair in boycotts:
            if agent.name in pair:
                other = next(iter(pair - {agent.name}))
                lines.append(f"There is an active boycott between you and {other} — trades between you will fail.")
        if current_leader == agent.name:
            lines.append(
                "You are the currently elected town leader — you alone can use 'decree' to "
                "legitimately seize a resource from anyone. Ordinary people can still denounce, "
                "boycott, or vote someone else in if they think you're abusing it."
            )
        elif current_leader:
            lines.append(
                f"{current_leader} is the currently elected town leader and can 'decree' to seize "
                "resources from anyone, including you. There is no leader if you'd rather vote for someone else."
            )
        else:
            lines.append("No one currently holds enough votes to be recognized as town leader.")
        lines.extend(self._debt_health_for(agent))
        return lines

    def _debt_health_for(self, agent) -> list[str]:
        """Lines describing this agent's own open collateralized positions — as
        borrower (at risk of liquidation) or as lender (exposed to the borrower)."""
        debt_price = self.market.prices.get("debt_note", 1.0)
        lines = []
        for pos in self.open_positions:
            debt_value = pos["principal"] * debt_price
            ratio = pos["collateral_gold"] / debt_value if debt_value > 0 else float("inf")
            if pos["borrower"] == agent.name:
                lines.append(
                    f"You owe {pos['principal']:.1f} debt_note to {pos['lender']}, collateralized at "
                    f"{ratio:.2f}x (liquidated below {LIQUIDATION_THRESHOLD}x)."
                )
            elif pos["lender"] == agent.name:
                lines.append(
                    f"{pos['borrower']} owes you {pos['principal']:.1f} debt_note, "
                    f"backed by {pos['collateral_gold']:.1f}g collateral (currently {ratio:.2f}x)."
                )
        return lines

    def _check_liquidations(self, round_num) -> None:
        """DeFi-style liquidation: if debt_note's market value rises enough relative to
        the locked collateral, the position gets force-closed — collateral is seized to
        repay the lender, any leftover goes back to the borrower."""
        debt_price = self.market.prices.get("debt_note", 1.0)
        still_open = []
        for pos in self.open_positions:
            debt_value = pos["principal"] * debt_price
            ratio = pos["collateral_gold"] / debt_value if debt_value > 0 else float("inf")
            if ratio >= LIQUIDATION_THRESHOLD:
                still_open.append(pos)
                continue

            borrower = self.agents_by_name.get(pos["borrower"])
            lender = self.agents_by_name.get(pos["lender"])
            seized = min(pos["collateral_gold"], debt_value)
            leftover = pos["collateral_gold"] - seized
            if lender:
                lender.resources["gold"] = lender.resources.get("gold", 0) + seized
                lender.resources["debt_note"] = lender.resources.get("debt_note", 0) - pos["principal"]
            if borrower:
                borrower.resources["gold"] = borrower.resources.get("gold", 0) + leftover
                borrower.resources["debt_note"] = borrower.resources.get("debt_note", 0) + pos["principal"]

            close_debt_position(self.conn, pos["id"], round_num, "liquidated")
            print(
                f"⚡ LIQUIDATED: {pos['borrower']}'s {pos['principal']:.1f} debt_note position "
                f"to {pos['lender']} (ratio {ratio:.2f}x fell below {LIQUIDATION_THRESHOLD}x)"
            )
        self.open_positions = still_open

    def _planning_and_trading_phase(self, round_num, phase_label, day_number, crisis) -> list[dict]:
        round_transactions = []
        boycotts = self._active_boycotts()
        current_leader = self._current_leader()
        for agent in self.agents:
            if not agent.is_alive():
                continue

            others = [a for a in self.agents if a.name != agent.name and a.is_alive()]
            action, thought = get_agent_action(
                agent, round_num, phase_label, day_number, others, self.market.snapshot(), crisis,
                self._own_history(agent), self._public_chronicle(),
                self._private_context(agent), self._social_context(agent, boycotts, current_leader),
            )
            blocked, new_position = _apply_action(
                agent, action, self.agents_by_name, boycotts, self.market, current_leader
            )
            agent.location = action.location

            if new_position:
                position_id = save_debt_position(self.conn, round_num, **new_position)
                new_position["id"] = position_id
                self.open_positions.append(new_position)

            record = {
                "round": round_num, "agent": agent.name, "role": agent.role.value,
                **action.model_dump(), "thought": thought, "blocked": blocked,
            }
            self.transactions.append(record)
            round_transactions.append(record)
            save_transaction(self.conn, round_num, agent, action, thought, blocked)

            price_note = f" @ {action.price_per_unit}g" if action.price_per_unit else ""
            if blocked and action.action == "decree":
                blocked_note = " [BLOCKED — not the elected leader]"
            elif blocked:
                blocked_note = " [BLOCKED by boycott]"
            else:
                blocked_note = ""
            print(
                f"[{agent.name}/{agent.role.value} @ {action.location}] {action.action} -> {action.target_agent} | "
                f"{action.resource} x{action.amount}{price_note}{blocked_note} — {action.reasoning}"
            )
            if new_position:
                print(f"   🔒 Collateral locked: {new_position['collateral_gold']:.1f}g")
            if action.public_message:
                print(f'   💬 {agent.name}: "{action.public_message}"')
            if action.private_message and action.dm_target:
                print(f'   🤫 {agent.name} -> {action.dm_target} (DM): "{action.private_message}"')
            if action.stance != "none" and action.stance_target:
                print(f"   🏛️ {agent.name} -> {action.stance} -> {action.stance_target}")
        return round_transactions
