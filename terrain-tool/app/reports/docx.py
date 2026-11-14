"""Word renderer (python-docx), A4.

Walks the same blocks as the PDF renderer. Sections use the built-in Heading 1 / Heading 2
styles so Word's navigation pane works. python-docx has no API for cell shading, borders,
page-number fields or hyperlinks, so small OXML helpers below add them; each inserts its
element at the position the WordprocessingML schema requires, which Word enforces.
python-docx escapes text itself; block text is already free of XML-illegal characters.
"""
from __future__ import annotations

from datetime import timezone
from pathlib import Path

from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_TAB_ALIGNMENT
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Emu, Mm, Pt, RGBColor

from . import content as c

FONT = "Arial"                 # present on every Word / LibreOffice install
NAVY, GOLD, GOLD_DEEP = "0F2742", "D4A23A", "B8841F"
INK, INK_SOFT, CLOUD, WHITE = "12233A", "48586C", "AFBFCF", "FFFFFF"
RULE, ZEBRA, TOTAL_BG = "D6DCE3", "F6F3ED", "E8EDF3"
# level -> (bar colour, label colour, tinted background); same palette as the PDF
LEVEL_COLOURS = {
    "warning": ("C0392B", "A61B1B", "FDEEEC"),
    "caution": ("D97706", "92400E", "FEF6E7"),
    "info": (NAVY, NAVY, "EDF1F6"),
}

MARGIN = Mm(18)
TEXT_W = Mm(210 - 2 * 18)
FIGURE_W_CM = 16.0
FIGURE_MAX_H_CM = 20.0         # tall figures are fitted to this height instead

# Child order inside property elements (ECMA-376 sequences, trimmed to what we touch and
# what may already be present).
_PPR_ORDER = ("w:pStyle", "w:keepNext", "w:keepLines", "w:pageBreakBefore", "w:framePr",
              "w:widowControl", "w:numPr", "w:suppressLineNumbers", "w:pBdr", "w:shd", "w:tabs",
              "w:suppressAutoHyphens", "w:kinsoku", "w:wordWrap", "w:overflowPunct",
              "w:topLinePunct", "w:autoSpaceDE", "w:autoSpaceDN", "w:bidi", "w:adjustRightInd",
              "w:snapToGrid", "w:spacing", "w:ind", "w:contextualSpacing", "w:mirrorIndents",
              "w:suppressOverlap", "w:jc", "w:textDirection", "w:textAlignment",
              "w:textboxTightWrap", "w:outlineLvl", "w:divId", "w:cnfStyle", "w:rPr", "w:sectPr",
              "w:pPrChange")
_RPR_ORDER = ("w:rStyle", "w:rFonts", "w:b", "w:bCs", "w:i", "w:iCs", "w:caps", "w:smallCaps",
              "w:strike", "w:dstrike", "w:outline", "w:shadow", "w:emboss", "w:imprint",
              "w:noProof", "w:snapToGrid", "w:vanish", "w:webHidden", "w:color", "w:spacing",
              "w:w", "w:kern", "w:position", "w:sz", "w:szCs", "w:highlight", "w:u", "w:effect",
              "w:bdr", "w:shd", "w:fitText", "w:vertAlign", "w:rtl", "w:cs", "w:em", "w:lang",
              "w:eastAsianLayout", "w:specVanish", "w:oMath")
_TCPR_ORDER = ("w:cnfStyle", "w:tcW", "w:gridSpan", "w:hMerge", "w:vMerge", "w:tcBorders",
               "w:shd", "w:noWrap", "w:tcMar", "w:textDirection", "w:tcFitText", "w:vAlign",
               "w:hideMark", "w:headers", "w:cellIns", "w:cellDel", "w:cellMerge", "w:tcPrChange")
_TBLPR_ORDER = ("w:tblStyle", "w:tblpPr", "w:tblOverlap", "w:bidiVisual", "w:tblStyleRowBandSize",
                "w:tblStyleColBandSize", "w:tblW", "w:jc", "w:tblCellSpacing", "w:tblInd",
                "w:tblBorders", "w:shd", "w:tblLayout", "w:tblCellMar", "w:tblLook",
                "w:tblCaption", "w:tblDescription", "w:tblPrChange")
_BORDER_ORDER = ("top", "left", "bottom", "right", "insideH", "insideV")


