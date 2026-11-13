"""Reusable lease-agreement PDF generation.

Shared by the landlord view (``tenants:lease_download_pdf``) and the tenant
portal (``portal:lease_pdf``) so a tenant always has a copy of their agreement
to download — even when no signed document was uploaded against the lease.

The document reproduces the standard Swahili "Mkataba wa Upangaji
Chumba/Nyumba" form used by landlords in Tanzania. Only the blanks (dates,
term, monthly rent, landlord contacts) are filled from the lease record; the
fourteen ``Masharti`` (terms) are printed as on the printed form.
"""
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


def lease_pdf_filename(lease) -> str:
    """Return a safe, human-readable filename for ``lease``'s PDF."""
    name = (lease.tenant.full_name or "tenant").replace(" ", "_")
    return f"lease_{lease.pk}_{name}.pdf"


def _owner_profile(lease):
    """Return the property owner's profile, or ``None`` when not set up."""
    owner = lease.unit.block.property.owner
    # Reverse one-to-one raises AttributeError when missing, so getattr's
    # default covers owners that have no OwnerProfile yet.
    return getattr(owner, "owner_profile", None)


def _header_lines(lease) -> list[str]:
    """Build the address / phone / bank lines printed under the title."""
    property_ = lease.unit.block.property
    location = (property_.location or property_.name or "").strip().upper()
    profile = _owner_profile(lease)

    lines = []
    if location:
        lines.append(location)
    if profile and profile.phone:
        lines.append(f"SIMU-{profile.phone}")
    if profile and profile.bank_name and profile.bank_account_number:
        lines.append(
            f"A/NO-{profile.bank_name.strip().upper()} "
            f"{profile.bank_account_number.strip()}"
        )
    return lines


def _money(value) -> str:
    """Format a rent amount with thousands separators (no trailing ``.00``)."""
    amount = float(value)
    if amount == int(amount):
        return f"{amount:,.0f}"
    return f"{amount:,.2f}"


def _clauses(lease) -> list[str]:
    """The fourteen ``Masharti`` with the lease-specific blanks filled in."""
    start = lease.start_date.strftime("%d/%m/%Y")
    end = lease.end_date.strftime("%d/%m/%Y")
    rent = _money(lease.monthly_rent)
    currency = lease.unit.effective_currency

    return [
        f"Mkataba huu utaanza tarehe {start} hadi tarehe {end} na utadumu "
        f"kwa kipindi cha miezi {lease.duration_months}.",
        f"Kodi ya kila mwezi ni shilingi {rent}/= ({currency}).",
        "Mpangaji haruhusiwi kumpangisha mtu yeyote bila idhini ya mwenye "
        "nyumba.",
        "Mpangaji anao wajibu wa kuhakikisha sehemu aliyo pangisha, na "
        "kuhakikisha kwamba kila wakati sehemu hiyo iko katika hali nzuri "
        "ya upangaji aliyo ikuta.",
        "Mpangaji atatumia sehemu aliyo pangisha kwa makazi tuu, na si kwa "
        "biashara wala shughuli nyingine.",
        "Mpangaji ana wajibu wa kutowabugudhi wapangaji wenzake au majirani "
        "zake.",
        "Mpangaji atawajibika kulipa gharama za maji atakayo tumia, pia "
        "kulipa huduma ya utondooji taka kama sheria ya mtaa inavyo elekeza.",
        "Mwenye nyumba atakuwa huru kuwatembelea sehemu aliyo pangishwa kwa "
        "ajili ya ukaguzi, na pia baada ya kumtaarifu mpangaji saa zilizo "
        "kubalika.",
        "Iwapo watakua na nia ya kuendeleza uhusiano wa upangaji kati ya "
        "mwenye nyumba na mpangaji basi mkataba mpya utafanyika baina yao, "
        "vinginevyo mpangaji atawajibika kumkabidhi sehemu aliyopangishwa "
        "mara tuu baada ya mkataba huu, itakua mwisho wa upangaji wake.",
        "Iwapo mpangaji atavunja masharti ya mkataba huu, itakuwa mwisho wa "
        "upangaji wake.",
        "Iwapo mpangaji atataka kuhamia basi itamlazimu atoe taarifa ya "
        "mwezi mmoja kabla ya kuhamia.",
        "Mpangaji haruhusiwi kwa namna yoyote ile kugongelea misumari "
        "ukutani.",
        "Iwapo mpangaji atatishia mkataba ni sharti aache mazingira salama "
        "na iwapo kuna uharibifu wowote umefanyika ndani ya kipindi cha "
        "mkataba atalazimika kugharamia matengenezo ya vitu alivyo haribu.",
        "Ukisha soma na kuelewa yote niliyo andika hapo juu tia sahihi yako "
        "hapa chini.",
    ]


