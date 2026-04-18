"""
Generates a PDF resume that exactly matches the styling of Chip Bishop's hardware resume.

Font sizes, margins, line heights, and gray rules are all measured from the original PDF.
"""

import io
import pdfplumber
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepInFrame
from reportlab.platypus.flowables import Flowable
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ── Page geometry (measured from original PDF) ────────────────────────────────
PAGE_W   = 596
PAGE_H   = 842
L_MARGIN = 28.3
R_MARGIN = PAGE_W - 566.5   # = 29.5
T_MARGIN = 25.0
B_MARGIN = 30.0
CONTENT_W = PAGE_W - L_MARGIN - R_MARGIN  # = 538.2

LINE_H   = 10.6   # leading for 8pt body text
DATE_COL = 105    # right-column width for dates

GRAY = colors.Color(0.5333, 0.5333, 0.5333)
LINK_COLOR = "#1155CC"
MAX_RESUME_PAGES = 1
MIN_READABLE_BODY_FONT_SIZE = 7.0

# ── Font registration ─────────────────────────────────────────────────────────
_FONTS = [
    ("TNR",       "C:/Windows/Fonts/times.ttf"),
    ("TNR-Bold",  "C:/Windows/Fonts/timesbd.ttf"),
    ("TNR-Italic","C:/Windows/Fonts/timesi.ttf"),
    ("TNR-BI",    "C:/Windows/Fonts/timesbi.ttf"),
    ("Arial",     "C:/Windows/Fonts/arial.ttf"),
]

def _register():
    for name, path in _FONTS:
        try:
            pdfmetrics.registerFont(TTFont(name, path))
        except Exception:
            pass
    pdfmetrics.registerFontFamily("TNR",
        normal="TNR", bold="TNR-Bold",
        italic="TNR-Italic", boldItalic="TNR-BI")

_register()


class ResumeTooLongError(ValueError):
    """Raised when the rendered resume exceeds the allowed page count."""

# ── Styles ────────────────────────────────────────────────────────────────────
def _ps(name, **kw):
    s = ParagraphStyle(name)
    for k, v in kw.items():
        setattr(s, k, v)
    return s

S_NAME    = _ps("name",    fontName="TNR-Bold",   fontSize=20, leading=24,   alignment=TA_CENTER)
S_CONTACT = _ps("contact", fontName="TNR",        fontSize=9,  leading=11,   alignment=TA_CENTER)
S_HEAD    = _ps("head",    fontName="TNR-Bold",   fontSize=8,  leading=LINE_H, spaceAfter=0, spaceBefore=0)
S_HEAD_R  = _ps("head_r",  fontName="TNR",        fontSize=8,  leading=LINE_H, alignment=TA_RIGHT, spaceAfter=0, spaceBefore=0)
S_SUB     = _ps("sub",     fontName="TNR-Italic", fontSize=8,  leading=LINE_H, spaceAfter=0, spaceBefore=0)
S_SUB_R   = _ps("sub_r",   fontName="TNR-Bold",   fontSize=8,  leading=LINE_H, alignment=TA_RIGHT, spaceAfter=0, spaceBefore=0)
S_BODY    = _ps("body",    fontName="TNR",        fontSize=8,  leading=LINE_H, spaceAfter=0, spaceBefore=0)
S_SKILL   = _ps("skill",   fontName="TNR",        fontSize=8,  leading=LINE_H, spaceAfter=0, spaceBefore=0)
S_BULLET  = _ps("bullet",  fontName="TNR",        fontSize=8,  leading=LINE_H,
                leftIndent=36, firstLineIndent=-18, spaceAfter=0, spaceBefore=0)
BASE_MIN_CONTENT_FONT_SIZE = min(
    S_HEAD.fontSize,
    S_HEAD_R.fontSize,
    S_SUB.fontSize,
    S_SUB_R.fontSize,
    S_BODY.fontSize,
    S_SKILL.fontSize,
    S_BULLET.fontSize,
)

# ── Custom flowable: section header + gray rule ───────────────────────────────
class SectionHeader(Flowable):
    HEIGHT = 26.0  # total height: text + rule gap

    def __init__(self, title):
        super().__init__()
        self.title = title

    def wrap(self, aw, ah):
        self._w = aw
        return (aw, self.HEIGHT)

    def draw(self):
        c = self.canv
        c.setFont("TNR", 12)
        c.setFillColorRGB(0, 0, 0)
        c.drawString(0, 10, self.title)        # baseline ~10pt from bottom
        c.setStrokeColor(GRAY)
        c.setLineWidth(0.75)
        c.line(0, 3, self._w, 3)              # rule 3pt from bottom

# ── Helpers ───────────────────────────────────────────────────────────────────
def _esc(text):
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def _row(left_para, right_para):
    """Left-bold + right-aligned date on one line."""
    t = Table(
        [[left_para, right_para]],
        colWidths=[CONTENT_W - DATE_COL, DATE_COL],
    )
    t.setStyle(TableStyle([
        ("ALIGN",         (1, 0), (1, 0), "RIGHT"),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING",    (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
    ]))
    return t

