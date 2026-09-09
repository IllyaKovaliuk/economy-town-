"""Simple crisis triggers: drought, crop blight, marauder raid."""

import random
from dataclasses import dataclass
from typing import Optional

from .config import CRISIS_CHANCE

CRISIS_CATALOG = [
    {
        "type": "drought",
        "description": "Drought: water sources are drying up, farmers lose part of their water stock.",
        "resource": "water",
        "magnitude": 0.3,
        "affects": "Farmer",
    },
    {
        "type": "blight",
        "description": "Crop blight: farmers lose part of their food stock.",
        "resource": "food",
        "magnitude": 0.25,
        "affects": "Farmer",
    },
    {
        "type": "raid",
        "description": "Marauder raid: everyone in town loses part of their gold.",
        "resource": "gold",
        "magnitude": 0.2,
        "affects": "all",
    },
]


@dataclass
class CrisisEvent:
    round: int
    type: str
    description: str
    resource: str
    magnitude: float
    affects: str


def maybe_trigger_crisis(round_num: int, day_number: int) -> Optional[CrisisEvent]:
    if day_number == 1:
        return None  # the first day is always calm, so agents have time to get their bearings
    if random.random() > CRISIS_CHANCE:
        return None
    template = random.choice(CRISIS_CATALOG)
    return CrisisEvent(round=round_num, **template)


def apply_crisis(agents, crisis: CrisisEvent) -> None:
    for agent in agents:
        if crisis.affects != "all" and agent.role.value != crisis.affects:
            continue
        current = agent.resources.get(crisis.resource, 0)
        loss = round(current * crisis.magnitude, 2)
        agent.resources[crisis.resource] = max(current - loss, 0)
