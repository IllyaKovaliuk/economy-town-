"""Pydantic schemas for structured LLM responses."""

from typing import Literal, Optional

from pydantic import BaseModel, Field


class AgentAction(BaseModel):
    action: Literal["trade", "issue_debt", "buy_futures", "raid", "decree", "do_nothing"] = Field(
        description=(
            "The type of action the agent takes. 'raid' forcibly takes a resource from "
            "target_agent regardless of consent — everyone in town will hear about it. "
            "'decree' does the same but is only effective if you are the currently elected "
            "town leader (a no-op otherwise) — a legitimate use of power, not theft."
        )
    )
    target_agent: str = Field(
        description="The name of the agent this action targets (or 'none' if no target is needed)"
    )
    resource: Literal["food", "water", "debt_note"] = Field(
        description="The resource being offered or requested"
    )
    amount: float = Field(ge=0, description="Quantity of the resource")
    price_per_unit: Optional[float] = Field(
        default=None,
        ge=0,
        description=(
            "Price per unit the agent is proposing (relevant for trade, and for the "
            "Financier who sets market prices). None if not applicable."
        ),
    )
    reasoning: str = Field(description="A short explanation of the decision (1-2 sentences)")
    public_message: Optional[str] = Field(
        default=None,
        description=(
            "An optional short public statement/advice/warning to the whole town (1-2 sentences). "
            "Other agents will see it in future rounds. None if the agent says nothing out loud."
        ),
    )
    dm_target: Optional[str] = Field(
        default=None,
        description=(
            "Name of the single agent who should privately receive private_message. "
            "Required if private_message is set, otherwise None. Independent of target_agent — "
            "you can trade with one agent and privately message a different one in the same round."
        ),
    )
    private_message: Optional[str] = Field(
        default=None,
        description=(
            "An optional short private message (1-2 sentences) to exactly one other agent — a "
            "rumor, a secret alliance, a suspicion, a conspiracy theory. Only dm_target will ever "
            "see this, never the rest of the town. None if the agent has nothing private to say."
        ),
    )
    stance: Literal["none", "endorse", "denounce", "boycott", "propose_alliance", "vote_leader"] = Field(
        default="none",
        description=(
            "An optional social/political move toward exactly one other agent (paired with "
            "stance_target): 'endorse' publicly supports them as a leader; 'denounce' publicly "
            "shames or criticizes them; 'boycott' permanently refuses to trade or deal with them "
            "from now on; 'propose_alliance' privately signals wanting to team up with them (becomes "
            "a real alliance only if they also propose you back); 'vote_leader' casts your vote for "
            "who should lead the town this round. Use 'none' if you have no political move this round."
        ),
    )
    stance_target: Optional[str] = Field(
        default=None,
        description="Name of the agent your stance applies to. Required if stance is not 'none', otherwise None.",
    )
    location: Literal["Bank", "Farms", "Workshops", "Town Square"] = Field(
        default="Town Square",
        description=(
            "Where you physically are/choose to go this time of day. Move somewhere if it fits "
            "your plans — e.g. go to the Bank to deal with the Financier, stay on the Farms to "
            "work, head to the Town Square to meet people. This doesn't restrict who you can "
            "trade with or talk to; it's simply where you are right now."
        ),
    )
