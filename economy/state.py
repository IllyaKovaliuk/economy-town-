"""Persists the town's state between separate `python3 main.py` runs, so each
run continues the story (next rounds, same agents, same resources) instead of
resetting the town from scratch every time.

economy.db keeps the full history forever (for the dashboard/analysis).
town_state.json only holds "where things currently stand" (for resuming).
"""

import json
from pathlib import Path

from .agents import Agent, Role
from .config import DB_PATH

STATE_PATH = DB_PATH.parent / "town_state.json"


def save_state(agents: list[Agent], market_prices: dict, last_round: int, path=STATE_PATH) -> None:
    data = {
        "last_round": last_round,
        "market_prices": market_prices,
        "agents": [
            {
                "name": a.name,
                "role": a.role.value,
                "personality": a.personality,
                "knowledge": a.knowledge,
                "resources": a.resources,
                "status": a.status,
                "critical_streak": a.critical_streak,
                "location": a.location,
            }
            for a in agents
        ],
    }
    Path(path).write_text(json.dumps(data, indent=2))


def load_state(path=STATE_PATH):
    """Returns (agents, market_prices, last_round), or None if no checkpoint exists."""
    p = Path(path)
    if not p.exists():
        return None
    data = json.loads(p.read_text())
    agents = [
        Agent(
            name=a["name"], role=Role(a["role"]), personality=a["personality"],
            knowledge=a["knowledge"], resources=a["resources"], status=a["status"],
            critical_streak=a["critical_streak"], location=a.get("location", "Town Square"),
        )
        for a in data["agents"]
    ]
    return agents, data["market_prices"], data["last_round"]
