# Economy Town

A post-apocalyptic micro-economy simulator with 10 autonomous LLM agents (a
Financier, 5 Workers, 4 Farmers). Every decision — what to trade, who to lend
to, who to denounce, where to go — is made by an LLM reasoning from the
agent's role, personality, memory, and the town's live state. Nothing is
scripted.

## Research question

In a closed-loop economy with no central bank, does a self-appointed
financier's credit issuance organically build the trust infrastructure of a
banking system — or does it just concentrate risk in one node? Specifically:

1. Does credit/wealth inequality (Gini coefficient) rise as lending deepens?
2. Does `debt_note` behave like an endogenous stablecoin — holding a stable
   peg, or drifting as trust in the issuer shifts?
3. Once debt is collateralized, do liquidation cascades emerge the way they
   do in DeFi lending markets (Aave/Compound) during price shocks?

The dashboard's analytics panel computes all three live from `economy.db`.

## Structure

```
main.py                    # entry point — runs SimulationEngine
dashboard.py                 # Streamlit dashboard on top of economy.db
run_phase.sh                   # cron-friendly wrapper: advance one phase, log, exit
.github/workflows/tick.yml       # runs the town every 30 min via GitHub Actions
economy/
  config.py                      # model, phases/day, prices, crisis, collateral ratios
  models.py                       # Pydantic schema AgentAction (structured LLM output)
  agents.py                        # roles, Agent dataclass, starting roster + knowledge
  market.py                         # Market: resource prices react to supply/demand
  crisis.py                          # crisis triggers (drought, blight, marauder raid)
  llm.py                              # OpenAI/Gemini calls, role-aware system prompts
  ledger.py                           # SQLite ledger (economy.db)
  engine.py                            # SimulationEngine: phases, memory, death, liquidation
  state.py                              # checkpoint so runs continue the story, not reset it
```

## How a day works

A day is split into time-of-day phases (`Morning` / `Afternoon` / `Evening` by
default) — each is a separate LLM decision per agent, not one big decision for
the whole day. Per phase:

1. **Crisis check** — probabilistic event (droughts, blight, raids); day 1 is always calm.
2. **Survival** — food/water are consumed automatically; an agent that stays
   `critical` for enough consecutive phases dies and permanently leaves the town.
3. **Planning** — each living agent picks ONE action (`trade` / `issue_debt` /
   `buy_futures` / `do_nothing`), a location to be in, and optionally: a public
   statement to the whole town, a private DM to one other agent, and a
   political move (`endorse` / `denounce` / `boycott` / `propose_alliance` /
   `vote_leader`). Every agent's prompt includes its own recent decisions, the
   public chronicle, its private conversations, current alliances/boycotts,
   and the health of its own debt positions.
4. **Collateralized lending** — `issue_debt` is a DeFi-style loan: the
   borrower locks gold worth `COLLATERAL_RATIO`x the debt's market value.
   Each phase, every open position is re-priced; if the ratio falls below
   `LIQUIDATION_THRESHOLD`, it's force-liquidated — collateral seized to repay
   the lender, leftovers returned to the borrower.
5. **Market update** — prices move on trade volume and agent-proposed prices.
6. Everything lands in `economy.db`: `transactions`, `agent_states`, `prices`,
   `crisis_events`, `deaths`, `debt_positions`.

## Run

```bash
pip install -r requirements.txt

# Option A (default, free) — get a key at aistudio.google.com/apikey, no card needed
export GEMINI_API_KEY="..."

# Option B — paid OpenAI
export LLM_PROVIDER="openai"
export OPENAI_API_KEY="sk-..."

python3 main.py                 # advance one full day (all phases), continuing the story
python3 main.py --rounds 1      # advance exactly one phase
python3 main.py --fresh         # start a brand-new town instead of continuing
streamlit run dashboard.py      # open the live dashboard
```

### Running it 24/7

`.github/workflows/tick.yml` advances the town by one phase every 30 minutes
on GitHub's infrastructure — no server to pay for or keep on. It runs
`main.py --rounds 1` with `GEMINI_API_KEY` from a repo secret, then commits
`economy.db` and `town_state.json` back to the repo, so the story keeps
compounding across runs. Trigger it manually from the Actions tab, or just
wait for the schedule.

## Scaling (planned)

- New roles: `Marauder`, `Doctor`, `Engineer` already exist in `Role`
  (`economy/agents.py`), but no logic is wired up for them yet.
- Nearly every constant (`SURVIVAL_NEEDS`, `CRISIS_CHANCE`, `PRICE_ELASTICITY`,
  `DEATH_THRESHOLD`, `COLLATERAL_RATIO`, `LIQUIDATION_THRESHOLD`, `DAY_PHASES`)
  lives in `economy/config.py`.
- The Financier is the only agent who remembers pre-collapse finance (barter →
  commodity money → banknotes → credit → crypto/tokenomics) and decides for
  itself when to share that via `public_message`. Whether the town organically
  arrives at needing a trusted intermediary is meant to emerge from the
  agents' own reasoning, not be hardcoded.
