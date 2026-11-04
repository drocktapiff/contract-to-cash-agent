"""Administrator-attested pricing. No invented rates or paid verification requests."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, Field, model_validator
from .models import Input, Launch
from .store import StoreError

OFFICIAL_PRICING = "https://developers.openai.com/api/docs/pricing"


class PricingConfirmation(Input):
    model: Literal["gpt-6.1-sol"] = "gpt-6.1-sol"
    service_tier: Literal["default"] = "default"
    currency: Literal["USD"] = "USD"
    source: Literal["https://developers.openai.com/api/docs/pricing"] = OFFICIAL_PRICING
    input_price: Decimal = Field(gt=0, le=1000)
    output_price: Decimal = Field(gt=0, le=1000)
    cached_input_price: Decimal = Field(ge=0, le=1000)
    checked_current_official_rates: Literal[True]

    @model_validator(mode="after")
    def valid_prices(self):
        if self.cached_input_price > self.input_price:
            raise ValueError("Cached input price cannot exceed regular input price")
        return self


class BillingReviewRequest(Input):
    idempotency_key: UUID
    acknowledge_paid: Literal[True]


class SavedPricing(Input):
    rates: PricingConfirmation
    confirmed_by: str = Field(min_length=1, max_length=200)
    confirmed_at: datetime
    expires_at: datetime
    verification_method: Literal["local_administrator_attestation"]


class PricingLimits(BaseModel):
    maximum_seconds: int
    spending_limit_usd: str
    max_tool_calls: int
    max_responses: int


class PricingState(BaseModel):
    ready: bool
    reason: str
    profile: SavedPricing | None
    limits: PricingLimits


def state_view(ready, reason, profile):
    return dict(
        ready=ready,
        reason=reason,
        profile=profile,
        limits=dict(
            maximum_seconds=Launch.model_fields["max_seconds"].default,
            spending_limit_usd=str(Launch.model_fields["max_cost_usd"].default),
            max_tool_calls=Launch.model_fields["max_tool_calls"].default,
            max_responses=Launch.model_fields["max_responses"].default,
        ),
    )


def pricing_state(root, mode="operator", now=None):
    if mode == "recorded":
        return state_view(False, "recorded_only", None)
    path = root / "admin/pricing.json"
    if not path.exists():
        return state_view(False, "administrator_setup_required", None)
    try:
        profile = SavedPricing.model_validate_json(path.read_text(encoding="utf-8")).model_dump(
            mode="json"
        )
        confirmed = datetime.fromisoformat(profile["confirmed_at"])
        expires = datetime.fromisoformat(profile["expires_at"])
        current = now or datetime.now(timezone.utc)
        if (
            confirmed.tzinfo is None
            or expires != confirmed + timedelta(hours=24)
            or confirmed > current
        ):
            raise ValueError("Invalid confirmation time")
        if current >= expires:
            return state_view(False, "administrator_confirmation_expired", profile)
        return state_view(True, "administrator_confirmed", profile)
    except Exception:
        return state_view(False, "administrator_configuration_invalid", None)


def confirm_pricing(root, body, reviewer):
    current = datetime.now(timezone.utc)
    profile = dict(
        rates=body.model_dump(mode="json"),
        confirmed_by=reviewer,
        confirmed_at=current.isoformat(),
        expires_at=(current + timedelta(hours=24)).isoformat(),
        verification_method="local_administrator_attestation",
    )
    directory = root / "admin"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "pricing.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")
    temporary.replace(target)
    return pricing_state(root)


def employee_launch(request, state):
    if not state["ready"]:
        raise StoreError(
            503,
            "An administrator must confirm current model pricing in Advanced Settings before starting a billing review.",
        )
    rates = state["profile"]["rates"]
    return Launch(
        idempotency_key=request.idempotency_key,
        acknowledge_paid=request.acknowledge_paid,
        input_price=rates["input_price"],
        cached_input_price=rates["cached_input_price"],
        output_price=rates["output_price"],
    )
