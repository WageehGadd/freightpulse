import os
import markdown
from fpdf import FPDF
from pathlib import Path

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
    # Encode to latin-1 with replacement fallback for any other obscure symbols
    return text.encode("latin-1", "replace").decode("latin-1")

def generate_route_brief_pdf(brief_id: str, markdown_content: str) -> str:
    """
    Generates a PDF from markdown content and saves it.
    Returns the absolute or relative path to the generated PDF.
    """
    # Ensure storage directory exists
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)

    pdf_path = STORAGE_DIR / f"{brief_id}.pdf"

    sanitized_content = _sanitize_unicode_for_pdf(markdown_content)

    # Convert markdown to basic HTML for fpdf2
    html = markdown.markdown(sanitized_content)

    # Generate PDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    # Use standard fonts available in fpdf2
    pdf.set_font("helvetica", size=12)

    # fpdf2's write_html can parse basic HTML
    from fpdf.errors import FPDFException
    try:
        pdf.write_html(html)
    except FPDFException:
        # Fallback to plain text if HTML parsing fails
        pdf = FPDF()
        pdf.add_page()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.set_font("helvetica", size=11)
        pdf.multi_cell(0, 5, text=sanitized_content)

    pdf.output(str(pdf_path))

    return str(pdf_path)
