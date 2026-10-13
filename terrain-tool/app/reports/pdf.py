"""PDF renderer: ReportLab platypus, A4.

Only fonts built into ReportLab are used (the Helvetica family, plus the STSong-Light
CID font for Chinese characters in site names, whose glyphs the PDF viewer supplies), so
rendering works on any machine with nothing to install. Helvetica only covers WinAnsi;
other characters are transliterated by ``_drawable()``. Every piece of block text goes
through ``esc()`` because ReportLab paragraphs are a mini-HTML dialect and site names
come from the visitor's KML.
"""
from __future__ import annotations

import math
import unicodedata
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (BaseDocTemplate, Flowable, Frame, Image, KeepTogether,
                                NextPageTemplate, PageBreak, PageTemplate, Paragraph, Spacer, Table,
                                TableStyle)

from . import content as c

PAGE_W, PAGE_H = A4
MARGIN = 18 * mm               # left / right
TOP = 24 * mm                  # body pages: room for the running header
BOTTOM = 20 * mm               # room for the footer
COVER_TOP = 21 * mm            # cover: the navy band starts above the frame and holds the header
FRAME_W = PAGE_W - 2 * MARGIN
BODY_H = PAGE_H - TOP - BOTTOM
FIGURE_RESERVE = 50 * mm       # headings + caption kept on the page with each figure

FONT, BOLD, ITALIC = "Helvetica", "Helvetica-Bold", "Helvetica-Oblique"
CJK_FONT = "STSong-Light"      # ReportLab built-in CID font: no font file needed

NAVY = colors.HexColor("#0F2742")
NAVY_LINE = colors.HexColor("#1F4166")
GOLD = colors.HexColor("#D4A23A")
INK = colors.HexColor("#12233A")
INK_SOFT = colors.HexColor("#48586C")
CLOUD = colors.HexColor("#AFBFCF")
RULE = colors.HexColor("#D6DCE3")
ZEBRA = colors.HexColor("#F6F3ED")
TOTAL_BG = colors.HexColor("#E8EDF3")
WHITE = colors.white

# level -> (bar colour, label colour, tinted background)
LEVEL_COLOURS = {
    "warning": (colors.HexColor("#C0392B"), colors.HexColor("#A61B1B"), colors.HexColor("#FDEEEC")),
    "caution": (colors.HexColor("#D97706"), colors.HexColor("#92400E"), colors.HexColor("#FEF6E7")),
    "info": (NAVY, NAVY, colors.HexColor("#EDF1F6")),
}

# EcoEnergy leaf mark (app/static/logo-mark.svg), in its 100 x 100 path units, y down.
_LEAF = ((55, 5), [((18, 18), (4, 55), (6, 100)), ((48, 96), (86, 70), (92, 28)),
                   ((72, 40), (50, 58), (40, 86)), ((44, 56), (47, 26), (55, 5))])

if CJK_FONT not in pdfmetrics.getRegisteredFontNames():
    pdfmetrics.registerFont(UnicodeCIDFont(CJK_FONT))


# ---------------------------------------------------------------------------
# text: escaping and the WinAnsi character set of the built-in fonts
# ---------------------------------------------------------------------------
# Characters outside WinAnsi that have an obvious ASCII stand-in.
_SUBST = {"≥": ">=", "≤": "<=", "→": "->", "←": "<-", "−": "-", "‑": "-", "≈": "~",
          "′": "'", "″": '"', " ": " ", " ": " ", "​": ""}


def _is_cjk(ch: str) -> bool:
    o = ord(ch)
    return 0x2E80 <= o <= 0x9FFF or 0xF900 <= o <= 0xFAFF or 0xFF00 <= o <= 0xFFEF


def _drawable(ch: str) -> str:
    """One character -> text the standard Type 1 fonts can draw (they only know WinAnsi)."""
    try:
        ch.encode("cp1252")
        return ch
    except UnicodeEncodeError:
        pass
    if ch in _SUBST:
        return _SUBST[ch]
    # Accented Latin letters outside WinAnsi (ā, ș, ő, ...) lose the accent rather than the letter.
    base = "".join(b for b in unicodedata.normalize("NFKD", ch) if not unicodedata.combining(b))
    try:
        base.encode("cp1252")
        return base or "?"
    except UnicodeEncodeError:
        return "?"