# ---------------------------------------------------------------------------
# OXML helpers
# ---------------------------------------------------------------------------
def _child(parent, tag: str, order: tuple[str, ...], **attrs):
    """Get or create `tag` under `parent` at its schema position, then set w:* attributes."""
    el = parent.find(qn(tag))
    if el is None:
        el = OxmlElement(tag)
        successors = order[order.index(tag) + 1:]
        parent.insert_element_before(el, *successors)
    for key, value in attrs.items():
        el.set(qn(f"w:{key}"), str(value))
    return el


def _borders(parent, tag: str, order: tuple[str, ...], **edges) -> None:
    """edges: name=(hex colour, size in eighths of a point) or None for no border."""
    box = _child(parent, tag, order)
    for name in _BORDER_ORDER:
        if name not in edges:
            continue
        old = box.find(qn(f"w:{name}"))
        if old is not None:
            box.remove(old)
        el = OxmlElement(f"w:{name}")
        spec = edges[name]
        if spec is None:
            el.set(qn("w:val"), "nil")
        else:
            colour, size = spec
            for k, v in (("val", "single"), ("sz", size), ("space", 0), ("color", colour)):
                el.set(qn(f"w:{k}"), str(v))
        # keep the edges in schema order regardless of the order they were passed
        later = [box.find(qn(f"w:{n}")) for n in _BORDER_ORDER[_BORDER_ORDER.index(name) + 1:]]
        later = [x for x in later if x is not None]
        if later:
            later[0].addprevious(el)
        else:
            box.append(el)


def _shade(cell, fill: str) -> None:
    _child(cell._tc.get_or_add_tcPr(), "w:shd", _TCPR_ORDER, val="clear", color="auto", fill=fill)


def _cell_borders(cell, **edges) -> None:
    _borders(cell._tc.get_or_add_tcPr(), "w:tcBorders", _TCPR_ORDER, **edges)


def _cell_margins(cell, top: int, bottom: int, left: int, right: int) -> None:
    """Margins in twentieths of a point (dxa)."""
    mar = _child(cell._tc.get_or_add_tcPr(), "w:tcMar", _TCPR_ORDER)
    for name, value in (("top", top), ("left", left), ("bottom", bottom), ("right", right)):
        el = mar.find(qn(f"w:{name}"))
        if el is None:
            el = OxmlElement(f"w:{name}")
            mar.append(el)
        el.set(qn("w:w"), str(value))
        el.set(qn("w:type"), "dxa")


def _table_margins(table, top: int, bottom: int, left: int, right: int) -> None:
    """Default cell margins for a whole table, in twentieths of a point (dxa)."""
    mar = _child(table._tbl.tblPr, "w:tblCellMar", _TBLPR_ORDER)
    for name, value in (("top", top), ("left", left), ("bottom", bottom), ("right", right)):
        el = mar.find(qn(f"w:{name}"))
        if el is None:
            el = OxmlElement(f"w:{name}")
            mar.append(el)
        el.set(qn("w:w"), str(value))
        el.set(qn("w:type"), "dxa")


def _para_border(pPr, edge: str, colour: str, size: int, space: int = 4) -> None:
    """Add a border edge to a paragraph (or paragraph style) property element."""
    bdr = _child(pPr, "w:pBdr", _PPR_ORDER)
    el = OxmlElement(f"w:{edge}")
    for k, v in (("val", "single"), ("sz", size), ("space", space), ("color", colour)):
        el.set(qn(f"w:{k}"), str(v))
    bdr.append(el)


def _font(run, size: float | None = None, bold: bool | None = None, italic: bool | None = None,
          colour: str | None = None, spacing: float | None = None, highlight: str | None = None):
    f = run.font
    if size is not None:
        f.size = Pt(size)
    if bold is not None:
        f.bold = bold
    if italic is not None:
        f.italic = italic
    if colour is not None:
        f.color.rgb = RGBColor.from_string(colour)
    rPr = run._r.get_or_add_rPr()
    if spacing is not None:                          # letter spacing, in points
        _child(rPr, "w:spacing", _RPR_ORDER, val=int(spacing * 20))
    if highlight is not None:                        # run background (any colour, unlike w:highlight)
        _child(rPr, "w:shd", _RPR_ORDER, val="clear", color="auto", fill=highlight)
    return run


def _style_font(style, name: str = FONT) -> None:
    """Point a style at `name`, dropping theme-font attributes that would override it."""
    rFonts = _child(style.element.get_or_add_rPr(), "w:rFonts", _RPR_ORDER)
    for attr in ("asciiTheme", "hAnsiTheme", "cstheme", "eastAsiaTheme"):
        rFonts.attrib.pop(qn(f"w:{attr}"), None)
    for attr in ("ascii", "hAnsi", "cs"):
        rFonts.set(qn(f"w:{attr}"), name)


