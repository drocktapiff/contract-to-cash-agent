"""Export public API model schemas without reading credentials, runs, or fixtures."""

import argparse
import json
from pathlib import Path
from contract_to_cash.web.models import (
    DatasetView,
    EventView,
    Health,
    Launch,
    Login,
    ReviewAction,
    RunView,
)

from contract_to_cash.web.pricing import BillingReviewRequest, PricingConfirmation, PricingState


def public_schema():
    return {
        model.__name__: model.model_json_schema()
        for model in (
            DatasetView,
            EventView,
            Health,
            Launch,
            Login,
            ReviewAction,
            RunView,
            BillingReviewRequest,
            PricingConfirmation,
            PricingState,
        )
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    path = Path(__file__).resolve().parents[1] / "frontend/src/api-schema.json"
    content = json.dumps(public_schema(), indent=2, sort_keys=True) + "\n"
    if args.check:
        if not path.exists() or json.loads(path.read_text(encoding="utf-8")) != json.loads(content):
            parser.exit(
                1,
                "Public API schema changed. Regenerate it and review frontend types/mapping tests.\n",
            )
        print("Public API schema snapshot matches Python models.")
    else:
        path.write_text(content, encoding="utf-8")