def esc(text) -> str:
    """Untrusted plain text -> ReportLab paragraph markup (escaped, drawable, CJK in a CID font)."""
    out: list[str] = []
    cjk: list[str] = []

    def flush() -> None:
        if cjk:
            out.append(f'<font name="{CJK_FONT}">{escape("".join(cjk))}</font>')
            cjk.clear()

    for ch in str(text):
        if ch == "\n":
            flush()
            out.append("<br/>")
        elif _is_cjk(ch):
            cjk.append(ch)
        else:
            flush()
            out.append(escape(_drawable(ch), {'"': "&quot;"}))
    flush()
    return "".join(out)


def plain(text) -> str:
    """Text for canvas.drawString (no markup, one line)."""
    return "".join(_drawable(ch) for ch in str(text).replace("\n", " "))


def _attr(value: str) -> str:
    return escape(value, {'"': "&quot;"})


def _hex(colour: colors.Color) -> str:
    return "#" + colour.hexval()[2:]


# ---------------------------------------------------------------------------
# styles
# ---------------------------------------------------------------------------
def _styles() -> dict[str, ParagraphStyle]:
    def ps(name, **kw) -> ParagraphStyle:
        base = dict(fontName=FONT, fontSize=9.5, leading=13.6, textColor=INK)
        base.update(kw)
        return ParagraphStyle(name, **base)

    th = dict(fontName=BOLD, fontSize=7.6, leading=9.4, textColor=WHITE)
    td = dict(fontSize=8.2, leading=10.4)
    return {
        "body": ps("body", spaceAfter=6),
        "lead": ps("lead", fontSize=10.5, leading=15.2, spaceAfter=7),
        "note": ps("note", fontName=ITALIC, fontSize=8.2, leading=11.4, textColor=INK_SOFT,
                   spaceAfter=6),
        "h1": ps("h1", fontName=BOLD, fontSize=15.5, leading=19, textColor=NAVY, spaceBefore=12,
                 spaceAfter=3, keepWithNext=1),
        "h2": ps("h2", fontName=BOLD, fontSize=11.5, leading=14.5, textColor=NAVY, spaceBefore=11,
                 spaceAfter=6, keepWithNext=1),
        "th": ps("th", **th),
        "th_r": ps("th_r", alignment=TA_RIGHT, **th),
        "th_c": ps("th_c", alignment=TA_CENTER, **th),
        "td": ps("td", **td),
        "td_r": ps("td_r", alignment=TA_RIGHT, **td),
        "td_total": ps("td_total", fontName=BOLD, **td),
        "td_total_r": ps("td_total_r", fontName=BOLD, alignment=TA_RIGHT, **td),
        "table_note": ps("table_note", fontName=ITALIC, fontSize=7.6, leading=10.2,
                         textColor=INK_SOFT, spaceBefore=5, spaceAfter=4),
        "kv_key": ps("kv_key", fontName=BOLD, fontSize=8.4, leading=11.6, textColor=INK_SOFT),
        "kv_val": ps("kv_val", fontSize=9, leading=12.2),
        "callout_label": ps("callout_label", fontName=BOLD, fontSize=7, leading=9, spaceAfter=1.5),
        "callout_title": ps("callout_title", fontName=BOLD, fontSize=9.8, leading=12.8, spaceAfter=2.5),
        "callout_body": ps("callout_body", fontSize=8.8, leading=12.4),
        "callout_source": ps("callout_source", fontName=ITALIC, fontSize=7.6, leading=10,
                             textColor=INK_SOFT, spaceBefore=3.5),
        "li": ps("li", leftIndent=13, bulletIndent=1.5, spaceAfter=4.5),
        "li_num": ps("li_num", leftIndent=17, bulletIndent=0, spaceAfter=7, bulletFontName=BOLD),
        "caption": ps("caption", fontSize=8.6, leading=12, textColor=INK_SOFT, spaceBefore=6,
                      alignment=TA_LEFT),
        "cover_subtitle": ps("cover_subtitle", fontName=BOLD, fontSize=15, leading=19, textColor=WHITE),
        "cover_location": ps("cover_location", fontSize=10.5, leading=14, textColor=CLOUD),
        "cta_title": ps("cta_title", fontName=BOLD, fontSize=15, leading=19, textColor=WHITE),
        "cta_body": ps("cta_body", fontSize=9.8, leading=14, textColor=colors.HexColor("#E3E9F0")),
        "cta_link": ps("cta_link", fontSize=8.4, leading=11, textColor=CLOUD),
        "missing": ps("missing", fontName=ITALIC, alignment=TA_CENTER, textColor=INK_SOFT),
    }