def _contact_html(raw):
    """Pipe-separated contact string → HTML with clickable blue links."""
    parts = [p.strip() for p in raw.split("|")]
    out = []
    for p in parts:
        e = _esc(p)
        if p.startswith("http") or (p.startswith("www")):
            out.append(f'<link href="{e}" color="{LINK_COLOR}"><u>{e}</u></link>')
        elif "@" in p and "." in p:
            out.append(f'<link href="mailto:{e}" color="{LINK_COLOR}"><u>{e}</u></link>')
        elif "." in p and "/" in p:
            href = p if p.startswith("http") else "https://" + p
            out.append(f'<link href="{href}" color="{LINK_COLOR}"><u>{e}</u></link>')
        else:
            out.append(e)
    return " | ".join(out)

def _body_para(text):
    """Body paragraph — bolds a short label before ':' if present."""
    colon = text.find(":")
    if 0 < colon < 30 and " " not in text[:colon]:
        label = _esc(text[:colon + 1])
        rest  = _esc(text[colon + 1:])
        return Paragraph(f"<b>{label}</b>{rest}", S_BODY)
    return Paragraph(_esc(text), S_BODY)

# ── Story builder ─────────────────────────────────────────────────────────────
def _build_story(data):
    story = []

    # Name
    story.append(Paragraph(_esc(data.get("name", "")), S_NAME))
    story.append(Spacer(1, 2))

    # Contact line
    story.append(Paragraph(_contact_html(data.get("contact", "")), S_CONTACT))
    story.append(Spacer(1, 12))

    sections = data.get("sections", [])
    for i, section in enumerate(sections):
        if i > 0:
            story.append(Spacer(1, 11))  # gap between sections (~matches original)

        story.append(SectionHeader(section["title"]))

        entries = section.get("entries", [])
        is_skills = entries and "label" in entries[0]

        for j, entry in enumerate(entries):
            if is_skills:
                label = _esc(entry.get("label", ""))
                text  = _esc(entry.get("text", ""))
                story.append(Paragraph(f"<b>{label}:</b> {text}", S_SKILL))
            else:
                if j > 0:
                    story.append(Spacer(1, 3))

                heading       = _esc(entry.get("heading", ""))
                heading_right = _esc(entry.get("heading_right", ""))
                subheading    = _esc(entry.get("subheading", ""))
                subheading_r  = _esc(entry.get("subheading_right", ""))
                body          = entry.get("body", "")
                bullets       = entry.get("bullets", [])

                # Heading row
                if heading_right:
                    story.append(_row(
                        Paragraph(f"<b>{heading}</b>", S_HEAD),
                        Paragraph(heading_right, S_HEAD_R),
                    ))
                else:
                    story.append(Paragraph(f"<b>{heading}</b>", S_HEAD))

                # Subheading row (italic degree + bold GPA)
                if subheading:
                    if subheading_r:
                        story.append(_row(
                            Paragraph(f"<i>{subheading}</i>", S_SUB),
                            Paragraph(f"<b>{subheading_r}</b>", S_SUB_R),
                        ))
                    else:
                        story.append(Paragraph(f"<i>{subheading}</i>", S_SUB))

                # Body text (e.g. Relevant Coursework)
                if body:
                    story.append(_body_para(body))

                # Bullet points with hanging indent
                for bullet in bullets:
                    story.append(Paragraph(
                        f'<font name="Arial">\u25cf</font> {_esc(bullet)}',
                        S_BULLET,
                    ))

    return story


def _count_pdf_pages(pdf_bytes: bytes) -> int:
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return len(pdf.pages)


def _get_min_rendered_font_size(flowable: KeepInFrame) -> float:
    shrink_scale = getattr(flowable, "_scale", 1.0)
    return BASE_MIN_CONTENT_FONT_SIZE / shrink_scale

# ── Public API ────────────────────────────────────────────────────────────────
def generate_resume_pdf(data: dict, max_pages: int = MAX_RESUME_PAGES) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=(PAGE_W, PAGE_H),
        leftMargin=L_MARGIN,
        rightMargin=R_MARGIN,
        topMargin=T_MARGIN,
        bottomMargin=B_MARGIN,
    )
    story = _build_story(data)
    fitted_resume = KeepInFrame(doc.width, doc.height, story, mode="shrink", hAlign="LEFT", vAlign="TOP")
    fitted_story = [fitted_resume]
    doc.build(fitted_story)
    pdf_bytes = buf.getvalue()

    min_rendered_font_size = _get_min_rendered_font_size(fitted_resume)
    if min_rendered_font_size < MIN_READABLE_BODY_FONT_SIZE - 0.01:
        raise ResumeTooLongError(
            f"Resume would need to shrink below {MIN_READABLE_BODY_FONT_SIZE:.1f}pt to fit on one page. "
            "Tighten the wording slightly or trim lower-priority detail."
        )

    if max_pages is not None:
        page_count = _count_pdf_pages(pdf_bytes)
        if page_count > max_pages:
            raise ResumeTooLongError(
                f"Resume content exceeds the {max_pages}-page limit. "
                "Trim less relevant bullets or shorten long descriptions."
            )

    return pdf_bytes
