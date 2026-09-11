"""LLM calls that produce a structured agent action.

The provider is switched via the LLM_PROVIDER=gemini|openai environment
variable (see economy/config.py). Default is Gemini (free tier).
"""

from .agents import Role
from .config import COLLATERAL_RATIO, LIQUIDATION_THRESHOLD, MODEL, PROVIDER
from .models import AgentAction

_openai_client = None
_gemini_client = None


def _get_openai_client():
    """Lazy init — so importing this module doesn't require OPENAI_API_KEY."""
    global _openai_client
    if _openai_client is None:
        from openai import OpenAI
        _openai_client = OpenAI()
    return _openai_client


def _get_gemini_client():
    """Lazy init — so importing this module doesn't require GEMINI_API_KEY."""
    global _gemini_client
    if _gemini_client is None:
        from google import genai
        _gemini_client = genai.Client()
    return _gemini_client


BASE_SYSTEM_PROMPT = (
    "You are an agent in a post-apocalyptic simulation of a small town. "
    "Resources are scarce, crisis is all around. Decide based only on "
    "your role, personality, knowledge, memory of past rounds, and the town's situation. "
    "Respond only with a structured action object."
)

FINANCIER_SYSTEM_ADDENDUM = (
    " You remember how the financial system worked before the collapse, and the other "
    "townspeople do not. You are not obligated to share this knowledge right away or in "
    "full — decide for yourself when and what is worth revealing via public_message, and "
    "whether it's even in your interest for others to know."
)

OTHER_SYSTEM_ADDENDUM = (
    " You grew up after the collapse and never saw the old financial world — abstract "
    "promises and paper mean nothing to you by themselves; trust has to be earned in practice."
)


def _system_prompt(role: Role) -> str:
    if role == Role.FINANCIER:
        return BASE_SYSTEM_PROMPT + FINANCIER_SYSTEM_ADDENDUM
    return BASE_SYSTEM_PROMPT + OTHER_SYSTEM_ADDENDUM


def _status_line(agent) -> str:
    if agent.status == "critical":
        return "🔴 critical condition — on the brink of survival"
    if agent.status in ("hungry", "thirsty"):
        return f"🟡 {agent.status} — urgently needs to restock resources"
    return "🟢 stable condition"