def _styles():
    """Build the paragraph styles used throughout the document."""
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "Title2", parent=base["Title"], fontName="Helvetica-Bold",
            fontSize=13.5, leading=17, spaceAfter=2 * mm,
            alignment=TA_CENTER, textColor=colors.black,
        ),
        "header": ParagraphStyle(
            "HeaderLine", parent=base["Normal"], fontName="Helvetica-Bold",
            fontSize=10.5, leading=13.5, alignment=TA_CENTER,
            textColor=colors.black,
        ),
        "tenant": ParagraphStyle(
            "TenantLine", parent=base["Normal"], fontName="Times-Italic",
            fontSize=10, leading=13, alignment=TA_CENTER,
            textColor=colors.HexColor("#333333"), spaceBefore=3 * mm,
        ),
        "heading": ParagraphStyle(
            "Heading2", parent=base["Heading2"], fontName="Times-Bold",
            fontSize=12.5, leading=16, spaceBefore=6 * mm,
            spaceAfter=5 * mm, textColor=colors.black,
        ),
        "clause": ParagraphStyle(
            "Clause", parent=base["Normal"], fontName="Times-Roman",
            fontSize=11, leading=15.5, alignment=TA_JUSTIFY,
            leftIndent=9 * mm, firstLineIndent=-9 * mm,
            spaceAfter=2.4 * mm,
        ),
        "signature": ParagraphStyle(
            "Signature", parent=base["Normal"], fontName="Times-Roman",
            fontSize=10.5, leading=14,
        ),
        "base": base,
    }


def build_lease_pdf(lease) -> bytes:
    """Render ``lease`` as a Swahili tenancy agreement and return the bytes."""
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
        leftMargin=22 * mm,
        rightMargin=22 * mm,
        title=f"Mkataba wa Upangaji - {lease.tenant.full_name}",
    )

    s = _styles()
    elements = []

    # --- Title block ---
    elements.append(Paragraph("MKATABA WA UPANGAJI CHUMBA/NYUMBA", s["title"]))
    for line in _header_lines(lease):
        elements.append(Paragraph(line, s["header"]))

    # The printed form leaves tenant/unit to be written in by hand; the
    # generated copy states them so the document identifies itself.
    elements.append(Paragraph(
        f"Mpangaji: {lease.tenant.full_name} &nbsp;|&nbsp; "
        f"Chumba/Unit Na.: {lease.unit.unit_number}",
        s["tenant"],
    ))

    # --- Terms ---
    elements.append(Paragraph("<u>MASHARTI YA MKATABA</u>", s["heading"]))
    for number, clause in enumerate(_clauses(lease), start=1):
        elements.append(Paragraph(f"{number}. {clause}", s["clause"]))

    # --- Signatures ---
    elements.append(Spacer(1, 8 * mm))
    sig_data = [[
        "SAINI YA MWENYENYUMBA ______________________",
        "SAINI YA MPANGAJI ______________________",
    ]]
    sig_table = Table(sig_data, colWidths=[83 * mm, 83 * mm])
    sig_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Times-Roman"),
        ("FONTSIZE", (0, 0), (-1, -1), 10.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    elements.append(sig_table)
    elements.append(Spacer(1, 6 * mm))
    elements.append(Paragraph("TAREHE- ______________________", s["signature"]))

    doc.build(elements)
    pdf = buf.getvalue()
    buf.close()
    return pdf
