"""Round orchestration: planning -> trading/settlement -> market update."""

from .agents import default_roster
from .config import (
    CHRONICLE_LIMIT,
    DAY_PHASES,
    DEATH_THRESHOLD,
    OWN_HISTORY_LIMIT,
    PRIVATE_HISTORY_LIMIT,
    ROUNDS,
    SURVIVAL_NEEDS,
)
from .crisis import apply_crisis, maybe_trigger_crisis
from .ledger import init_db, save_agent_state, save_crisis, save_death, save_prices, save_transaction
from .llm import get_agent_action
from .market import Market
from .state import load_state, save_state

TX_COLUMNS = [
    "round", "agent", "role", "action", "target_agent", "resource", "amount", "price_per_unit",
    "reasoning", "public_message", "dm_target", "private_message", "stance", "stance_target",
    "location",
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


def _apply_action(agent, action, agents_by_name, boycotts: set) -> bool:
    """Applies the resource effect of an action. Returns True if it was blocked by
    an active boycott between the two agents (trade never happens between them again)."""
    target = agents_by_name.get(action.target_agent)
    if action.action == "do_nothing" or target is None or not target.is_alive():
        return False

    if frozenset((agent.name, target.name)) in boycotts:
        return True

    if action.action == "trade":
        available = agent.resources.get(action.resource, 0)
        amount = min(action.amount, max(available, 0))
        agent.resources[action.resource] = available - amount
        target.resources[action.resource] = target.resources.get(action.resource, 0) + amount

    elif action.action == "issue_debt":
        agent.resources["debt_note"] = agent.resources.get("debt_note", 0) - action.amount
        target.resources["debt_note"] = target.resources.get("debt_note", 0) + action.amount

    elif action.action == "buy_futures":
        agent.resources[action.resource] = agent.resources.get(action.resource, 0) + action.amount

    return False


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

    def _load_past_transactions(self) -> list[dict]:
        """Loads all prior rounds from economy.db so memory, alliances, and boycotts
        stay continuous across separate runs, not just within a single one."""
        cur = self.conn.execute(f"SELECT {', '.join(TX_COLUMNS)} FROM transactions ORDER BY id")
        return [dict(zip(TX_COLUMNS, row)) for row in cur.fetchall()]

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

            for agent in self.agents:
                save_agent_state(self.conn, round_num, agent)

        save_state(self.agents, self.market.snapshot(), last_round_run)
        self.conn.close()
        return self.transactions

    def _own_history(self, agent) -> list[str]:
        mine = [t for t in self.transactions if t["agent"] == agent.name]
        return [
            f"Round {t['round']}: {t['action']} -> {t['target_agent']} "
            f"({t['resource']} x{t['amount']}) — {t['reasoning']}"
            for t in mine[-OWN_HISTORY_LIMIT:]
        ]

    def _public_chronicle(self) -> list[str]:
        spoken = [t for t in self.transactions if t.get("public_message")]
        return [
            f"Round {t['round']}, {t['agent']} ({t['role']}): {t['public_message']}"
            for t in spoken[-CHRONICLE_LIMIT:]
        ]

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

    def _social_context(self, agent, boycotts: set) -> list[str]:
        lines = list(self._political_events())
        allies = self._alliances_for(agent)
        if allies:
            lines.append(f"You are allied with: {', '.join(sorted(allies))}.")
        for pair in boycotts:
            if agent.name in pair:
                other = next(iter(pair - {agent.name}))
                lines.append(f"There is an active boycott between you and {other} — trades between you will fail.")
        return lines

    def _planning_and_trading_phase(self, round_num, phase_label, day_number, crisis) -> list[dict]:
        round_transactions = []
        boycotts = self._active_boycotts()
        for agent in self.agents:
            if not agent.is_alive():
                continue

            others = [a for a in self.agents if a.name != agent.name and a.is_alive()]
            action = get_agent_action(
                agent, round_num, phase_label, day_number, others, self.market.snapshot(), crisis,
                self._own_history(agent), self._public_chronicle(),
                self._private_context(agent), self._social_context(agent, boycotts),
            )
            blocked = _apply_action(agent, action, self.agents_by_name, boycotts)
            agent.location = action.location

            record = {
                "round": round_num, "agent": agent.name, "role": agent.role.value,
                **action.model_dump(),
            }
            self.transactions.append(record)
            round_transactions.append(record)
            save_transaction(self.conn, round_num, agent, action)

            price_note = f" @ {action.price_per_unit}g" if action.price_per_unit else ""
            blocked_note = " [BLOCKED by boycott]" if blocked else ""
            print(
                f"[{agent.name}/{agent.role.value} @ {action.location}] {action.action} -> {action.target_agent} | "
                f"{action.resource} x{action.amount}{price_note}{blocked_note} — {action.reasoning}"
            )
            if action.public_message:
                print(f'   💬 {agent.name}: "{action.public_message}"')
            if action.private_message and action.dm_target:
                print(f'   🤫 {agent.name} -> {action.dm_target} (DM): "{action.private_message}"')
            if action.stance != "none" and action.stance_target:
                print(f"   🏛️ {agent.name} -> {action.stance} -> {action.stance_target}")
        return round_transactions