# ---------------------------------------------------------------------------
# custom flowables
# ---------------------------------------------------------------------------
def _leaf(canv: Canvas, x: float, y: float, size: float) -> None:
    """Draw the leaf mark with its bottom-left corner at (x, y)."""
    def pt(px, py):
        return x + px * size / 100, y + (100 - py) * size / 100

    start, curves = _LEAF
    p = canv.beginPath()
    p.moveTo(*pt(*start))
    for c1, c2, end in curves:
        p.curveTo(*pt(*c1), *pt(*c2), *pt(*end))
    p.close()
    canv.setFillColor(GOLD)
    canv.drawPath(p, stroke=0, fill=1)


class _CoverBand(Flowable):
    """Full-bleed navy band with brand, title, site, location and the screening-grade pill.

    It sits at the top of the cover frame and paints upwards to the page edge and
    sideways across the margins; its height follows the wrapped site label.
    """
    PAD_TOP, BRAND_H, TITLE_SIZE, PILL_H, PAD_BOTTOM = 5 * mm, 14, 30, 19, 9 * mm

    def __init__(self, cover: c.Cover, st: dict[str, ParagraphStyle]):
        super().__init__()
        self.cover = cover
        self.subtitle = Paragraph(esc(cover.subtitle), st["cover_subtitle"])
        self.location = Paragraph(esc(cover.location), st["cover_location"])

    def wrap(self, avail_w, avail_h):
        text_w = avail_w * 0.74                     # keep text clear of the contour motif
        self._hs = self.subtitle.wrap(text_w, avail_h)[1]
        self._hl = self.location.wrap(text_w, avail_h)[1]
        self.width = avail_w
        self.height = (self.PAD_TOP + self.BRAND_H + 16 + self.TITLE_SIZE + 12 + self._hs + 4
                       + self._hl + 16 + self.PILL_H + self.PAD_BOTTOM)
        return self.width, self.height

    def _contours(self, canv: Canvas, top: float) -> None:
        """Decorative topographic contour lines on the right of the band (fixed, not data)."""
        canv.saveState()
        clip = canv.beginPath()
        clip.rect(-MARGIN, 0, PAGE_W, top)
        canv.clipPath(clip, stroke=0, fill=0)
        canv.setStrokeColor(NAVY_LINE)
        canv.setLineWidth(0.7)
        cx, cy = FRAME_W - 28 * mm, top * 0.50
        for k in range(1, 17):
            r = 7.5 * k + 5
            path = canv.beginPath()
            for i in range(121):
                t = 2 * math.pi * i / 120
                rr = r * (1 + 0.11 * math.sin(3 * t + 0.33 * k) + 0.05 * math.cos(5 * t - 0.21 * k))
                x, y = cx + 1.3 * rr * math.cos(t), cy + 0.95 * rr * math.sin(t)
                if i == 0:
                    path.moveTo(x, y)
                else:
                    path.lineTo(x, y)
            path.close()
            canv.drawPath(path, stroke=1, fill=0)
        canv.restoreState()

    def draw(self):
        canv, h = self.canv, self.height
        top = h + COVER_TOP                       # band reaches the top edge of the page
        canv.saveState()
        canv.setFillColor(NAVY)
        canv.rect(-MARGIN, 0, PAGE_W, top, stroke=0, fill=1)
        self._contours(canv, top)
        canv.setFillColor(GOLD)
        canv.rect(-MARGIN, 0, PAGE_W, 2.4, stroke=0, fill=1)

        y = h - self.PAD_TOP
        _leaf(canv, 0, y - self.BRAND_H, self.BRAND_H)
        canv.setFont(BOLD, 9.5)
        canv.setFillColor(GOLD)
        canv.drawString(self.BRAND_H + 6, y - self.BRAND_H + 3.5, plain(self.cover.brand.upper()),
                        charSpace=1.6)
        y -= self.BRAND_H + 16

        canv.setFont(BOLD, self.TITLE_SIZE)
        canv.setFillColor(WHITE)
        canv.drawString(0, y - self.TITLE_SIZE * 0.78, plain(self.cover.title))
        y -= self.TITLE_SIZE + 12

        self.subtitle.drawOn(canv, 0, y - self._hs)
        y -= self._hs + 4
        self.location.drawOn(canv, 0, y - self._hl)
        y -= self._hl + 16

        label, size, space = plain(self.cover.label.upper()), 8.6, 0.9
        width = canv.stringWidth(label, BOLD, size) + space * len(label) + 26
        canv.setFillColor(GOLD)
        canv.roundRect(0, y - self.PILL_H, width, self.PILL_H, self.PILL_H / 2, stroke=0, fill=1)
        canv.setFillColor(NAVY)
        canv.setFont(BOLD, size)
        canv.drawString(13, y - self.PILL_H + 6.2, label, charSpace=space)
        canv.restoreState()


