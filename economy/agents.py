"""Agent roles and state for the town."""

from dataclasses import dataclass, field
from enum import Enum


class Role(str, Enum):
    FINANCIER = "Financier"
    WORKER = "Worker"
    FARMER = "Farmer"
    # Planned roles for future scaling (not yet active in this simulation).
    MARAUDER = "Marauder"
    DOCTOR = "Doctor"
    ENGINEER = "Engineer"


@dataclass
class Agent:
    name: str
    role: Role
    personality: str
    knowledge: str = ""  # what the agent understands/remembers about finance & economics
    resources: dict = field(default_factory=dict)
    status: str = "ok"  # ok | hungry | thirsty | critical | dead
    critical_streak: int = 0  # how many rounds IN A ROW the agent has been critical (for death)
    location: str = "Town Square"  # Bank | Farms | Workshops | Town Square — where they are now

    def is_alive(self) -> bool:
        return self.status != "dead"


def default_roster() -> list[Agent]:
    """Starting town roster: 1 financier, 5 workers, 4 farmers.

    `knowledge` and `personality` are deliberately uneven — some agents trust the
    Financier, some don't, some are gossips or conspiracy-minded, so private DMs
    between them have real texture instead of everyone sounding the same.
    """
    return [
        Agent(
            "Marcus", Role.FINANCIER, "calculating, careful with his own capital",
            knowledge=(
                "Remembers how the economy worked before the collapse: barter -> commodity "
                "money -> banknotes -> bank credit at interest -> in the last years before "
                "the collapse, even cryptocurrencies and tokenomics. The only person in town "
                "who understands this — everyone else grew up after the collapse."
            ),
            location="Bank",
            resources={"food": 5, "water": 5, "debt_note": 0, "gold": 150},
        ),
        Agent(
            "Anna", Role.WORKER, "practical, values stability",
            knowledge="Never saw the old financial world. Trusts only what can be eaten or drunk right now.",
            location="Workshops",
            resources={"food": 10, "water": 10, "debt_note": 0, "gold": 15},
        ),
        Agent(
            "Ivan", Role.WORKER, "risk-taking, drives a hard bargain",
            knowledge=(
                "Has heard scattered stories about 'banks' and 'credit' from elders. "
                "Curious about new ideas if he sees a personal upside in them."
            ),
            location="Workshops",
            resources={"food": 10, "water": 10, "debt_note": 0, "gold": 15},
        ),
        Agent(
            "Dmytro", Role.WORKER, "paranoid, quick to suspect hidden motives",
            knowledge=(
                "Grew up hearing warnings that any centralized system always ends in betrayal. "
                "Assumes anyone offering an easy deal wants something bigger in return."
            ),
            location="Workshops",
            resources={"food": 10, "water": 10, "debt_note": 0, "gold": 15},
        ),
        Agent(
            "Sofia", Role.WORKER, "a gossip who trades in information as much as goods",
            knowledge=(
                "Doesn't have much to offer materially, but always knows who owes whom and who "
                "said what to whom. Treats information itself as a kind of currency."
            ),
            location="Workshops",
            resources={"food": 8, "water": 8, "debt_note": 0, "gold": 10},
        ),
        Agent(
            "Taras", Role.WORKER, "nihilistic, quietly hoards for himself",
            knowledge=(
                "Doesn't believe any system, old or new, will protect him in the end. "
                "Prefers to hoard quietly rather than join anyone's scheme."
            ),
            location="Workshops",
            resources={"food": 12, "water": 12, "debt_note": 0, "gold": 20},
        ),
        Agent(
            "Olena", Role.FARMER, "generous, but doesn't trust debt",
            knowledge="Used to direct exchange. Considers any paper or promise a waste of time.",
            location="Farms",
            resources={"food": 35, "water": 15, "debt_note": 0, "gold": 5},
        ),
        Agent(
            "Petro", Role.FARMER, "suspicious of the financier",
            knowledge="Suspects the Financier is out to profit off others. Doesn't trust his offers without proof.",
            location="Farms",
            resources={"food": 35, "water": 15, "debt_note": 0, "gold": 5},
        ),
        Agent(
            "Yuri", Role.FARMER, "a secretive loner",
            knowledge=(
                "Keeps to himself and rarely reveals how much he actually has stored away. "
                "Prefers quiet, private deals over anything said in front of the whole town."
            ),
            location="Farms",
            resources={"food": 30, "water": 18, "debt_note": 0, "gold": 5},
        ),
        Agent(
            "Kateryna", Role.FARMER, "an alliance-builder who plays people, not just crops",
            knowledge=(
                "Believes surviving the collapse is about who you know, not just what you have. "
                "Actively cultivates private alliances and isn't above a little manipulation."
            ),
            location="Farms",
            resources={"food": 30, "water": 18, "debt_note": 0, "gold": 8},
        ),
    ]
