import os
import markdown
from fpdf import FPDF
from pathlib import Path

STORAGE_DIR = Path("storage/route_briefs")

def generate_route_brief_pdf(brief_id: str, markdown_content: str) -> str:
    """
    Generates a PDF from markdown content and saves it.
    Returns the absolute or relative path to the generated PDF.
    """
    # Ensure storage directory exists
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)

    pdf_path = STORAGE_DIR / f"{brief_id}.pdf"

    # Convert markdown to basic HTML for fpdf2
    html = markdown.markdown(markdown_content)

    # Generate PDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    # Use standard fonts available in fpdf2
    pdf.set_font("helvetica", size=12)

    # fpdf2's write_html can parse basic HTML
    try:
        pdf.write_html(html)
    except Exception as e:
        # Fallback to plain text if HTML parsing fails
        pdf.set_font("helvetica", size=11)
        pdf.multi_cell(0, 5, text=markdown_content)

    pdf.output(str(pdf_path))

    return str(pdf_path)