class _Rule(Flowable):
    """Short gold accent bar under a section heading."""

    def __init__(self, width: float, thickness: float = 1.8, space_after: float = 8):
        super().__init__()
        self.bar_w, self.thickness, self.space_after = width, thickness, space_after
        self.keepWithNext = 1

    def wrap(self, avail_w, avail_h):
        self.width, self.height = avail_w, self.thickness + self.space_after
        return self.width, self.height

    def draw(self):
        self.canv.setFillColor(GOLD)
        self.canv.rect(0, self.space_after, self.bar_w, self.thickness, stroke=0, fill=1)


class _Button(Flowable):
    """Gold rounded button; the whole rectangle is a clickable link."""

    def __init__(self, label: str, url: str, size: float = 10.5, height: float = 27, pad: float = 18):
        super().__init__()
        self.label, self.url, self.size, self.pad = plain(label), url, size, pad
        self.height = height

    def wrap(self, avail_w, avail_h):
        self.width = min(avail_w, pdfmetrics.stringWidth(self.label, BOLD, self.size) + 2 * self.pad)
        return self.width, self.height

    def draw(self):
        canv = self.canv
        canv.setFillColor(GOLD)
        canv.roundRect(0, 0, self.width, self.height, 5, stroke=0, fill=1)
        canv.setFillColor(NAVY)
        canv.setFont(BOLD, self.size)
        canv.drawCentredString(self.width / 2, (self.height - self.size * 0.7) / 2, self.label)
        canv.linkURL(self.url, (0, 0, self.width, self.height), relative=1, thickness=0)


# ---------------------------------------------------------------------------
# block renderers
# ---------------------------------------------------------------------------
def _heading(block: c.Heading, st) -> list[Flowable]:
    if block.level <= 1:
        p = Paragraph(esc(block.text), st["h1"])
        p.outline = (block.text, 0)
        return [p, _Rule(22 * mm)]
    p = Paragraph(esc(block.text), st["h2"])
    p.outline = (block.text, 1)
    return [p]


def _kv_table(rows, st, key_frac: float = 0.29) -> Table:
    data = [[Paragraph(esc(k), st["kv_key"]), Paragraph(esc(v), st["kv_val"])] for k, v in rows]
    t = Table(data, colWidths=[FRAME_W * key_frac, FRAME_W * (1 - key_frac)], hAlign="LEFT")
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [ZEBRA, WHITE]),
        ("LINEABOVE", (0, 0), (-1, 0), 1.1, NAVY),
        ("LINEBELOW", (0, -1), (-1, -1), 1.1, NAVY),
        ("LINEBELOW", (0, 0), (-1, -2), 0.3, RULE),
        ("TOPPADDING", (0, 0), (-1, -1), 4.6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4.6),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
    ]))
    return t


