"""Evidence-backed document and revenue-operations work-item contracts."""

from dataclasses import dataclass, field, asdict
from typing import Protocol


@dataclass
class Evidence:
    document_id: str
    file_hash: str
    page: int
    start: int
    end: int
    text: str
    extraction_method: str = "pypdf_text+label_baseline_v1"
    validation_status: str = "extracted_not_independent_authority"
    source_record_reference: str = ""


@dataclass
class Document:
    document_id: str
    file_hash: str
    filename: str
    document_type: str | None
    customer_id: str | None
    contract_id: str | None
    fields: dict
    evidence: dict[str, list[dict]]
    pages: list[str]
    errors: list[str] = field(default_factory=list)
    provenance: dict = field(
        default_factory=lambda: dict(
            source="actual_pdf_bytes",
            processing="deterministic_baseline",
            synthetic=None,
            paid_model_calls=0,
        )
    )

    def dump(self):
        return asdict(self)


@dataclass
class WorkItem:
    work_item_id: str
    source_documents: list[str]
    customer_id: str | None
    contract_id: str | None
    business_object_type: str
    business_object_id: str
    category: str
    required_action: str
    original_functional_owner: str
    assigned_role: str
    status: str
    supporting_facts: dict
    evidence: list[dict]
    financial_impact: dict | None
    suggested_next_action: str
    automation_eligible: bool
    eligibility_reason: str
    human_review_required: bool
    automatic_closure_allowed: bool
    intentionally_unresolved: bool
    created_at: str
    updated_at: str
    event_history: list[dict]
    provenance: dict

    def dump(self):
        return asdict(self)


class OptionalExtractionAdvisor(Protocol):
    """Opt-in proposals only. No live provider implementation or automatic invocation.

    Future adapters must implement paid consent/pricing/quota accounting externally.
    Proposals cannot change validated fields, financial rules or source authority.
    """

    def propose(self, document: dict) -> dict: ...
