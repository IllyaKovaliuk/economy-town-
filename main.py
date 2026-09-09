"""Entry point: runs the Economy Town simulation.

By default, each run continues the story from town_state.json (if it exists) —
so running this daily advances the town day by day instead of resetting it.
Pass --fresh to ignore any saved state and start a brand-new town.
Pass --rounds N to advance exactly N time-of-day phases this run (overrides the
config default of a full day) — used to run one phase per real-world trigger,
e.g. from cron, so the town's morning/afternoon/evening line up with the real one.
"""

import os
import sys

from economy.config import PROVIDER, ROUNDS
from economy.engine import SimulationEngine

REQUIRED_KEY = {"gemini": "GEMINI_API_KEY", "openai": "OPENAI_API_KEY"}


def _rounds_override() -> int:
    if "--rounds" in sys.argv:
        idx = sys.argv.index("--rounds")
        return int(sys.argv[idx + 1])
    return ROUNDS


def main():
    key_name = REQUIRED_KEY.get(PROVIDER, "GEMINI_API_KEY")
    if not os.environ.get(key_name):
        raise SystemExit(
            f"Provider '{PROVIDER}' (LLM_PROVIDER) requires the {key_name} environment variable. "
            "Set it before running, or change LLM_PROVIDER in .env."
        )

    fresh = "--fresh" in sys.argv
    engine = SimulationEngine(rounds=_rounds_override(), resume=not fresh)
    transactions = engine.run()

    print("\n=== Town state at the end of this run ===")
    for agent in engine.agents:
        print(f"{agent.name} ({agent.role.value}, {agent.status}): {agent.resources}")

    print(f"\n{len(transactions)} new transactions this run — full history is in economy.db.")
    print("Run again (no flags) to continue the story, or with --fresh to start a new town.")


if __name__ == "__main__":
    main()