def _data_table(block: c.DataTable, st) -> list[Flowable]:
    rel = sum(block.widths)
    col_w = [FRAME_W * w / rel for w in block.widths]

    def head(i: int) -> Paragraph:
        return Paragraph(esc(block.columns[i]), st["th_r" if block.align[i] == "right" else "th"])

    cmds: list[tuple] = []
    rows: list[list] = []
    if block.groups:
        top, bottom, col = [], [], 0
        for label, span in block.groups:
            if label is None:                      # ungrouped columns: header spans both rows
                for i in range(col, col + span):
                    top.append(head(i))
                    bottom.append("")
                    cmds.append(("SPAN", (i, 0), (i, 1)))
            else:
                top += [Paragraph(esc(label), st["th_c"])] + [""] * (span - 1)
                bottom += [head(i) for i in range(col, col + span)]
                cmds += [("SPAN", (col, 0), (col + span - 1, 0)),
                         ("LINEBELOW", (col, 0), (col + span - 1, 0), 0.6, GOLD)]
            col += span
        rows += [top, bottom]
    else:
        rows.append([head(i) for i in range(len(block.columns))])
    n_head = len(rows)

    def cells(values, left: str, right: str) -> list[Paragraph]:
        return [Paragraph(esc(v), st[right if a == "right" else left])
                for v, a in zip(values, block.align)]

    rows += [cells(r, "td", "td_r") for r in block.rows]
    if block.total:
        rows.append(cells(block.total, "td_total", "td_total_r"))
    last_body = n_head + len(block.rows) - 1

    cmds += [
        ("BACKGROUND", (0, 0), (-1, n_head - 1), NAVY),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3.4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.6),
        ("LEFTPADDING", (0, 0), (-1, -1), 4.5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4.5),
        ("LINEBELOW", (0, -1), (-1, -1), 1.0, NAVY),
    ]
    if block.rows:
        cmds += [("ROWBACKGROUNDS", (0, n_head), (-1, last_body), [WHITE, ZEBRA]),
                 ("LINEBELOW", (0, n_head), (-1, last_body), 0.3, RULE)]
    if block.total:
        cmds += [("BACKGROUND", (0, -1), (-1, -1), TOTAL_BG),
                 ("LINEABOVE", (0, -1), (-1, -1), 0.9, NAVY)]
    t = Table(rows, colWidths=col_w, repeatRows=n_head, hAlign="LEFT")
    t.setStyle(TableStyle(cmds))
    out: list[Flowable] = [t]
    if block.note:
        out.append(Paragraph(esc(block.note), st["table_note"]))
    out.append(Spacer(1, 4))
    return out


