import os
from pathlib import Path
from typing import Optional
from fpdf import FPDF
import markdown

from app.config import settings

STORAGE_DIR = Path("storage/route_briefs")


def _sanitize_unicode_for_pdf(text: str) -> str:
    """Replace unsupported unicode characters with ASCII equivalents for standard PDF fonts."""
    if not text:
        return ""
    replacements = {
        "\u2014": "--",   # em dash
        "\u2013": "-",    # en dash
        "\u2018": "'",    # left single quote
        "\u2019": "'",    # right single quote
        "\u201c": '"',    # left double quote
        "\u201d": '"',    # right double quote
        "\u2022": "*",    # bullet
        "\u2192": "->",   # right arrow
        "\u2190": "<-",   # left arrow
        "\u2026": "...",  # ellipsis
        "\u00a0": " ",    # non-breaking space
    }
    for char, replacement in replacements.items():
        text = text.replace(char, replacement)
    return text.encode("latin-1", "replace").decode("latin-1")


def generate_route_brief_pdf(
    brief_id: str,
    origin: Optional[str] = None,
    destination: Optional[str] = None,
    carrier: Optional[str] = None,
    cargo_type: Optional[str] = None,
    recommendation: Optional[str] = None,
    risk_level: Optional[str] = None,
    brief_markdown: Optional[str] = None,
    output_dir: Optional[str] = None,
    markdown_content: Optional[str] = None,
) -> str:
    """
    Generates a PDF route brief report using fpdf2.
    Supports both legacy keyword signatures and content-only signatures.
    """
    target_dir = Path(output_dir or getattr(settings, "BRIEF_STORAGE_PATH", "storage/route_briefs"))
    target_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = target_dir / f"brief_{brief_id}.pdf"

    content = brief_markdown or markdown_content or ""
    if not content and origin and destination:
        content = f"# Route Brief: {origin} to {destination}\n\n"
        if carrier:
            content += f"**Carrier:** {carrier}\n\n"
        if cargo_type:
            content += f"**Cargo Type:** {cargo_type}\n\n"
        if risk_level:
            content += f"**Risk Level:** {risk_level}\n\n"
        if recommendation:
            content += f"## Recommendation\n\n{recommendation}\n\n"

    sanitized = _sanitize_unicode_for_pdf(content)
    html = markdown.markdown(sanitized)

    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_font("helvetica", size=11)

    from fpdf.errors import FPDFException
    try:
        pdf.write_html(html)
    except (FPDFException, Exception):
        pdf = FPDF()
        pdf.add_page()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.set_font("helvetica", size=10)
        pdf.multi_cell(0, 5, text=sanitized)

    pdf.output(str(pdf_path))
    return str(pdf_path)
