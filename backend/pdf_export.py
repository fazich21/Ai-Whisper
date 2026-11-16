from datetime import datetime
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def clean(text) -> str:
    """Make text safe for the PDF library (special characters, new lines)."""
    return escape(str(text or "")).replace("\n", "<br/>")


def build_pdf(summary: str, action_items: list, transcript: str) -> bytes:
    """Take the notes and return the PDF file as bytes."""
    styles = getSampleStyleSheet()
    normal = styles["Normal"]

    buffer = BytesIO()                       # the PDF is built in memory, not on disk
    doc = SimpleDocTemplate(buffer, pagesize=A4, title="Meeting Notes")

    story = []                               # the list of things to put on the page

    story.append(Paragraph("Meeting Notes", styles["Title"]))
    story.append(Paragraph(datetime.now().strftime("%d %B %Y, %H:%M"), normal))
    story.append(Spacer(1, 14))

    story.append(Paragraph("Summary", styles["Heading2"]))
    story.append(Paragraph(clean(summary), normal))
    story.append(Spacer(1, 14))

    story.append(Paragraph("Action items", styles["Heading2"]))
    if action_items:
        rows = [["Task", "Owner", "Deadline"]]
        for item in action_items:
            rows.append([
                Paragraph(clean(item.get("task")), normal),
                Paragraph(clean(item.get("owner")), normal),
                Paragraph(clean(item.get("deadline")), normal),
            ])
        table = Table(rows, colWidths=[230, 110, 110], repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(table)
    else:
        story.append(Paragraph("No action items.", normal))
    story.append(Spacer(1, 14))

    story.append(Paragraph("Full transcript", styles["Heading2"]))
    story.append(Paragraph(clean(transcript), normal))

    doc.build(story)                         # draw everything into the buffer
    return buffer.getvalue()