def _callout(block: c.Callout, st) -> list[Flowable]:
    bar, label_colour, tint = LEVEL_COLOURS.get(block.level, LEVEL_COLOURS["info"])
    parts: list[Flowable] = [
        Paragraph(f'<font color="{_hex(label_colour)}">'
                  f"{esc(block.label.upper())}</font>", st["callout_label"]),
        Paragraph(esc(block.title), st["callout_title"]),
        Paragraph(esc(block.text), st["callout_body"]),
    ]
    if block.source:
        parts.append(Paragraph(f"Source: {esc(block.source)}", st["callout_source"]))
    bar_w = 3.2 * mm
    t = Table([["", parts]], colWidths=[bar_w, FRAME_W - bar_w], hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), bar),
        ("BACKGROUND", (1, 0), (1, 0), tint),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (0, 0), 0),
        ("RIGHTPADDING", (0, 0), (0, 0), 0),
        ("LEFTPADDING", (1, 0), (1, 0), 10),
        ("RIGHTPADDING", (1, 0), (1, 0), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    return [t, Spacer(1, 6)]


def _list(block: c.BulletList, st) -> list[Flowable]:
    out: list[Flowable] = []
    for i, item in enumerate(block.items, 1):
        if block.numbered:
            body = (f'<font color="{_hex(NAVY)}"><b>{esc(item.title)}</b></font><br/>'
                    if item.title else "") + esc(item.text)
            bullet = f'<bullet color="#B8841F" font="{BOLD}">{i}.</bullet>'
            out.append(Paragraph(bullet + body, st["li_num"]))
        else:
            body = (f"<b>{esc(item.title)}</b> " if item.title else "") + esc(item.text)
            out.append(Paragraph(f'<bullet color="#D4A23A">•</bullet>{body}', st["li"]))
    return out


def _figure(block: c.Figure, st) -> list[Flowable]:
    caption = Paragraph(f"<b>Figure {block.number}.</b> {esc(block.caption)}", st["caption"])
    if block.path is None or not block.size_px:
        box = Table([[Paragraph("This figure could not be produced.", st["missing"])]],
                    colWidths=[FRAME_W], rowHeights=[60 * mm])
        box.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, RULE),
                                 ("BACKGROUND", (0, 0), (-1, -1), ZEBRA),
                                 ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
        box.keepWithNext = 1
        return [box, caption]
    w_px, h_px = block.size_px
    max_h = BODY_H - FIGURE_RESERVE
    w, h = FRAME_W, FRAME_W * h_px / w_px
    if h > max_h:                                 # tall figure: fit the height instead
        w, h = max_h * w_px / h_px, max_h
    img = Image(str(block.path), width=w, height=h)
    frame = Table([[img]], colWidths=[w], rowHeights=[h], hAlign="CENTER")
    frame.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.5, RULE),
                               ("LEFTPADDING", (0, 0), (-1, -1), 0),
                               ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                               ("TOPPADDING", (0, 0), (-1, -1), 0),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    frame.keepWithNext = 1
    return [frame, caption]


def _cta(block: c.Cta, st) -> list[Flowable]:
    url = block.url_for("pdf")
    inner = [
        Paragraph(esc(block.title), st["cta_title"]),
        Spacer(1, 5),
        Paragraph(esc(block.text), st["cta_body"]),
        Spacer(1, 12),
        _Button(f"{block.link_text}  »", url),
        Spacer(1, 8),
        Paragraph(f'<a href="{_attr(url)}" color="{_hex(GOLD)}">{esc(block.display_url)}</a>',
                  st["cta_link"]),
    ]
    t = Table([[inner]], colWidths=[FRAME_W], hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), NAVY),
        ("LINEABOVE", (0, 0), (-1, 0), 3, GOLD),
        ("LEFTPADDING", (0, 0), (-1, -1), 18),
        ("RIGHTPADDING", (0, 0), (-1, -1), 18),
        ("TOPPADDING", (0, 0), (-1, -1), 16),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 16),
    ]))
    return [t]


def _story(blocks: list, st) -> list[Flowable]:
    story: list[Flowable] = []
    kept: list[Flowable] | None = None            # flowables of a keep_section section
    after_heading = False
    for block in blocks:
        ends_section = (isinstance(block, (c.PageBreak, c.Cta))
                        or (isinstance(block, c.Heading) and block.level <= 1))
        if kept is not None and ends_section:
            # Moves to the next page if it does not fit; splits normally if longer than a page.
            story.append(KeepTogether(kept))
            kept = None
        if isinstance(block, c.Heading) and block.keep_section:
            kept = []
        out = story if kept is None else kept
        if isinstance(block, c.Cover):
            out += [_CoverBand(block, st), NextPageTemplate("body"), Spacer(1, 9 * mm),
                    _kv_table(block.details, st), Spacer(1, 3 * mm)]
        elif isinstance(block, c.Heading):
            out += _heading(block, st)
        elif isinstance(block, c.Paragraph):
            p = Paragraph(esc(block.text), st.get(block.style, st["body"]))
            if after_heading:                     # an intro line stays with what it introduces
                p.keepWithNext = 1
            out.append(p)
        elif isinstance(block, c.BulletList):
            out += _list(block, st)
        elif isinstance(block, c.KeyValueTable):
            out += [_kv_table(block.rows, st), Spacer(1, 4)]
        elif isinstance(block, c.DataTable):
            out += _data_table(block, st)
        elif isinstance(block, c.Callout):
            out += _callout(block, st)
        elif isinstance(block, c.Figure):
            out += _figure(block, st)
        elif isinstance(block, c.PageBreak):
            out.append(PageBreak())
        elif isinstance(block, c.Cta):
            out += _cta(block, st)
        after_heading = isinstance(block, c.Heading)
    if kept is not None:
        story.append(KeepTogether(kept))
    return story