def _field(paragraph, instr: str, size: float, colour: str) -> None:
    """Complex field (PAGE, NUMPAGES): Word fills in the value when it lays out the page."""
    def run_with(tag: str, **attrs):
        run = _font(paragraph.add_run(), size=size, colour=colour)
        el = OxmlElement(tag)
        for k, v in attrs.items():
            el.set(qn(k), v)
        run._r.append(el)
        return el

    run_with("w:fldChar", **{"w:fldCharType": "begin"})
    instr_el = run_with("w:instrText", **{"xml:space": "preserve"})
    instr_el.text = f" {instr} "
    run_with("w:fldChar", **{"w:fldCharType": "separate"})
    _font(paragraph.add_run("1"), size=size, colour=colour)
    run_with("w:fldChar", **{"w:fldCharType": "end"})


def _hyperlink(paragraph, url: str, text: str, *, colour: str, size: float, bold: bool = False,
               underline: bool = True, fill: str | None = None) -> None:
    r_id = paragraph.part.relate_to(url, RT.HYPERLINK, is_external=True)
    link = OxmlElement("w:hyperlink")
    link.set(qn("r:id"), r_id)
    link.set(qn("w:history"), "1")
    run = OxmlElement("w:r")
    rPr = OxmlElement("w:rPr")
    run.append(rPr)
    if bold:
        _child(rPr, "w:b", _RPR_ORDER)
    _child(rPr, "w:color", _RPR_ORDER, val=colour)
    _child(rPr, "w:sz", _RPR_ORDER, val=int(size * 2))
    _child(rPr, "w:u", _RPR_ORDER, val="single" if underline else "none")
    if fill:
        _child(rPr, "w:shd", _RPR_ORDER, val="clear", color="auto", fill=fill)
    t = OxmlElement("w:t")
    t.set(qn("xml:space"), "preserve")
    t.text = text
    run.append(t)
    link.append(run)
    paragraph._p.append(link)


def _tight(paragraph, before: float = 0, after: float = 0, line: float = 1.0) -> None:
    pf = paragraph.paragraph_format
    pf.space_before, pf.space_after, pf.line_spacing = Pt(before), Pt(after), line


