"""Professional text PDFs; no hidden extraction payload or embedded expected result."""

from pathlib import Path
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether

BRAND = "Northstar Cloudworks"
TITLES = {
    "contract": ("MASTER SUBSCRIPTION AGREEMENT", "SOFTWARE SERVICES AGREEMENT"),
    "invoice": ("COMMERCIAL INVOICE", "TAX INVOICE"),
    "receipt": ("PAYMENT RECEIPT", "CASH APPLICATION RECORD"),
    "amendment": ("SIGNED PRICING AMENDMENT", "AMENDMENT TO SUBSCRIPTION TERMS"),
    "pricing": ("PRICING SCHEDULE", "SUBSCRIPTION ORDER FORM"),
    "renewal": ("RENEWAL NOTICE", "CONTRACT RENEWAL NOTICE"),
    "credit": ("CREDIT MEMO", "CUSTOMER CREDIT NOTE"),
    "usage": ("USAGE SUMMARY", "METERED SERVICE STATEMENT"),
    "remittance": ("REMITTANCE ADVICE", "PAYMENT ALLOCATION ADVICE"),
    "correspondence": ("ACCOUNT CORRESPONDENCE", "CONTRACT ADMINISTRATION LETTER"),
}
ALIASES = {
    "Document ID": "Document reference",
    "Customer account": "Account reference",
    "Contract reference": "Agreement identifier",
    "Subscription amount": "Subscription fee",
    "Invoice total": "Amount due",
    "Payment amount": "Amount received",
}


def render_pdf(path: Path, kind: str, fields: dict, variant=0, clauses=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="Brand",
            fontName="Helvetica-Bold",
            fontSize=22,
            textColor=colors.HexColor("#173d50"),
            spaceAfter=8,
        )
    )
    styles.add(
        ParagraphStyle(
            name="Title2",
            fontName="Helvetica-Bold",
            fontSize=15,
            textColor=colors.HexColor("#236558"),
            spaceBefore=12,
            spaceAfter=16,
        )
    )
    styles.add(
        ParagraphStyle(name="Business", fontName="Helvetica", fontSize=9, leading=13, spaceAfter=5)
    )
    styles.add(
        ParagraphStyle(
            name="Fine",
            fontName="Helvetica",
            fontSize=7,
            leading=10,
            textColor=colors.HexColor("#647674"),
        )
    )
    story = [
        Paragraph(BRAND, styles["Brand"]),
        Paragraph("Revenue Operations | Enterprise platform services", styles["Fine"]),
        Paragraph("FICTIONAL / DEMO DATA", styles["Fine"]),
        Paragraph(TITLES[kind][variant % 2], styles["Title2"]),
    ]
    for label, value in fields.items():
        label = ALIASES.get(label, label) if variant % 2 else label
        story.append(Paragraph(f"<b>{escape(label)}:</b> {escape(str(value))}", styles["Business"]))
    if kind == "invoice":
        currency = fields.get("Currency", "CAD")
        rows = [
            ["Service description", "Quantity", "Amount"],
            [
                fields.get("Service description", "Enterprise subscription"),
                str(fields.get("Quantity", "1")),
                f"{currency} {fields.get('Service subtotal','0.00')}",
            ],
            [
                "Implementation / onboarding",
                "1",
                f"{currency} {fields.get('Implementation charge','0.00')}",
            ],
            ["Tax", "", f"{currency} {fields.get('Tax amount','0.00')}"],
            ["TOTAL DUE", "", f"{currency} {fields.get('Invoice total','0.00')}"],
        ]
        table = Table(rows, colWidths=[3.85 * inch, 0.65 * inch, 1.4 * inch])
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e7f2ee")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#214d48")),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
                    ("TOPPADDING", (0, 0), (-1, -1), 9),
                    ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#cddbd6")),
                    ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                ]
            )
        )
        story.extend([Spacer(1, 12), table, Spacer(1, 12)])
    if kind in ("receipt", "remittance"):
        story.extend(
            [
                Spacer(1, 10),
                Paragraph("Cash application record", styles["Heading3"]),
                Paragraph(
                    "This receipt documents a fictional customer remittance and its stated allocation. It does not establish that funds moved through any real bank account. No bank routing details are provided.",
                    styles["Business"],
                ),
            ]
        )
    for title, text in clauses or []:
        story.append(Paragraph(escape(title), styles["Heading3"]))
        story.append(Paragraph(escape(text), styles["Business"]))
    story.extend(
        [
            Spacer(1, 12),
            Paragraph(
                "All organizations, contacts, signatures and account references in this document are synthetic. Do not submit this document for payment, legal reliance or financial authorization.",
                styles["Fine"],
            ),
        ]
    )

    def footer(canvas, doc):
        canvas.setStrokeColor(colors.HexColor("#d3ded9"))
        canvas.line(48, 46, 564, 46)
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#657b75"))
        canvas.drawString(48, 34, "NORTHSTAR CLOUDWORKS | FICTIONAL / DEMO DATA")
        canvas.drawRightString(
            564, 34, f"{fields.get('Document ID','Synthetic record')} | Page {doc.page}"
        )

    SimpleDocTemplate(
        str(path),
        pagesize=(612, 792),
        rightMargin=48,
        leftMargin=48,
        topMargin=45,
        bottomMargin=60,
        title=f"{BRAND} - {TITLES[kind][variant%2]}",
        author="Synthetic document generator",
        invariant=1,
    ).build(story, onFirstPage=footer, onLaterPages=footer)
