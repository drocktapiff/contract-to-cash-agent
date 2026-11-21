"""Future advisory interface; no provider implementation or automatic invocation.

Live adapters require the existing paid authorization/admission/accounting controls.
Validated proposals remain non-authoritative; workflow rules never consume prose as
financial facts or contractual authority. The web workspace uses deterministic rules.
"""

from typing import Literal, Protocol
from pydantic import BaseModel, ConfigDict, Field


class RecommendationProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    suggested_disposition: Literal["review", "request_evidence", "escalate", "financial_review"]
    why: str = Field(min_length=1, max_length=2000)
    evidence_hashes: list[str] = Field(min_length=1, max_length=50)
    human_judgment_required: str = Field(min_length=1, max_length=2000)


class RecommendationAdvisor(Protocol):
    """An adapter must not be constructed/called by free demonstration commands."""

    def propose(self, work_item: dict, documents: list[dict]) -> RecommendationProposal: ...


def validate_proposal(payload, work_item):
    proposal = RecommendationProposal.model_validate(payload)
    if len(proposal.evidence_hashes) != len(set(proposal.evidence_hashes)):
        raise ValueError("Recommendation citations must be unique")
    if not set(proposal.evidence_hashes).issubset(work_item["supporting_facts"]):
        raise ValueError("Recommendation references evidence outside the work item")
    return {
        "source": "Unverified advisory proposal",
        "authority": False,
        "proposal": proposal.model_dump(),
    }
