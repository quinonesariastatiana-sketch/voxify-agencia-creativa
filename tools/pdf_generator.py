"""Generate branded PDF quotes using reportlab."""

import io
import os
import logging
from datetime import date

logger = logging.getLogger(__name__)


def generate_quote(brand: dict, lead: dict, items: list, notes: str = "") -> bytes:
    """
    Generate a branded PDF quote.
    items: [{"name": str, "description": str, "price": float, "qty": int}]
    Returns PDF bytes.
    """
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                         Table, TableStyle, HRFlowable)
        from reportlab.lib.enums import TA_RIGHT, TA_CENTER, TA_LEFT
    except ImportError:
        logger.warning("[pdf] reportlab no instalado — instala con: pip install reportlab")
        return _fallback_pdf(brand, lead, items, notes)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter,
                            leftMargin=0.75*inch, rightMargin=0.75*inch,
                            topMargin=0.75*inch, bottomMargin=0.75*inch)

    # Colors from brand or Voxify defaults
    primary_hex = (brand.get("color") or "#635BFF").lstrip("#")
    r_val = int(primary_hex[0:2], 16) / 255
    g_val = int(primary_hex[2:4], 16) / 255
    b_val = int(primary_hex[4:6], 16) / 255
    primary = colors.Color(r_val, g_val, b_val)
    navy = colors.Color(0.039, 0.145, 0.251)  # #0A2540

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("H1", fontSize=22, textColor=navy, spaceAfter=4, fontName="Helvetica-Bold")
    h2 = ParagraphStyle("H2", fontSize=13, textColor=primary, spaceAfter=2, fontName="Helvetica-Bold")
    body = ParagraphStyle("Body", fontSize=10, textColor=colors.HexColor("#333333"), leading=14)
    small = ParagraphStyle("Small", fontSize=8, textColor=colors.grey, leading=11)
    right = ParagraphStyle("Right", fontSize=10, alignment=TA_RIGHT)

    story = []

    # Header
    story.append(Paragraph(brand.get("name", "Voxify"), h1))
    story.append(Paragraph(brand.get("tagline", ""), ParagraphStyle("Tag", fontSize=11, textColor=colors.grey)))
    story.append(Spacer(1, 8))
    story.append(HRFlowable(width="100%", thickness=2, color=primary))
    story.append(Spacer(1, 12))

    # Quote meta
    quote_num = f"COT-{date.today().strftime('%Y%m%d')}-{lead.get('id', '001')}"
    meta_data = [
        ["COTIZACIÓN", quote_num],
        ["FECHA", date.today().strftime("%d/%m/%Y")],
        ["VÁLIDA HASTA", date.today().replace(day=min(date.today().day+30, 28)).strftime("%d/%m/%Y")],
    ]
    meta_table = Table(meta_data, colWidths=[1.5*inch, 2.5*inch])
    meta_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (0, -1), navy),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))

    # Lead info
    lead_data = [
        ["PARA", lead.get("name", "")],
        ["EMPRESA", lead.get("company", "")],
        ["EMAIL", lead.get("email", "")],
        ["TELÉFONO", lead.get("phone", "")],
    ]
    lead_table = Table(lead_data, colWidths=[1.5*inch, 2.5*inch])
    lead_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (0, -1), navy),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))

    side_by_side = Table([[meta_table, lead_table]], colWidths=[4*inch, 4*inch])
    side_by_side.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(side_by_side)
    story.append(Spacer(1, 20))

    # Items table
    story.append(Paragraph("DETALLE DE SERVICIOS / PRODUCTOS", h2))
    story.append(Spacer(1, 6))

    headers = ["DESCRIPCIÓN", "CANT.", "PRECIO UNIT.", "TOTAL"]
    rows = [headers]
    subtotal = 0.0
    for item in items:
        qty = int(item.get("qty", 1))
        price = float(item.get("price", 0))
        total = qty * price
        subtotal += total
        rows.append([
            f"{item.get('name','')}\n{item.get('description','')}",
            str(qty),
            f"${price:,.2f}",
            f"${total:,.2f}",
        ])

    tax = subtotal * 0.0  # No tax by default; configurable
    grand_total = subtotal + tax
    rows.append(["", "", "SUBTOTAL", f"${subtotal:,.2f}"])
    rows.append(["", "", "TOTAL", f"${grand_total:,.2f}"])

    col_widths = [4.5*inch, 0.6*inch, 1.2*inch, 1.2*inch]
    items_table = Table(rows, colWidths=col_widths, repeatRows=1)
    items_table.setStyle(TableStyle([
        # Header row
        ("BACKGROUND", (0, 0), (-1, 0), primary),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("TOPPADDING", (0, 0), (-1, 0), 8),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
        # Body rows
        ("FONTSIZE", (0, 1), (-1, -3), 9),
        ("ROWBACKGROUNDS", (0, 1), (-1, -3), [colors.white, colors.Color(0.97, 0.97, 1)]),
        ("TOPPADDING", (0, 1), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 6),
        ("GRID", (0, 0), (-1, -3), 0.5, colors.Color(0.88, 0.88, 0.92)),
        # Total rows
        ("FONTNAME", (2, -2), (-1, -1), "Helvetica-Bold"),
        ("TEXTCOLOR", (2, -1), (-1, -1), primary),
        ("FONTSIZE", (2, -1), (-1, -1), 11),
        ("LINEABOVE", (2, -2), (-1, -2), 1, colors.grey),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
    ]))
    story.append(items_table)
    story.append(Spacer(1, 20))

    # Notes
    if notes:
        story.append(Paragraph("NOTAS", h2))
        story.append(Paragraph(notes, body))
        story.append(Spacer(1, 12))

    # Footer
    story.append(HRFlowable(width="100%", thickness=1, color=colors.Color(0.88, 0.88, 0.92)))
    story.append(Spacer(1, 6))
    footer_text = (
        f"{brand.get('name','')} · {brand.get('website','voxify.ai')} · "
        f"Esta cotización es válida por 30 días."
    )
    story.append(Paragraph(footer_text, small))

    doc.build(story)
    return buf.getvalue()


def _fallback_pdf(brand: dict, lead: dict, items: list, notes: str) -> bytes:
    """Plain text fallback if reportlab is not installed."""
    lines = [
        f"COTIZACIÓN — {brand.get('name', 'Voxify')}",
        f"Para: {lead.get('name', '')} / {lead.get('company', '')}",
        f"Fecha: {date.today().isoformat()}",
        "",
        "ITEMS:",
    ]
    total = 0.0
    for item in items:
        qty = int(item.get("qty", 1))
        price = float(item.get("price", 0))
        subtotal = qty * price
        total += subtotal
        lines.append(f"  {item.get('name', '')} x{qty} = ${subtotal:,.2f}")
    lines += ["", f"TOTAL: ${total:,.2f}", "", notes or ""]
    content = "\n".join(lines).encode("utf-8")
    return content


def save_quote(brand: dict, lead: dict, items: list, notes: str = "") -> str:
    """Save PDF to static/uploads and return local URL."""
    from pathlib import Path
    pdf_bytes = generate_quote(brand, lead, items, notes)
    lead_id = lead.get("id", "0")
    brand_id = brand.get("id", "voxify")
    filename = f"quote_{brand_id}_{lead_id}_{date.today().strftime('%Y%m%d')}.pdf"
    dest = Path(__file__).resolve().parent.parent / "static" / "uploads" / "quotes"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / filename).write_bytes(pdf_bytes)
    return f"/static/uploads/quotes/{filename}"
