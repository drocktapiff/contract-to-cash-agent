"""Bounded, text-only PDF intake. No generator, ledger or oracle dependencies."""

from dataclasses import asdict
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
from io import BytesIO
from pathlib import Path
import re
from pypdf import PdfReader
from .models import Document, Evidence

HEADINGS = {
    "MASTER SUBSCRIPTION AGREEMENT": "contract",
    "SOFTWARE SERVICES AGREEMENT": "contract",
    "COMMERCIAL INVOICE": "invoice",
    "TAX INVOICE": "invoice",
    "PAYMENT RECEIPT": "receipt",
    "CASH APPLICATION RECORD": "receipt",
    "SIGNED PRICING AMENDMENT": "amendment",
    "AMENDMENT TO SUBSCRIPTION TERMS": "amendment",
    "PRICING SCHEDULE": "pricing",
    "SUBSCRIPTION ORDER FORM": "pricing",
    "RENEWAL NOTICE": "renewal",
    "CONTRACT RENEWAL NOTICE": "renewal",
    "CREDIT MEMO": "credit",
    "CUSTOMER CREDIT NOTE": "credit",
    "USAGE SUMMARY": "usage",
    "METERED SERVICE STATEMENT": "usage",
    "REMITTANCE ADVICE": "remittance",
    "PAYMENT ALLOCATION ADVICE": "remittance",
    "ACCOUNT CORRESPONDENCE": "correspondence",
    "CONTRACT ADMINISTRATION LETTER": "correspondence",
}
ALIASES = {
    "Document reference": "Document ID",
    "Account reference": "Customer account",
    "Agreement identifier": "Contract reference",
    "Subscription fee": "Subscription amount",
    "Amount due": "Invoice total",
    "Amount received": "Payment amount",
}
NUMERIC = set(
    "Subscription amount|Included quantity|Unit rate|Discount percent|Implementation fee|Tax rate|Quantity|Service subtotal|Implementation charge|Tax amount|Invoice total|Payment amount|Allocated amount|Credit amount".split(
        "|"
    )
)
DATES = set(
    "Effective date|Term end|Discount valid through|Invoice date|Due date|Period start|Period end|Receipt date|Notice date".split(
        "|"
    )
)
REQUIRED = {
    "contract": [
        "Contract status",
        "Effective date",
        "Term end",
        "Billing cadence",
        "Subscription amount",
        "Currency",
        "Discount percent",
        "Discount valid through",
        "Implementation fee",
        "Tax rate",
        "Unit rate",
        "Included quantity",
    ],
    "invoice": [
        "Invoice reference",
        "Invoice date",
        "Due date",
        "Period start",
        "Period end",
        "Quantity",
        "Service subtotal",
        "Implementation charge",
        "Tax rate",
        "Tax amount",
        "Invoice total",
        "Currency",
    ],
    "receipt": [
        "Receipt date",
        "Payment reference",
        "Payment amount",
        "Applied invoice",
        "Allocated amount",
        "Currency",
    ],
    "amendment": [
        "Contract status",
        "Effective date",
        "Subscription amount",
        "Currency",
        "Supersedes",
    ],
    "pricing": [
        "Contract status",
        "Effective date",
        "Billing cadence",
        "Subscription amount",
        "Currency",
    ],
    "usage": ["Period start", "Period end", "Quantity", "Currency"],
    "credit": ["Applied invoice", "Credit amount", "Credit status", "Currency"],
    "remittance": [
        "Receipt reference",
        "Applied invoice",
        "Payment amount",
        "Payment reference",
        "Allocated amount",
        "Currency",
    ],
    "renewal": ["Notice date", "Term end", "Renewal status"],
    "correspondence": ["Required action"],
}
MAX_BYTES = 5 * 1024 * 1024
MAX_PAGES = 20
MAX_TEXT = 200_000


