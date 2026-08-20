import os
from datetime import datetime
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.config import settings


def generate_route_brief_pdf(
    brief_id: str,
    origin: str,
    destination: str,
    carrier: str | None,
    cargo_type: str,
    recommendation: str | None,
    risk_level: str | None,
    brief_markdown: str | None,
    output_dir: str | None = None,
) -> str:
    target_dir = output_dir or settings.BRIEF_STORAGE_PATH
    os.makedirs(target_dir, exist_ok=True)
    pdf_filename = f"brief_{brief_id}.pdf"
    pdf_path = os.path.join(target_dir, pdf_filename)

    doc = SimpleDocTemplate(
        pdf_path,
        pagesize=letter,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36,
    )
    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        "TitleStyle",
        parent=styles["Heading1"],
        fontSize=20,
        leading=24,
        textColor=colors.HexColor("#0f172a"),
        spaceAfter=12,
    )
    meta_style = ParagraphStyle(
        "MetaStyle",
        parent=styles["Normal"],
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#334155"),
    )
    body_style = ParagraphStyle(
        "BodyStyle",
        parent=styles["Normal"],
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#1e293b"),
        spaceAfter=8,
    )

    story = []

    # Title
    story.append(Paragraph(f"Route Intelligence Brief: {origin} → {destination}", title_style))
    story.append(Spacer(1, 10))

    # Meta Table
    meta_data = [
        [
            Paragraph(f"<b>Origin:</b> {origin}", meta_style),
            Paragraph(f"<b>Destination:</b> {destination}", meta_style),
        ],
        [
            Paragraph(f"<b>Carrier:</b> {carrier or 'All'}", meta_style),
            Paragraph(f"<b>Cargo Type:</b> {cargo_type}", meta_style),
        ],
        [
            Paragraph(f"<b>Recommendation:</b> {(recommendation or 'N/A').upper()}", meta_style),
            Paragraph(f"<b>Risk Level:</b> {(risk_level or 'N/A').upper()}", meta_style),
        ],
        [
            Paragraph(f"<b>Generated:</b> {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}", meta_style),
            Paragraph(f"<b>Brief ID:</b> {brief_id}", meta_style),
        ],
    ]

    table = Table(meta_data, colWidths=[270, 270])
    table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
            ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#cbd5e1")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ])
    )
    story.append(table)
    story.append(Spacer(1, 16))

    # Brief Markdown Content
    if brief_markdown:
        lines = brief_markdown.split("\n")
        for line in lines:
            if line.startswith("# "):
                story.append(Paragraph(line[2:], styles["Heading1"]))
                story.append(Spacer(1, 6))
            elif line.startswith("## "):
                story.append(Paragraph(line[3:], styles["Heading2"]))
                story.append(Spacer(1, 4))
            elif line.startswith("### "):
                story.append(Paragraph(line[4:], styles["Heading3"]))
                story.append(Spacer(1, 4))
            elif line.strip():
                # Replace special chars for reportlab XML-like parser
                clean_line = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                story.append(Paragraph(clean_line, body_style))
            else:
                story.append(Spacer(1, 4))

    doc.build(story)
    return pdf_path
