"""Global simulation settings."""

import os
from pathlib import Path

from dotenv import load_dotenv

# Loads GEMINI_API_KEY / OPENAI_API_KEY / LLM_PROVIDER from a .env file in the
# project root, if present. Variables already set in the environment take priority.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# "gemini" (free tier, no card required) or "openai". Switched via the LLM_PROVIDER
# environment variable so you never have to edit code to change providers.
PROVIDER = os.environ.get("LLM_PROVIDER", "gemini").lower()

MODEL_BY_PROVIDER = {
    "gemini": "gemini-3.5-flash-lite",  # free tier (gemini-2.5-flash-lite was retired for new users)
    "openai": "gpt-4o-mini",
}
MODEL = MODEL_BY_PROVIDER.get(PROVIDER, MODEL_BY_PROVIDER["gemini"])

# A "day" in the town's life is split into several time-of-day phases — each one is a
# separate round with its own LLM decision, so a full day is several real decisions and
# real (declared) movement, not a single instant action. ROUNDS below is in units of
# phases, so ROUNDS = len(DAY_PHASES) advances the town by exactly one full day.
DAY_PHASES = ["Morning", "Afternoon", "Evening"]

ROUNDS = len(DAY_PHASES)

DB_PATH = Path(__file__).resolve().parent.parent / "economy.db"

# Original design targets were "per day" — rescaled per phase so the town's overall
# pace (how fast people starve, how often crises hit) stays the same as before, just
# spread across more, smaller decisions instead of one big one.
_DAILY_SURVIVAL_NEEDS = {"food": 2, "water": 1}
SURVIVAL_NEEDS = {k: v / len(DAY_PHASES) for k, v in _DAILY_SURVIVAL_NEEDS.items()}

# Starting market prices (gold per unit).
BASE_PRICES = {"food": 2.0, "water": 1.5, "debt_note": 1.0}

# How strongly a round's supply/demand shifts the price (0..1).
PRICE_ELASTICITY = 0.15

# Probability of at least one crisis per DAY was 0.35 — rescaled to a per-phase roll so
# multiple phases per day don't multiply the odds. Day 1 is always calm either way.
_DAILY_CRISIS_CHANCE = 0.35
CRISIS_CHANCE = 1 - (1 - _DAILY_CRISIS_CHANCE) ** (1 / len(DAY_PHASES))

# How many CONSECUTIVE phases (not days) an agent must stay in critical (both food and
# water below zero) before dying — equivalent to 2 full days, same as before.
DEATH_THRESHOLD = 2 * len(DAY_PHASES)

# How many of their own last decisions, how many town-wide public statements, and how
# many private DMs (sent or received) an agent sees in its prompt.
OWN_HISTORY_LIMIT = 4
CHRONICLE_LIMIT = 10
PRIVATE_HISTORY_LIMIT = 6

# Collateralized lending (DeFi-style, mirrors Aave/Compound): issuing debt_note requires
# locking gold worth COLLATERAL_RATIO times the debt's current market value. If the
# debt's value rises relative to the locked collateral and the ratio falls below
# LIQUIDATION_THRESHOLD, the position is force-liquidated: collateral is seized to repay
# the lender, any leftover returns to the borrower.
COLLATERAL_RATIO = 1.5
LIQUIDATION_THRESHOLD = 1.2