def parse_pdf(path: Path) -> Document:
    """Every rejection remains a document result and produces review work."""
    if path.is_symlink():
        raise ValueError("Symbolic links are not accepted")
    size = path.stat().st_size
    raw = b""
    errors = []
    pages = []
    fields = {}
    evidence = {}
    kind = None
    if size > MAX_BYTES:
        # Stream the hash without loading an oversized document into memory.
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(65536), b""):
                digest.update(chunk)
        file_hash = digest.hexdigest()
        errors.append("PDF exceeds 5 MiB intake limit")
    else:
        raw = path.read_bytes()
        file_hash = hashlib.sha256(raw).hexdigest()
        try:
            if not raw.startswith(b"%PDF-"):
                raise ValueError("Missing PDF signature")
            with BytesIO(raw) as stream:
                reader = PdfReader(stream, strict=True)
                if reader.is_encrypted:
                    raise ValueError("Encrypted PDF requires review")
                if len(reader.pages) > MAX_PAGES:
                    raise ValueError("PDF exceeds 20 page limit")
                for page in reader.pages:
                    value = page.extract_text() or ""
                    if sum(map(len, pages)) + len(value) > MAX_TEXT:
                        raise ValueError("Extracted text limit exceeded")
                    pages.append(value)
        except Exception as exc:
            # Deliberately no exception/request payload in persisted diagnostics.
            errors.append("PDF extraction failed: " + type(exc).__name__)
            pages = []
    titles = {
        HEADINGS[line.strip()]
        for text in pages
        for line in text.splitlines()
        if line.strip() in HEADINGS
    }
    if len(titles) == 1:
        kind = titles.pop()
    else:
        errors.append("Unsupported or ambiguous document heading")
    for page_number, text in enumerate(pages, 1):
        for match in re.finditer(r"^([^\n:]{1,70}):\s*([^\n]+)", text, re.M):
            label = ALIASES.get(match[1].strip(), match[1].strip())
            value = match[2].strip()
            if label in fields and fields[label] != value:
                errors.append("Conflicting repeated field: " + label)
            else:
                fields[label] = value
            evidence.setdefault(label, []).append(
                asdict(
                    Evidence(
                        "",
                        file_hash,
                        page_number,
                        match.start(),
                        match.end(),
                        match.group(),
                        source_record_reference=label,
                    )
                )
            )
    for label in ["Document ID", "Customer account", "Contract reference"] + REQUIRED.get(kind, []):
        if not fields.get(label):
            errors.append("Missing field: " + label)
    for label, value in fields.items():
        if label in NUMERIC:
            try:
                n = Decimal(value)
                if not n.is_finite() or not 0 <= n <= Decimal("1000000000000"):
                    raise ValueError()
                if label == "Tax rate" and n > 1:
                    raise ValueError()
                if label == "Discount percent" and n > 100:
                    raise ValueError()
            except (InvalidOperation, ValueError):
                errors.append("Invalid numeric field: " + label)
        if label in DATES:
            try:
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                    raise ValueError()
                date.fromisoformat(value)
            except ValueError:
                errors.append("Invalid calendar field: " + label)
    did = fields.get("Document ID", "unparsed-" + file_hash[:20])
    for spans in evidence.values():
        for span in spans:
            span["document_id"] = did
    result = Document(
        did,
        file_hash,
        path.name,
        kind,
        fields.get("Customer account"),
        fields.get("Contract reference"),
        fields,
        evidence,
        pages,
        errors,
    )
    result.provenance["synthetic"] = any("FICTIONAL / DEMO DATA" in text for text in pages)
    return result


def read_directory(directory):
    root = Path(directory).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Input must be a controlled PDF directory")
    files = sorted(root.iterdir())
    if len(files) > 500:
        raise ValueError("Intake limit is 500 directory entries")
    docs = []
    for path in files:
        if path.is_symlink():
            raise ValueError("Symbolic links are not accepted")
        if path.is_file() and path.suffix.lower() == ".pdf":
            docs.append(parse_pdf(path))
    return docs