# ---------------------------------------------------------------------------
# document: page templates, running header/footer, outline
# ---------------------------------------------------------------------------
def _draw_furniture(canv: Canvas, info: c.DocInfo, page: int, total: int) -> None:
    on_cover = page == 1                          # the cover band is navy: use light text there
    canv.saveState()
    y = PAGE_H - 12.5 * mm
    brand = plain(info.header_brand)
    canv.setFont(BOLD, 7.6)
    canv.setFillColor(GOLD if on_cover else NAVY)
    canv.drawString(MARGIN, y, brand)
    canv.setFont(FONT, 7.6)
    canv.setFillColor(CLOUD if on_cover else INK_SOFT)
    canv.drawString(MARGIN + pdfmetrics.stringWidth(brand, BOLD, 7.6), y,
                    plain(f" · {info.header_title}"))
    canv.drawRightString(PAGE_W - MARGIN, y, plain(f"{info.header_right} · page {page} of {total}"))
    if not on_cover:
        canv.setStrokeColor(GOLD)
        canv.setLineWidth(0.6)
        canv.line(MARGIN, y - 3.4 * mm, PAGE_W - MARGIN, y - 3.4 * mm)
    canv.setStrokeColor(RULE)
    canv.setLineWidth(0.4)
    canv.line(MARGIN, 13 * mm, PAGE_W - MARGIN, 13 * mm)
    canv.setFont(FONT, 7)
    canv.setFillColor(INK_SOFT)
    canv.drawCentredString(PAGE_W / 2, 8.6 * mm, plain(info.footer))
    canv.restoreState()


def _canvas_class(info: c.DocInfo) -> type[Canvas]:
    """Canvas that defers page furniture until the page count ("page N of M") is known."""
    class _ReportCanvas(Canvas):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._pages: list[dict] = []

        def showPage(self):
            self._pages.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._pages)
            for state in self._pages:
                self.__dict__.update(state)
                _draw_furniture(self, info, self._pageNumber, total)
                Canvas.showPage(self)
            Canvas.save(self)

    return _ReportCanvas


class _ReportDoc(BaseDocTemplate):
    def __init__(self, path: Path, info: c.DocInfo):
        super().__init__(
            str(path), pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=TOP,
            bottomMargin=BOTTOM, title=plain(info.title), author=info.author,
            subject=plain(info.subject), creator=c.ENGINE_CREDIT.removeprefix("Analysis: "),
            keywords=[plain(k) for k in info.keywords], displayDocTitle=True, lang="en-MY")
        frame = dict(leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
        self.addPageTemplates([
            PageTemplate("cover", [Frame(MARGIN, BOTTOM, FRAME_W, PAGE_H - BOTTOM - COVER_TOP,
                                         id="cover", **frame)]),
            PageTemplate("body", [Frame(MARGIN, BOTTOM, FRAME_W, BODY_H, id="body", **frame)]),
        ])
        self._marks = 0
        self._outline_level = -1

    def afterFlowable(self, flowable):
        mark = getattr(flowable, "outline", None)
        if not mark:
            return
        text, level = mark
        level = min(level, self._outline_level + 1)   # PDF outlines may not skip a level
        self._outline_level = level
        key = f"section-{self._marks}"
        self._marks += 1
        self.canv.bookmarkPage(key)
        self.canv.addOutlineEntry(text, key, level=level, closed=False)


def render_pdf(content: c.ReportContent, path: Path) -> Path:
    """Write the report PDF for `content` to `path`."""
    path = Path(path)
    doc = _ReportDoc(path, content.info)
    doc.build(_story(content.blocks, _styles()), canvasmaker=_canvas_class(content.info))
    return path