# ---------------------------------------------------------------------------
# document setup
# ---------------------------------------------------------------------------
def _setup(doc, info: c.DocInfo) -> None:
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Mm(210), Mm(297)
    sec.left_margin = sec.right_margin = MARGIN
    sec.top_margin, sec.bottom_margin = Mm(22), Mm(20)
    sec.header_distance = sec.footer_distance = Mm(9)

    styles = doc.styles
    normal = styles["Normal"]
    _style_font(normal)
    normal.font.size = Pt(10)
    normal.font.color.rgb = RGBColor.from_string(INK)
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.line_spacing = 1.15

    for name, size, before, after in (("Heading 1", 16, 18, 8), ("Heading 2", 12, 12, 5)):
        st = styles[name]
        _style_font(st)
        st.font.size = Pt(size)
        st.font.bold = True
        st.font.italic = False
        st.font.color.rgb = RGBColor.from_string(NAVY)
        pf = st.paragraph_format
        pf.space_before, pf.space_after = Pt(before), Pt(after)
        pf.keep_with_next = True
    _para_border(styles["Heading 1"].element.get_or_add_pPr(), "bottom", GOLD, 12, space=3)

    caption = styles["Caption"]
    _style_font(caption)
    caption.font.size = Pt(8.5)
    caption.font.bold = False
    caption.font.italic = False
    caption.font.color.rgb = RGBColor.from_string(INK_SOFT)
    caption.paragraph_format.space_before = Pt(6)

    for name in ("Header", "Footer"):
        tabs = styles[name].paragraph_format.tab_stops
        tabs.clear_all()
        tabs.add_tab_stop(TEXT_W, WD_TAB_ALIGNMENT.RIGHT)

    # running header: brand left, report id and page N of M right, gold rule underneath
    header = sec.header
    header.is_linked_to_previous = False
    p = header.paragraphs[0]
    _tight(p)
    _font(p.add_run(info.header_brand), size=7.5, bold=True, colour=NAVY)
    _font(p.add_run(f" · {info.header_title}\t{info.header_right} · page "), size=7.5, colour=INK_SOFT)
    _field(p, "PAGE", 7.5, INK_SOFT)
    _font(p.add_run(" of "), size=7.5, colour=INK_SOFT)
    _field(p, "NUMPAGES", 7.5, INK_SOFT)
    _para_border(p._p.get_or_add_pPr(), "bottom", GOLD, 4, space=4)

    footer = sec.footer
    footer.is_linked_to_previous = False
    p = footer.paragraphs[0]
    _tight(p)
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _font(p.add_run(info.footer), size=7.5, colour=INK_SOFT)
    _para_border(p._p.get_or_add_pPr(), "top", RULE, 4, space=4)

    cp = doc.core_properties
    cp.title = info.title
    cp.subject = info.subject
    cp.author = info.author
    cp.last_modified_by = info.author
    cp.keywords = ", ".join(info.keywords)
    cp.comments = c.SCREENING_LABEL
    cp.category = "Desktop terrain screening"
    cp.identifier = info.report_id
    cp.language = "en-MY"
    cp.revision = 1
    if info.generated_at is not None:
        # python-docx writes the value with a literal "Z", so hand it UTC wall time.
        cp.created = cp.modified = info.generated_at.astimezone(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# renderer
# ---------------------------------------------------------------------------
class _Renderer:
    def __init__(self, doc):
        self.doc = doc
        self.pending_break = False

    # -- primitives ---------------------------------------------------------
    def paragraph(self, text: str = "", style: str | None = None):
        p = self.doc.add_paragraph(style=style)
        if text:
            p.add_run(text)
        if self.pending_break:                       # start the next page without an empty line
            p.paragraph_format.page_break_before = True
            self.pending_break = False
        return p

    def table(self, rows: int, widths: list[int]):
        widths = [Emu(int(w)) for w in widths]
        if self.pending_break:
            self.paragraph().add_run().add_break(WD_BREAK.PAGE)
        t = self.doc.add_table(rows=rows, cols=len(widths))
        t.alignment = WD_TABLE_ALIGNMENT.LEFT
        t.autofit = False
        tblPr = t._tbl.tblPr
        _child(tblPr, "w:tblW", _TBLPR_ORDER, w=sum(w.twips for w in widths), type="dxa")
        _child(tblPr, "w:tblLayout", _TBLPR_ORDER, type="fixed")
        _borders(tblPr, "w:tblBorders", _TBLPR_ORDER, top=None, left=None, bottom=None, right=None,
                 insideH=None, insideV=None)
        for col, w in zip(t.columns, widths):
            col.width = w
        for row in t.rows:
            for cell, w in zip(row.cells, widths):
                cell.width = w
        return t

    def spacer(self, pt: float = 4) -> None:
        """Small paragraph after a table: keeps consecutive tables from merging in Word."""
        p = self.doc.add_paragraph()
        _tight(p)
        _font(p.add_run(""), size=pt)
        p.paragraph_format.line_spacing = Pt(pt)

    @staticmethod
    def cell_text(cell, text: str, *, size: float = 8.5, bold: bool = False, colour: str = INK,
                  align: str = "left", italic: bool = False):
        p = cell.paragraphs[0]
        _tight(p)
        p.alignment = {"right": WD_ALIGN_PARAGRAPH.RIGHT,
                       "center": WD_ALIGN_PARAGRAPH.CENTER}.get(align, WD_ALIGN_PARAGRAPH.LEFT)
        _font(p.add_run(text), size=size, bold=bold, italic=italic, colour=colour)
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        return p

    # -- blocks -------------------------------------------------------------
    def cover(self, b: c.Cover) -> None:
        t = self.table(1, [TEXT_W])
        cell = t.cell(0, 0)
        _shade(cell, NAVY)
        _cell_margins(cell, top=420, bottom=440, left=360, right=360)
        _cell_borders(cell, bottom=(GOLD, 24))
        p = cell.paragraphs[0]
        _tight(p, after=10)
        _font(p.add_run(b.brand.upper()), size=9, bold=True, colour=GOLD, spacing=1.5)
        for text, size, bold, colour, after in ((b.title, 28, True, WHITE, 8),
                                                (b.subtitle, 15, True, WHITE, 2),
                                                (b.location, 10.5, False, CLOUD, 14)):
            p = cell.add_paragraph()
            _tight(p, after=after)
            _font(p.add_run(text), size=size, bold=bold, colour=colour)
        p = cell.add_paragraph()
        _tight(p)
        _font(p.add_run(f"  {b.label.upper()}  "), size=8.5, bold=True, colour=NAVY, spacing=0.8,
              highlight=GOLD)
        self.spacer(14)
        self.kv_table(b.details)

    def heading(self, b: c.Heading) -> None:
        self.paragraph(b.text, style="Heading 1" if b.level <= 1 else "Heading 2")

    def text(self, b: c.Paragraph) -> None:
        p = self.paragraph()
        size, italic, colour = {"lead": (11, False, INK), "note": (8.5, True, INK_SOFT)}.get(
            b.style, (10, False, INK))
        _font(p.add_run(b.text), size=size, italic=italic, colour=colour)

    def kv_table(self, rows) -> None:
        t = self.table(len(rows), [int(TEXT_W * 0.29), TEXT_W - int(TEXT_W * 0.29)])
        _borders(t._tbl.tblPr, "w:tblBorders", _TBLPR_ORDER, top=(NAVY, 8), bottom=(NAVY, 8),
                 insideH=(RULE, 4))
        _table_margins(t, top=85, bottom=85, left=130, right=130)
        for i, (key, value) in enumerate(rows):
            k_cell, v_cell = t.rows[i].cells
            self.cell_text(k_cell, key, size=8.5, bold=True, colour=INK_SOFT)
            self.cell_text(v_cell, value, size=9)
            if i % 2 == 0:
                _shade(k_cell, ZEBRA)
                _shade(v_cell, ZEBRA)
        self.spacer()

    def data_table(self, b: c.DataTable) -> None:
        rel = sum(b.widths)
        widths = [int(TEXT_W * w / rel) for w in b.widths]
        n_head = 2 if b.groups else 1
        n_rows = n_head + len(b.rows) + (1 if b.total else 0)
        t = self.table(n_rows, widths)
        _borders(t._tbl.tblPr, "w:tblBorders", _TBLPR_ORDER, bottom=(NAVY, 8), insideH=(RULE, 4))
        _table_margins(t, top=70, bottom=70, left=90, right=90)

        def head(cell, text, align):
            self.cell_text(cell, text, size=7.5, bold=True, colour=WHITE, align=align)

        if b.groups:
            col = 0
            for label, span in b.groups:
                if label is None:                    # ungrouped: header spans both rows
                    for i in range(col, col + span):
                        head(t.cell(0, i).merge(t.cell(1, i)), b.columns[i], b.align[i])
                else:
                    merged = t.cell(0, col).merge(t.cell(0, col + span - 1))
                    head(merged, label, "center")
                    _cell_borders(merged, bottom=(GOLD, 6))
                    for i in range(col, col + span):
                        head(t.cell(1, i), b.columns[i], b.align[i])
                col += span
        else:
            for i, text in enumerate(b.columns):
                head(t.cell(0, i), text, b.align[i])
        for r in range(n_head):
            tr = t.rows[r]._tr
            _child(tr.get_or_add_trPr(), "w:tblHeader", ("w:tblHeader",))   # repeat on each page
            for tc in tr.tc_lst:                     # every physical cell, merged or not
                _child(tc.get_or_add_tcPr(), "w:shd", _TCPR_ORDER, val="clear", color="auto", fill=NAVY)

        for r, values in enumerate(b.rows):
            row = t.rows[n_head + r]
            for i, value in enumerate(values):
                cell = row.cells[i]
                self.cell_text(cell, value, size=8, align=b.align[i])
                if r % 2 == 1:
                    _shade(cell, ZEBRA)
        if b.total:
            row = t.rows[-1]
            for i, value in enumerate(b.total):
                cell = row.cells[i]
                self.cell_text(cell, value, size=8, bold=True, align=b.align[i])
                _shade(cell, TOTAL_BG)
                _cell_borders(cell, top=(NAVY, 8))
        for i, row in enumerate(t.rows):
            _child(row._tr.get_or_add_trPr(), "w:cantSplit", ("w:cantSplit",))
            if i < len(t.rows) - 1:              # Word's way to keep a table on one page
                for tc in row._tr.tc_lst:
                    for p in tc.iter(qn("w:p")):
                        _child(p.get_or_add_pPr(), "w:keepNext", _PPR_ORDER)
        if b.note:
            p = self.paragraph()
            _tight(p, before=4, after=6, line=1.1)
            _font(p.add_run(b.note), size=7.5, italic=True, colour=INK_SOFT)
        else:
            self.spacer()

    def callout(self, b: c.Callout) -> None:
        bar, label_colour, tint = LEVEL_COLOURS.get(b.level, LEVEL_COLOURS["info"])
        t = self.table(1, [TEXT_W])
        cell = t.cell(0, 0)
        _shade(cell, tint)
        _cell_borders(cell, left=(bar, 36))
        _cell_margins(cell, top=110, bottom=130, left=200, right=200)
        p = cell.paragraphs[0]
        _tight(p, after=1)
        _font(p.add_run(b.label.upper()), size=7, bold=True, colour=label_colour, spacing=0.6)
        p = cell.add_paragraph()
        _tight(p, after=2)
        _font(p.add_run(b.title), size=10, bold=True, colour=INK)
        p = cell.add_paragraph()
        _tight(p, line=1.15)
        _font(p.add_run(b.text), size=9, colour=INK)
        if b.source:
            p = cell.add_paragraph()
            _tight(p, before=3)
            _font(p.add_run(f"Source: {b.source}"), size=7.5, italic=True, colour=INK_SOFT)
        self.spacer(5)

    def bullet_list(self, b: c.BulletList) -> None:
        for item in b.items:
            p = self.paragraph(style="List Number" if b.numbered else "List Bullet")
            p.paragraph_format.space_after = Pt(6 if b.numbered else 4)
            if item.title:
                if b.numbered:                       # study name on its own line, as in the PDF
                    _font(p.add_run(item.title), bold=True, colour=NAVY)
                    p.add_run().add_break()
                else:
                    _font(p.add_run(item.title + " "), bold=True)
            p.add_run(item.text)

    def figure(self, b: c.Figure) -> None:
        p = self.paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.keep_with_next = True
        if b.path is None or not b.size_px:
            _font(p.add_run("This figure could not be produced."), italic=True, colour=INK_SOFT)
        else:
            w_px, h_px = b.size_px
            w_cm, h_cm = FIGURE_W_CM, FIGURE_W_CM * h_px / w_px
            if h_cm > FIGURE_MAX_H_CM:
                w_cm, h_cm = FIGURE_MAX_H_CM * w_px / h_px, FIGURE_MAX_H_CM
            shape = p.add_run().add_picture(str(b.path), width=Cm(w_cm), height=Cm(h_cm))
            shape._inline.docPr.set("descr", f"Figure {b.number}. {b.title}")   # alt text
        cap = self.paragraph(style="Caption")
        _font(cap.add_run(f"Figure {b.number}. "), bold=True)
        cap.add_run(b.caption)

    def cta(self, b: c.Cta) -> None:
        url = b.url_for("docx")
        t = self.table(1, [TEXT_W])
        cell = t.cell(0, 0)
        _shade(cell, NAVY)
        _cell_borders(cell, top=(GOLD, 24))
        _cell_margins(cell, top=320, bottom=340, left=360, right=360)
        p = cell.paragraphs[0]
        _tight(p, after=6)
        _font(p.add_run(b.title), size=15, bold=True, colour=WHITE)
        p = cell.add_paragraph()
        _tight(p, after=12, line=1.2)
        _font(p.add_run(b.text), size=10, colour="E3E9F0")
        p = cell.add_paragraph()
        _tight(p, after=8)
        _hyperlink(p, url, f"   {b.link_text}  »   ", colour=NAVY, size=11, bold=True,
                   underline=False, fill=GOLD)
        p = cell.add_paragraph()
        _tight(p)
        _hyperlink(p, url, b.display_url, colour=GOLD, size=8.5)
        self.spacer()


def render_docx(content: c.ReportContent, path: Path) -> Path:
    """Write the report DOCX for `content` to `path`."""
    path = Path(path)
    doc = Document()
    _setup(doc, content.info)
    r = _Renderer(doc)
    for block in content.blocks:
        if isinstance(block, c.Cover):
            r.cover(block)
        elif isinstance(block, c.Heading):
            r.heading(block)
        elif isinstance(block, c.Paragraph):
            r.text(block)
        elif isinstance(block, c.BulletList):
            r.bullet_list(block)
        elif isinstance(block, c.KeyValueTable):
            r.kv_table(block.rows)
        elif isinstance(block, c.DataTable):
            r.data_table(block)
        elif isinstance(block, c.Callout):
            r.callout(block)
        elif isinstance(block, c.Figure):
            r.figure(block)
        elif isinstance(block, c.PageBreak):
            r.pending_break = True
        elif isinstance(block, c.Cta):
            r.cta(block)
    doc.save(str(path))
    return path
