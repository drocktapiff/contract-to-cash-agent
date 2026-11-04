"""Immutable administrator-attested evidence; no web/model writes or source edits."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Literal
from pydantic import Field
from contract_to_cash.agent.tools import Tools
from contract_to_cash.billing_engine import ConflictError, expected_amount
from .models import Input


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class AuthorityAssertion(Input):
    customer_id: str = Field(min_length=1, max_length=100)
    contract_id: str = Field(min_length=1, max_length=100)
    period: Literal["2026-04"]
    base_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    governing_amendment_id: str = Field(min_length=1, max_length=100)
    superseded_amendment_ids: list[str] = Field(min_length=1, max_length=20)
    issuer: str = Field(min_length=3, max_length=200)
    issuer_authority: str = Field(min_length=10, max_length=1000)
    source_reference: str = Field(min_length=5, max_length=1000)
    confirmation_text: str = Field(min_length=30, max_length=10000)


def validate_assertion(data, assertion):
    a = AuthorityAssertion.model_validate(assertion).model_dump()
    cid = a["customer_id"]
    if a["base_revision"] != data.revision or a["period"] != data.period:
        raise ValueError("Authority record is for a different evidence revision or period")
    contract = data.customers.get(cid)
    if not contract or contract["contract_id"] != a["contract_id"]:
        raise ValueError("Authority record does not match the customer contract")
    changes = data.changes[cid]
    try:
        expected_amount(contract, changes, data.period)
    except ConflictError:
        pass
    else:
        raise ValueError("Only an existing signed set-price conflict can be resolved this way")
    governing = next((r for r in changes if r["amendment_id"] == a["governing_amendment_id"]), None)
    if not governing or governing["status"] != "signed" or governing["kind"] != "set_price":
        raise ValueError("Select a signed governing set-price amendment")
    if governing["effective_date"] > data.period + "-01" or (
        governing.get("end_date") and governing["end_date"] < data.period + "-01"
    ):
        raise ValueError("Selected amendment is not active for the period")
    superseded = set(a["superseded_amendment_ids"])
    expected = {
        r["amendment_id"]
        for r in changes
        if r["status"] == "signed"
        and r["kind"] == "set_price"
        and r["effective_date"] == governing["effective_date"]
        and r["amendment_id"] != governing["amendment_id"]
        and (not r.get("end_date") or r["end_date"] >= data.period + "-01")
    }
    if (
        not expected
        or superseded != expected
        or len(superseded) != len(a["superseded_amendment_ids"])
    ):
        raise ValueError("Authority must identify exactly the competing signed amendments")
    remaining = [r for r in changes if r["amendment_id"] not in superseded]
    if any(
        r["kind"] == "set_price"
        and r["status"] == "signed"
        and governing["effective_date"] < r["effective_date"] <= data.period + "-01"
        and (not r.get("end_date") or r["end_date"] >= data.period + "-01")
        for r in remaining
    ):
        raise ValueError("A later active price contradicts the asserted governing amendment")
    quote = a["confirmation_text"]
    if any(
        reference not in quote
        for reference in [
            cid,
            a["contract_id"],
            data.period,
            a["governing_amendment_id"],
            *superseded,
        ]
    ):
        raise ValueError(
            "Original confirmation must explicitly identify customer, contract, period and governing/competing amendment IDs"
        )
    # Existing engine must independently accept the resulting terms; no guessed amounts.
    expected_amount(contract, remaining, data.period)
    return a


def evidence_directory(root):
    return Path(root) / "admin" / "resolution-evidence"


def registered_evidence(root, data):
    result = []
    for path in sorted(evidence_directory(root).glob("*.json")):
        if path.is_symlink():
            raise ValueError("Symlinked authority evidence is unsupported")
        envelope = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(envelope, dict) or not isinstance(envelope.get("payload"), dict):
            raise ValueError("Malformed authority evidence envelope")
        payload = envelope["payload"]
        if not isinstance(payload.get("assertion"), dict):
            raise ValueError("Malformed authority assertion")
        if (
            envelope.get("evidence_id") != "authority-" + digest(payload)
            or path.stem != envelope["evidence_id"]
        ):
            raise ValueError("Registered authority evidence failed integrity validation")
        if payload.get(
            "verification"
        ) != "administrator_verified_source_and_authority" or not payload.get("verified_by"):
            raise ValueError("Unverified authority evidence")
        original = payload.get("original_document_text", "")
        if (
            not isinstance(original, str)
            or not original
            or hashlib.sha256(original.encode()).hexdigest()
            != payload.get("original_document_sha256")
            or payload["assertion"]["confirmation_text"] not in original
        ):
            raise ValueError("Original supporting document failed integrity validation")
        # Retain older evidence on disk, but never use it for a different source revision.
        AuthorityAssertion.model_validate(payload["assertion"])
        if payload["assertion"]["base_revision"] != data.revision:
            continue
        validate_assertion(data, payload["assertion"])
        result.append(envelope)
    selections = {}
    for item in result:
        a = item["payload"]["assertion"]
        key = (a["customer_id"], a["period"])
        choice = (a["governing_amendment_id"], tuple(sorted(a["superseded_amendment_ids"])))
        if key in selections and selections[key] != choice:
            raise ValueError("Contradictory registered authority; escalate for clarification")
        selections[key] = choice
    return result


def register_evidence(root, data, assertion, verified_by, attested=False, original_document=None):
    if not attested or not verified_by.strip():
        raise ValueError(
            "An administrator must explicitly verify the original source and issuer authority"
        )
    a = validate_assertion(data, assertion)
    if (
        not isinstance(original_document, str)
        or not 30 <= len(original_document) <= 50000
        or a["confirmation_text"] not in original_document
    ):
        raise ValueError(
            "Supply the original UTF-8 supporting document containing the exact confirmation quote"
        )
    for old in registered_evidence(root, data):
        prior = old["payload"]["assertion"]
        if (
            prior["customer_id"] == a["customer_id"]
            and prior["governing_amendment_id"] != a["governing_amendment_id"]
        ):
            raise ValueError(
                "Contradictory authority already registered; do not choose between assertions"
            )
        if prior == a:
            return old
    payload = dict(
        assertion=a,
        original_document_text=original_document,
        original_document_sha256=hashlib.sha256(original_document.encode()).hexdigest(),
        verified_by=verified_by,
        verified_at=datetime.now(timezone.utc).isoformat(),
        verification="administrator_verified_source_and_authority",
        validation_boundary="Local administrator attestation; issuer identity and legal authority are not independently authenticated by Ledgerline",
    )
    eid = "authority-" + digest(payload)
    envelope = dict(evidence_id=eid, payload=payload)
    directory = evidence_directory(root)
    directory.mkdir(parents=True, exist_ok=True)
    # Exclusive creation never overwrites a previously registered record.
    from uuid import uuid4

    temporary = directory / (uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8") as output:
            output.write(json.dumps(envelope, indent=2) + "\n")
        temporary.replace(directory / (eid + ".json"))
    finally:
        temporary.unlink(missing_ok=True)
    return envelope


def select_evidence(root, data, evidence_id, customer_id, governing):
    records = registered_evidence(root, data)
    item = next((r for r in records if r["evidence_id"] == evidence_id), None)
    if not item:
        raise ValueError(
            "Reference an administrator-registered authority record for these current sources"
        )
    a = item["payload"]["assertion"]
    if a["customer_id"] != customer_id or a["governing_amendment_id"] != governing:
        raise ValueError("Your selection contradicts the registered authority record")
    return item


class ContinuationTools(Tools):
    """Scoped originals stay intact; only the calculation view excludes superseded terms."""

    def __init__(self, data, journal):
        self.authority = data.authority
        super().__init__(data, journal)

    def calculation_amendments(self, customer_id):
        self._customer(customer_id)
        superseded = self.authority["payload"]["assertion"]["superseded_amendment_ids"]
        return [a for a in self.data.changes[customer_id] if a["amendment_id"] not in superseded]

    def _required(self, customer_id):
        return super()._required(customer_id) | {self.authority["evidence_id"]}

    def get_customer_evidence(self, customer_ids):
        result = super().get_customer_evidence(customer_ids)
        for case in result["cases"]:
            case["documents"].append(self.get_document(self.authority["evidence_id"]))
        return result

    def refresh(self):
        raise ValueError("Continuation evidence is immutable; create a new validated revision")


def scoped_data(data, intervention, authority):
    import copy

    a = authority["payload"]["assertion"]
    cid = a["customer_id"]
    result = copy.copy(data)
    for name in ("customers", "changes", "rows"):
        setattr(result, name, {cid: copy.deepcopy(getattr(data, name)[cid])})
    result.contracts = [copy.deepcopy(data.customers[cid])]
    result.amendments = copy.deepcopy(data.changes[cid])
    result.invoices = copy.deepcopy(data.rows[cid])
    result.documents = {
        did: copy.deepcopy(doc) for did, doc in data.documents.items() if doc["customer_id"] == cid
    }
    text = json.dumps(authority["payload"], indent=2)
    result.documents[authority["evidence_id"]] = dict(
        document_id=authority["evidence_id"],
        customer_id=cid,
        text=text,
        sha256=hashlib.sha256(text.encode()).hexdigest(),
    )
    result.authority = authority
    result.revision = digest(
        dict(base_revision=data.revision, intervention_id=intervention["id"], authority=authority)
    )
    return result