def build_prompt(
    agent, round_num, phase_label, day_number, others, prices, crisis,
    own_history, chronicle, private_context, social_context,
) -> str:
    others_desc = (
        "\n".join(f"- {o.name} ({o.role.value}, at {o.location}): {o.resources}" for o in others)
        or "(no one left)"
    )
    crisis_line = f"\n⚠️ Event this time: {crisis.description}" if crisis else ""
    history_block = "\n".join(f"- {h}" for h in own_history) if own_history else "(nothing done yet)"
    chronicle_block = "\n".join(f"- {c}" for c in chronicle) if chronicle else "(no one has announced anything yet)"
    private_block = "\n".join(f"- {p}" for p in private_context) if private_context else "(no private messages yet)"
    social_block = "\n".join(f"- {s}" for s in social_context) if social_context else "(no political moves yet)"

    day_one_line = (
        "\n\nThis is it — the first day you're fully facing what happened. The old world "
        "is gone, and it's just now sinking in for real. You're disoriented, maybe scared, "
        "processing it in real time along with everyone else. It's natural to say something "
        "out loud about it (public_message) or confide in someone privately — react like a "
        "real person would on the day it actually hits them, not like someone who's had "
        "months to get used to it."
        if day_number == 1 else ""
    )

    return (
        f"It's {phase_label} on Day {day_number} of the town's ongoing story.{day_one_line}\n"
        f"You are {agent.name}, role: {agent.role.value}.\n"
        f"Personality: {agent.personality}.\n"
        f"Your knowledge of finance/economics: {agent.knowledge}\n"
        f"Your condition: {_status_line(agent)}\n"
        f"Your current location: {agent.location}.\n"
        f"Your resources: {agent.resources}.\n"
        f"Current market prices (gold/unit): {prices}.{crisis_line}\n\n"
        f"Your recent decisions:\n{history_block}\n\n"
        f"Public statements from townspeople (chronicle):\n{chronicle_block}\n\n"
        f"Your private conversations (only you and the other party ever see these):\n{private_block}\n\n"
        f"Town politics (endorsements, denouncements, leader votes, your alliances, active boycotts):\n{social_block}\n\n"
        f"Living townspeople and where they currently are:\n{others_desc}\n\n"
        "Decide where you are this time of day via location, and choose ONE action: "
        "trade (exchange resources at market or your own price), "
        "issue_debt (a collateralized loan, like DeFi lending — you lock gold worth "
        f"{COLLATERAL_RATIO}x the debt's value as collateral; if the debt's market value "
        f"rises too much relative to your collateral, dropping below {LIQUIDATION_THRESHOLD}x, "
        "it gets force-liquidated and you lose the collateral — typically the Financier's role, "
        "but anyone with gold to spare can lend), "
        "buy_futures (buy a futures contract on a resource — typically the Financier's role), "
        "raid (forcibly take a resource from target_agent — no consent needed, but the whole "
        "town automatically hears about it and may denounce, boycott, or retaliate against you), "
        "decree (the same forced seizure, but only has any effect if you are currently the "
        "elected town leader — a legitimate act of power rather than theft; it's a no-op for "
        "anyone else), or do_nothing.\n"
        "Workers sell labor and buy food/water. Farmers sell food and water. "
        "The Financier manages liquidity, can propose prices via price_per_unit, "
        "and issue credit to those in need.\n"
        "If you want to say something out loud to the whole town (advice, a warning, a "
        "proposal), fill in public_message; otherwise leave it empty.\n"
        "If you want to say something privately to exactly one other agent — a rumor, a "
        "secret alliance, a suspicion, a conspiracy theory — set dm_target to their name and "
        "fill in private_message. This is independent of your trade action and public_message: "
        "you can trade with one person, privately message a different one, and announce "
        "something to the whole town, all in the same round. No one but dm_target will ever "
        "see private_message.\n"
        "You can also make ONE political move via stance + stance_target: 'endorse' someone as "
        "a leader candidate, 'denounce' someone publicly, 'boycott' someone (this permanently "
        "blocks any future trade between the two of you — think carefully before using it), "
        "'propose_alliance' with someone (only becomes real if they also propose you), or "
        "'vote_leader' for who you think should lead the town. Use stance 'none' if you have "
        "no political move this round — you don't need to use this every round."
    )


THINKING_LEVEL = "medium"  # Gemini-only: none visible at "low", ~584 thinking tokens at "medium"


def _call_openai(prompt: str, system_prompt: str) -> tuple[AgentAction, None]:
    completion = _get_openai_client().beta.chat.completions.parse(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        response_format=AgentAction,
    )
    # gpt-4o-mini isn't a reasoning model — no chain-of-thought to capture here.
    return completion.choices[0].message.parsed, None


def _call_gemini(prompt: str, system_prompt: str) -> tuple[AgentAction, str | None]:
    response = _get_gemini_client().models.generate_content(
        model=MODEL,
        contents=prompt,
        config={
            "system_instruction": system_prompt,
            "response_mime_type": "application/json",
            "response_schema": AgentAction,
            "thinking_config": {"include_thoughts": True, "thinking_level": THINKING_LEVEL},
        },
    )
    thought_parts = [
        part.text for part in response.candidates[0].content.parts
        if getattr(part, "thought", False) and part.text
    ]
    thought = "\n".join(thought_parts) if thought_parts else None
    return response.parsed, thought


def get_agent_action(
    agent, round_num, phase_label, day_number, others, prices, crisis,
    own_history, chronicle, private_context, social_context,
) -> tuple[AgentAction, str | None]:
    """Returns (action, thought) — thought is the model's raw chain-of-thought (Gemini
    only, None for OpenAI), kept separate from the short `reasoning` field in the
    structured action so it can be stored/shown without feeding back into future prompts."""
    prompt = build_prompt(
        agent, round_num, phase_label, day_number, others, prices, crisis,
        own_history, chronicle, private_context, social_context,
    )
    system_prompt = _system_prompt(agent.role)
    if PROVIDER == "openai":
        return _call_openai(prompt, system_prompt)
    return _call_gemini(prompt, system_prompt)
