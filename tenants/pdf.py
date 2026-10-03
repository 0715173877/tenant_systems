"""Reusable lease-agreement PDF generation.

Shared by the landlord view (``tenants:lease_download_pdf``) and the tenant
portal (``portal:lease_pdf``) so a tenant always has a copy of their agreement
to download — even when no signed document was uploaded against the lease.
"""
from datetime import date
from io import BytesIO

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .models import Lease


def lease_pdf_filename(lease) -> str:
    """Return a safe, human-readable filename for ``lease``'s PDF."""
    name = (lease.tenant.full_name or "tenant").replace(" ", "_")
    return f"lease_{lease.pk}_{name}.pdf"


def _styles():
    """Build the paragraph styles used throughout the document."""
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "Title2", parent=base["Title"], fontSize=18, spaceAfter=6 * mm,
            alignment=TA_CENTER, textColor=colors.HexColor("#1a1a2e"),
        ),
        "subtitle": ParagraphStyle(
            "Subtitle", parent=base["Normal"], fontSize=10, alignment=TA_CENTER,
            textColor=colors.HexColor("#666666"), spaceAfter=10 * mm,
        ),
        "heading": ParagraphStyle(
            "Heading2", parent=base["Heading2"], fontSize=13, spaceAfter=4 * mm,
            spaceBefore=6 * mm, textColor=colors.HexColor("#1a1a2e"),
        ),
        "normal": ParagraphStyle(
            "Normal2", parent=base["Normal"], fontSize=10, leading=14,
            spaceAfter=2 * mm,
        ),
        "base": base,
    }


def _table_style():
    """Shared styling for the label/value tables in the document."""
    return TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dddddd")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f5f5f5")),
    ])


_TERMS_TEXT = """
This Lease Agreement (the "Agreement") is entered into between the Landlord and the Tenant identified above.<br/><br/>
<b>Payment:</b> The Tenant agrees to pay the monthly rent as specified above on or before the 5th day of each month.<br/><br/>
<b>Deposit:</b> The deposit shall be held as security against damages or breach of terms and shall be refunded upon
vacating, subject to deductions for any outstanding dues or damages.<br/><br/>
<b>Use:</b> The leased premises shall be used exclusively as a private residence by the Tenant and their immediate
family members. Subletting is prohibited without the Landlord's written consent.<br/><br/>
<b>Maintenance:</b> The Tenant shall maintain the premises in good condition and shall promptly report any damages
or needed repairs to the Landlord.<br/><br/>
<b>Termination:</b> Either party may terminate this Agreement by giving written notice as required by law. Upon
termination, the Tenant shall vacate the premises and return all keys.<br/><br/>
<b>Governing Law:</b> This Agreement shall be governed by and construed in accordance with the laws of the
applicable jurisdiction.
"""


def build_lease_pdf(lease) -> bytes:
    """Render ``lease`` to a PDF and return the raw bytes."""
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
    )

    s = _styles()
    title_style, subtitle_style = s["title"], s["subtitle"]
    heading_style, normal_style = s["heading"], s["normal"]

    elements = []

    # --- Title ---
    elements.append(Paragraph("LEASE AGREEMENT", title_style))
    elements.append(Paragraph(
        f"Prepared on {date.today().strftime('%B %d, %Y')}",
        subtitle_style,
    ))
    elements.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#cccccc")))
    elements.append(Spacer(1, 4 * mm))

    # --- Party Details ---
    elements.append(Paragraph("1. PARTIES TO THE AGREEMENT", heading_style))
    parties_data = [
        ["Landlord / Property", lease.unit.block.property.name if lease.unit.block and lease.unit.block.property else "N/A"],
        ["Property Address", str(lease.unit.block) if lease.unit.block else "N/A"],
        ["Unit Number", lease.unit.unit_number],
        ["Tenant", lease.tenant.full_name],
        ["Tenant Phone", lease.tenant.phone_number],
        ["Tenant Email", lease.tenant.email or "—"],
    ]
    parties_table = Table(parties_data, colWidths=[50 * mm, 110 * mm])
    parties_table.setStyle(_table_style())
    elements.append(parties_table)
    elements.append(Spacer(1, 4 * mm))

    # --- Lease Terms ---
    elements.append(Paragraph("2. LEASE TERMS", heading_style))
    status_text = dict(Lease.STATUS_CHOICES).get(lease.status, lease.status)
    terms_data = [
        ["Lease Period", f"{lease.start_date.strftime('%B %d, %Y')} to {lease.end_date.strftime('%B %d, %Y')}"],
        ["Monthly Rent", f"${lease.monthly_rent:,.2f}"],
        ["Deposit Paid", "Yes" if lease.deposit_paid else "No"],
    ]
    if lease.deposit_amount:
        terms_data.append(["Deposit Amount", f"${lease.deposit_amount:,.2f}"])
    terms_data.append(["Status", status_text])

    terms_table = Table(terms_data, colWidths=[50 * mm, 110 * mm])
    terms_table.setStyle(_table_style())
    elements.append(terms_table)
    elements.append(Spacer(1, 4 * mm))

    # --- Terms & Conditions ---
    elements.append(Paragraph("3. TERMS AND CONDITIONS", heading_style))
    elements.append(Paragraph(_TERMS_TEXT, normal_style))
    elements.append(Spacer(1, 6 * mm))

    # --- Signatures ---
    elements.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#cccccc")))
    elements.append(Spacer(1, 6 * mm))
    elements.append(Paragraph("4. SIGNATURES", heading_style))

    sig_data = [
        ["", ""],
        ["", ""],
        ["", ""],
        ["", ""],
        ["Landlord Signature: ___________________", "Tenant Signature: ___________________"],
        ["", ""],
        [f"Date: {date.today().strftime('%B %d, %Y')}", f"Date: {date.today().strftime('%B %d, %Y')}"],
    ]
    sig_table = Table(sig_data, colWidths=[85 * mm, 85 * mm])
    sig_table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.append(sig_table)

    # --- Footer ---
    elements.append(Spacer(1, 10 * mm))
    elements.append(Paragraph(
        f"Generated by Tenant Systems &mdash; {timezone.localtime().strftime('%Y-%m-%d %H:%M')}",
        ParagraphStyle("Footer", parent=s["base"]["Normal"], fontSize=8,
                       textColor=colors.HexColor("#999999"), alignment=TA_CENTER),
    ))

    doc.build(elements)
    pdf = buf.getvalue()
    buf.close()
    return pdf
