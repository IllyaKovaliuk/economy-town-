# Economy Town

A post-apocalyptic micro-economy simulator with 5 autonomous LLM agents
(a Financier, 2× Worker, 2× Farmer). Each round, agents receive context
(their resources, personality, knowledge, market prices, crises, their own
recent decisions, and the town's public chronicle) and return a structured
action defined by a Pydantic schema.

The LLM provider is switched without touching code — `openai` (`gpt-4o-mini`)
or `gemini` (`gemini-2.5-flash-lite`, default, Google AI Studio's free tier:
no card required, 1000 requests/day — far more than one simulation run needs).

## Structure

```
main.py              # entry point — runs SimulationEngine
dashboard.py          # Streamlit dashboard on top of economy.db
economy/
  config.py            # settings (model, round count, prices, crisis, death threshold)
  models.py             # Pydantic schema AgentAction
  agents.py              # roles (Role), Agent dataclass, starting roster + knowledge
  market.py                # Market: resource prices, react to supply/demand
  crisis.py                 # simple crisis triggers (drought, blight, raid)
  llm.py                     # OpenAI/Gemini calls, role-aware system prompts
  ledger.py                   # SQLite ledger (economy.db)
  engine.py                    # SimulationEngine: round phases, memory, death
```

## Round phases (engine.py)

1. **Crisis check** — with probability `CRISIS_CHANCE` an event happens (round 1 is always calm).
2. **Survival needs** — each living agent automatically spends food/water; status
   (`ok` / `hungry` / `thirsty` / `critical` / `dead`) is visible to the agent in its next prompt.
   An agent that stays `critical` (both food and water negative) for `DEATH_THRESHOLD`
   consecutive rounds dies and permanently leaves the simulation.
3. **Planning + trading** — each living agent, through the LLM, picks an action
   (`trade` / `issue_debt` / `buy_futures` / `do_nothing`), optionally says something
   out loud to the whole town (`public_message`), and the action is applied to resources
   immediately. Each agent's prompt includes its own recent decisions and the town's
   recent public statements, so trust and shared knowledge can build up over rounds.
4. **Market update** — prices shift based on trade volume and prices proposed by agents
   (typically the Financier).
5. Everything is logged to `economy.db`: `transactions`, `agent_states`, `prices`,
   `crisis_events`, `deaths`.

## Run

```bash
pip install -r requirements.txt

# Option A (default, free) — get a key at aistudio.google.com/apikey, no card needed
export GEMINI_API_KEY="..."

# Option B — paid OpenAI
export LLM_PROVIDER="openai"
export OPENAI_API_KEY="sk-..."

python3 main.py                 # run the simulation, populate economy.db
streamlit run dashboard.py      # open the live dashboard (prices, resources, log, crises, deaths)
```

## Scaling (planned)

- New roles: `Marauder`, `Doctor`, `Engineer` already exist in `Role` (economy/agents.py),
  but no logic is wired up for them yet.
- `SURVIVAL_NEEDS`, `CRISIS_CHANCE`, `PRICE_ELASTICITY`, `DEATH_THRESHOLD`, `ROUNDS` —
  all live in `economy/config.py`.
- The Financier is the only agent who remembers pre-collapse finance (barter → commodity
  money → banknotes → credit → crypto/tokenomics), and can choose when to share that
  knowledge via `public_message`. Whether the town organically arrives at needing a
  trusted intermediary for barter is meant to emerge from the agents' own reasoning,
  not be hardcoded.
