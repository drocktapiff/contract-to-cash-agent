"""Explicit API inputs; prices and money travel as decimal strings, never floats."""

from decimal import Decimal
from typing import Literal
from uuid import UUID
from .operator_auth import MIN_OPERATOR_PASSWORD_LENGTH, MAX_OPERATOR_PASSWORD_LENGTH
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Login(Input):
    token: str = Field(
        min_length=MIN_OPERATOR_PASSWORD_LENGTH, max_length=MAX_OPERATOR_PASSWORD_LENGTH
    )


class Launch(Input):
    idempotency_key: UUID
    acknowledge_paid: Literal[True]
    objective: str = Field(
        default="Investigate contractual billing discrepancies and shared patterns. Challenge findings with source evidence and request human review. Do not change billing.",
        min_length=10,
        max_length=2000,
    )
    max_tool_calls: int = Field(default=35, ge=1, le=35)
    max_responses: int = Field(default=40, ge=1, le=40)
    max_seconds: int = Field(default=180, ge=1, le=180)
    max_cost_usd: Decimal = Field(default=Decimal("1"), gt=0, le=1)
    input_price: Decimal = Field(gt=0, le=1000)
    output_price: Decimal = Field(gt=0, le=1000)
    cached_input_price: Decimal = Field(ge=0, le=1000)

    @model_validator(mode="after")
    def valid_prices(self):
        if self.cached_input_price > self.input_price:
            raise ValueError("Cached input price cannot exceed regular input price")
        return self


class ReviewAction(Input):
    decision: Literal["approved", "rejected", "needs_information"]
    rationale: str = Field(min_length=5, max_length=1000)
    expected_revision: str = Field(min_length=1, max_length=100)
    expected_version: int = Field(ge=1)


class Health(BaseModel):
    application_id: Literal["ledgerline-contract-operations"] = "ledgerline-contract-operations"
    status: str
    mode: Literal["operator", "recorded"]
    api_key_configured: bool
    operator_configured: bool
    dataset_ready: bool
    launch_available: bool
    message: str


class EventView(BaseModel):
    sequence: int
    timestamp: str
    type: str
    actor: str
    summary: str
    tool: str | None = None
    customer_ids: list[str] = Field(default_factory=list)
    finding_id: str | None = None
    decision: str | None = None
    reviewer: str | None = None
    rationale: str | None = None
    data_revision: str | None = None
    finding_version: int | None = None


class RunView(BaseModel):
    id: str
    mode: Literal["live", "recorded"]
    status: str
    reason: str
    created_at: str
    period: str
    model: str
    data_revision: str | None = None
    report_event_sequence: int = 0
    last_event_sequence: int = 0
    pricing_verification: dict | None = None
    screening_complete: bool = False
    customers_compared: list[str] = Field(default_factory=list)
    customers_with_retrieved_documents: list[str] = Field(default_factory=list)
    findings: list[dict] = Field(default_factory=list)
    reviews: list[dict] = Field(default_factory=list)
    candidates: list[dict] = Field(default_factory=list)
    financial_totals: dict = Field(default_factory=dict)
    metrics: dict = Field(default_factory=dict)


class DatasetView(BaseModel):
    period: str
    customer_count: int | None
    invoice_count: int | None
    currency: str = "CAD"
    data_revision: str | None = None
    message: str
