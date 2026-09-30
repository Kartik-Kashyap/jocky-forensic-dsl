"""Build the SIH 2026 idea-submission deck for JOCKY.

Starts from the official `SIH2026-IDEA-Presentation-Format.pptx` so the
mandated header, footer, slide numbers and logos survive untouched, then draws
the content as native PowerPoint shapes, tables and charts. Everything stays
editable in PowerPoint — nothing is a flat image except the console screenshot.

    python deck/build_deck.py
"""

import json
import os

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION, XL_TICK_MARK
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
from pptx.oxml import parse_xml
from pptx.oxml.ns import nsdecls, qn
from pptx.util import Emu, Inches, Pt

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TEMPLATE = os.path.join(ROOT, "SIH2026-IDEA-Presentation-Format.pptx")
OUT = os.path.join(HERE, "SIH2026-JOCKY-Presentation.pptx")
ASSETS = os.path.join(HERE, "assets")

# ---------------------------------------------------------------------------
# palette — mirrors the console so the deck and the tool look like one product
# ---------------------------------------------------------------------------
NAVY    = RGBColor(0x14, 0x2B, 0x4A)
BLUE    = RGBColor(0x2E, 0x75, 0xB6)
BLUE_D  = RGBColor(0x1F, 0x4E, 0x79)
SKY     = RGBColor(0x4D, 0xA3, 0xFF)
LIGHT   = RGBColor(0xEE, 0xF4, 0xFB)
BORDER  = RGBColor(0xB4, 0xCD, 0xE6)
INK     = RGBColor(0x1A, 0x1A, 0x1A)
MUTE    = RGBColor(0x53, 0x64, 0x74)
WHITE   = RGBColor(0xFF, 0xFF, 0xFF)
GREEN   = RGBColor(0x2E, 0x7D, 0x32)
GREEN_L = RGBColor(0xE3, 0xF2, 0xE4)
TEAL_L  = RGBColor(0xE4, 0xF2, 0xF1)
AMBER   = RGBColor(0xB2, 0x6A, 0x00)
AMBER_L = RGBColor(0xFD, 0xF1, 0xDF)
RED     = RGBColor(0xB3, 0x26, 0x1E)
RED_L   = RGBColor(0xFB, 0xE9, 0xE7)
PURPLE  = RGBColor(0x6A, 0x4C, 0x93)
PURPLE_L = RGBColor(0xEF, 0xEA, 0xF7)
TEAL    = RGBColor(0x00, 0x6A, 0x6A)
GREY_L  = RGBColor(0xF4, 0xF6, 0xF8)
FAINT   = RGBColor(0x7A, 0x8A, 0x99)
CODE_BG = RGBColor(0x0D, 0x11, 0x17)

BODY = "Calibri"
MONO = "Consolas"

# ---------------------------------------------------------------------------
# vertical grid (inches) — title band, two content rows, footnote strip
# ---------------------------------------------------------------------------
TOP  = 1.00            # first content row top
R1H  = 2.52            # first row height   -> ends 3.52
R2Y  = 3.66            # second row top
R2H  = 2.94            # second row height  -> ends 6.60
NOTE = 6.64            # provenance footnote strip
LEFT = 0.30
FULL = 12.73           # LEFT .. 13.03


# ---------------------------------------------------------------------------
# primitives
# ---------------------------------------------------------------------------

def no_bullet(p):
    pPr = p._p.get_or_add_pPr()
    for tag in ("a:buChar", "a:buAutoNum", "a:buNone"):
        for e in pPr.findall(qn(tag)):
            pPr.remove(e)
    pPr.append(parse_xml(f"<a:buNone {nsdecls('a')}/>"))
    pPr.set("marL", "0")
    pPr.set("indent", "0")


def rect(slide, x, y, w, h, fill=None, line=None, lw=0.75,
         shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.06):
    s = slide.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w),
                               Inches(h))
    if shape == MSO_SHAPE.ROUNDED_RECTANGLE:
        try:
            s.adjustments[0] = radius
        except (IndexError, ValueError):
            pass
    if fill is None:
        s.fill.background()
    else:
        s.fill.solid()
        s.fill.fore_color.rgb = fill
    if line is None:
        s.line.fill.background()
    else:
        s.line.color.rgb = line
        s.line.width = Pt(lw)
    s.shadow.inherit = False
    s.text_frame.word_wrap = True
    return s


def txt(slide, x, y, w, h, paras, anchor=MSO_ANCHOR.TOP, align=PP_ALIGN.LEFT,
        margins=(0.05, 0.05, 0.02, 0.02)):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.auto_size = MSO_AUTO_SIZE.NONE
    tf.vertical_anchor = anchor
    tf.margin_left, tf.margin_right = Inches(margins[0]), Inches(margins[1])
    tf.margin_top, tf.margin_bottom = Inches(margins[2]), Inches(margins[3])

    for i, spec in enumerate(paras):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = spec.get("align", align)
        if spec.get("space_after") is not None:
            p.space_after = Pt(spec["space_after"])
        if spec.get("space_before") is not None:
            p.space_before = Pt(spec["space_before"])
        if spec.get("line") is not None:
            p.line_spacing = spec["line"]
        for text, opt in spec["runs"]:
            r = p.add_run()
            r.text = text
            f = r.font
            f.name = opt.get("font", BODY)
            f.size = Pt(opt.get("size", spec.get("size", 9)))
            f.bold = opt.get("bold", False)
            f.italic = opt.get("italic", False)
            f.color.rgb = opt.get("color", INK)
    return tb


def panel(slide, x, y, w, h, title, accent=BLUE, fill=LIGHT, title_size=10.0):
    """A titled card. Returns the y where the body may start."""
    rect(slide, x, y, w, h, fill=fill, line=BORDER, lw=0.75)
    rect(slide, x, y, w, 0.30, fill=accent, line=None, radius=0.16)
    txt(slide, x + 0.10, y + 0.015, w - 0.20, 0.27,
        [{"runs": [(title, {"bold": True, "size": title_size, "color": WHITE})]}],
        anchor=MSO_ANCHOR.MIDDLE, margins=(0.0, 0.0, 0.0, 0.0))
    return y + 0.36


def bullets(slide, x, y, w, h, items, size=8.6, gap=4, marker="▪",
            mcolor=None, lead_color=NAVY):
    """items: list of (lead, rest) — lead is bolded."""
    paras = []
    for lead, rest in items:
        runs = [(f"{marker}  ", {"size": size, "color": mcolor or BLUE,
                                 "bold": True})]
        if lead:
            runs.append((lead, {"size": size, "bold": True,
                                "color": lead_color}))
        if rest:
            runs.append((rest, {"size": size, "color": INK}))
        paras.append({"runs": runs, "space_after": gap, "line": 0.96})
    txt(slide, x, y, w, h, paras)


def chip(slide, x, y, w, h, big, small, accent=BLUE, fill=WHITE):
    rect(slide, x, y, w, h, fill=fill, line=accent, lw=1.0)
    txt(slide, x + 0.05, y + 0.04, w - 0.10, h - 0.08,
        [{"runs": [(big, {"bold": True, "size": 12, "color": accent})],
          "align": PP_ALIGN.CENTER, "space_after": 1},
         {"runs": [(small, {"size": 7.2, "color": MUTE})],
          "align": PP_ALIGN.CENTER, "line": 0.9}],
        anchor=MSO_ANCHOR.MIDDLE, margins=(0.02, 0.02, 0.0, 0.0))


def flow(slide, x, y, w, h, label, sub, fill=WHITE, edge=BLUE, tcolor=NAVY,
         size=8.2, sub_size=6.8):
    rect(slide, x, y, w, h, fill=fill, line=edge, lw=1.0)
    txt(slide, x + 0.04, y + 0.03, w - 0.08, h - 0.06,
        [{"runs": [(label, {"bold": True, "size": size, "color": tcolor})],
          "align": PP_ALIGN.CENTER, "space_after": 0},
         {"runs": [(sub, {"size": sub_size, "color": MUTE})],
          "align": PP_ALIGN.CENTER, "line": 0.88}],
        anchor=MSO_ANCHOR.MIDDLE, margins=(0.02, 0.02, 0.0, 0.0))


def arrow(slide, x, y, w, h, color=BLUE, direction="right"):
    shp = {"right": MSO_SHAPE.RIGHT_ARROW,
           "down": MSO_SHAPE.DOWN_ARROW,
           "left": MSO_SHAPE.LEFT_ARROW}[direction]
    if direction == "down" and w > h:          # keep the head square
        x, y, w, h = x + (w - h) / 2, y, h, h
    rect(slide, x, y, w, h, fill=color, line=None, shape=shp)


def serpentine(slide, x, y, cols, rows, cw, ch, gx, gy, items,
               edge=BLUE, top_fill=BLUE, label_size=8.2, sub_size=6.4,
               arrow_color=SKY, badge=None, label_in_header=False):
    """Lay items out boustrophedon so the flow never jumps backwards.

    Row 0 reads left→right, the wrap goes straight down the last column, and
    row 1 reads right→left. Items arrive in narrative order.
    """
    slots = []
    for r in range(rows):
        order = range(cols) if r % 2 == 0 else range(cols - 1, -1, -1)
        for c in order:
            slots.append((c, r))

    pos = {}
    for i, (label, sub) in enumerate(items):
        c, r = slots[i]
        px = x + c * (cw + gx)
        py = y + r * (ch + gy)
        pos[i] = (px, py)
        rect(slide, px, py, cw, ch, fill=WHITE, line=BORDER, lw=0.75)
        if badge:
            rect(slide, px, py, cw, 0.16, fill=top_fill, line=None, radius=0.34)
            txt(slide, px, py - 0.005, cw, 0.17,
                [{"runs": [(badge(i + 1), {"bold": True, "size": 6.0,
                                           "color": WHITE})],
                  "align": PP_ALIGN.CENTER}], anchor=MSO_ANCHOR.MIDDLE,
                margins=(0, 0, 0, 0))
            txt(slide, px + 0.04, py + 0.17, cw - 0.08, ch - 0.20,
                [{"runs": [(label, {"bold": True, "size": label_size,
                                    "color": NAVY})],
                  "align": PP_ALIGN.CENTER, "space_after": 1},
                 {"runs": [(sub, {"size": sub_size, "color": MUTE})],
                  "align": PP_ALIGN.CENTER, "line": 0.88}],
                margins=(0.01, 0.01, 0.0, 0.0))
        elif label_in_header:
            # the caller draws its own coloured header bar carrying the name,
            # so the body only shows the supporting line
            txt(slide, px + 0.04, py + 0.16, cw - 0.08, ch - 0.20,
                [{"runs": [(sub, {"size": sub_size, "color": INK})],
                  "align": PP_ALIGN.CENTER, "line": 0.88}],
                anchor=MSO_ANCHOR.MIDDLE, margins=(0.02, 0.02, 0.0, 0.0))
        else:
            txt(slide, px + 0.04, py + 0.04, cw - 0.08, ch - 0.08,
                [{"runs": [(label, {"bold": True, "size": label_size,
                                    "color": NAVY})],
                  "align": PP_ALIGN.CENTER, "space_after": 1},
                 {"runs": [(sub, {"size": sub_size, "color": MUTE})],
                  "align": PP_ALIGN.CENTER, "line": 0.88}],
                anchor=MSO_ANCHOR.MIDDLE, margins=(0.02, 0.02, 0.0, 0.0))

    # connectors
    for i in range(len(items) - 1):
        px, py = pos[i]
        nx, ny = pos[i + 1]
        if abs(py - ny) < 0.01:                      # same row: horizontal
            if nx > px:
                arrow(slide, px + cw + 0.012, py + ch / 2 - 0.042,
                      gx - 0.024, 0.085, color=arrow_color)
            else:
                arrow(slide, nx + cw + 0.012, py + ch / 2 - 0.042,
                      gx - 0.024, 0.085, color=arrow_color)
        else:                                        # wrap: straight down
            arrow(slide, px + cw / 2 - 0.055, py + ch + 0.015, 0.11,
                  gy - 0.03, color=arrow_color, direction="down")


def table(slide, x, y, w, headers, rows, widths, row_h=0.26, head_h=0.28,
          head_fill=BLUE_D, size=8.0, head_size=8.4, zebra=True,
          first_bold=True):
    """A native PowerPoint table — restyleable in place."""
    shape = slide.shapes.add_table(len(rows) + 1, len(headers),
                                   Inches(x), Inches(y), Inches(w),
                                   Inches(head_h + row_h * len(rows)))
    tbl = shape.table
    tbl.first_row = True
    tbl.horz_banding = False

    total = sum(widths)
    for i, cw in enumerate(widths):
        tbl.columns[i].width = Emu(int(Inches(w) * cw / total))
    tbl.rows[0].height = Inches(head_h)
    for r in range(1, len(rows) + 1):
        tbl.rows[r].height = Inches(row_h)

    def style(cell, text, *, bold=False, fsize=size, color=INK, fill=None):
        if fill is not None:
            cell.fill.solid()
            cell.fill.fore_color.rgb = fill
        else:
            cell.fill.background()
        cell.margin_left = Inches(0.05)
        cell.margin_right = Inches(0.04)
        cell.margin_top = Inches(0.01)
        cell.margin_bottom = Inches(0.01)
        cell.vertical_anchor = MSO_ANCHOR.MIDDLE
        tf = cell.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.alignment = PP_ALIGN.LEFT
        p.space_after = Pt(0)
        p.line_spacing = 0.94
        r = p.add_run()
        r.text = text
        r.font.name = BODY
        r.font.size = Pt(fsize)
        r.font.bold = bold
        r.font.color.rgb = color

    for i, htext in enumerate(headers):
        style(tbl.cell(0, i), htext, bold=True, fsize=head_size, color=WHITE,
              fill=head_fill)
    for ri, row in enumerate(rows):
        bg = WHITE if (ri % 2 == 0 or not zebra) else GREY_L
        for ci, val in enumerate(row):
            style(tbl.cell(ri + 1, ci), val,
                  bold=(first_bold and ci == 0), fill=bg)
    return tbl


def bar_chart(slide, x, y, w, h, categories, series, colors=(BLUE,),
              number_format='#,##0', font=7.5, gap=70):
    cd = CategoryChartData()
    cd.categories = categories
    for name, values in series:
        cd.add_series(name, values)
    gf = slide.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED,
                                Inches(x), Inches(y), Inches(w), Inches(h), cd)
    ch = gf.chart
    ch.has_legend = False
    ch.font.size = Pt(font)
    ch.font.name = BODY
    ch.has_title = False

    plot = ch.plots[0]
    plot.gap_width = gap
    plot.has_data_labels = True
    dl = plot.data_labels
    dl.number_format = number_format
    dl.number_format_is_linked = False
    dl.font.size = Pt(font - 0.5)
    dl.font.bold = True
    dl.font.color.rgb = NAVY
    dl.font.name = BODY

    va = ch.value_axis
    va.has_major_gridlines = True
    va.major_gridlines.format.line.color.rgb = RGBColor(0xDD, 0xE4, 0xEC)
    va.tick_labels.font.size = Pt(font)
    va.tick_labels.number_format = number_format
    va.tick_labels.number_format_is_linked = False

    ca = ch.category_axis
    ca.tick_labels.font.size = Pt(font)
    ca.major_tick_mark = XL_TICK_MARK.NONE

    for i, s in enumerate(ch.series):
        s.format.fill.solid()
        s.format.fill.fore_color.rgb = colors[i % len(colors)]
    return ch


# ---------------------------------------------------------------------------
# slide furniture
# ---------------------------------------------------------------------------

PTR = {
    2: "Detailed explanation of the proposed solution  ·  How it "
       "addresses the problem  ·  Innovation and uniqueness of the solution",
    3: "Technologies to be used (languages, frameworks, hardware)  ·  "
       "Methodology and process for implementation",
    4: "Analysis of the feasibility of the idea  ·  Potential challenges "
       "and risks  ·  Strategies for overcoming these challenges",
    5: "Potential impact on the target audience  ·  Benefits of the "
       "solution (social, economic, industry)",
    6: "Details / links of the reference and research work",
}


def dress(slide, number, title, subtitle=None, title_top=0.30):
    """Own the template's chrome: title, guidance note, team name, footer."""
    for sh in slide.shapes:
        if sh.name.startswith("Title"):
            tf = sh.text_frame
            tf.word_wrap = True
            tf.auto_size = MSO_AUTO_SIZE.NONE
            tf.vertical_anchor = MSO_ANCHOR.TOP
            # the template's placeholder carries insets that push a two-line
            # title into the content band; zero them and place it ourselves
            tf.margin_left = tf.margin_top = tf.margin_bottom = Inches(0.0)
            p = tf.paragraphs[0]
            for r in list(p.runs):
                r._r.getparent().remove(r._r)
            # the template seeds these paragraphs with soft line breaks
            # (<a:br/>); left in place an empty first line is rendered and
            # shoves the text down out of its band
            for br in p._p.findall(qn("a:br")):
                p._p.remove(br)
            r = p.add_run()
            r.text = title
            r.font.size = Pt(28 if subtitle else 26)
            r.font.bold = True
            r.font.color.rgb = NAVY
            r.font.name = BODY
            if subtitle:
                p2 = tf.add_paragraph()
                p2.space_before = Pt(1)
                r2 = p2.add_run()
                r2.text = subtitle
                r2.font.size = Pt(10.5)
                r2.font.bold = False
                r2.font.color.rgb = BLUE
                r2.font.name = BODY
            sh.left, sh.top = Inches(0.35), Inches(title_top)
            sh.width = Inches(13.0)
            sh.height = Inches(0.62 if subtitle else 0.42)

        elif sh.name == "TextBox 8":                 # the guidance box
            tf = sh.text_frame
            tf.word_wrap = True
            tf.auto_size = MSO_AUTO_SIZE.NONE
            for p in tf.paragraphs:
                for r in p.runs:
                    r.font.size = Pt(6.0)
                    r.font.italic = True
                    r.font.color.rgb = FAINT
                    r.font.name = BODY
                p.space_after = Pt(0)
                p.line_spacing = 0.9
            # starts clear of the team-name oval, ends clear of the SIH logo
            sh.left, sh.top = Inches(1.80), Inches(0.845)
            sh.width, sh.height = Inches(8.65), Inches(0.16)

        elif sh.has_text_frame and "Team Name" in sh.text_frame.text:
            sh.fill.solid()
            sh.fill.fore_color.rgb = NAVY
            sh.line.color.rgb = NAVY
            tf = sh.text_frame
            p = tf.paragraphs[0]
            for r in list(p.runs):
                r._r.getparent().remove(r._r)
            # the template seeds these paragraphs with soft line breaks
            # (<a:br/>); left in place an empty first line is rendered and
            # shoves the text down out of its band
            for br in p._p.findall(qn("a:br")):
                p._p.remove(br)
            r = p.add_run()
            r.text = "Data_Drishti"
            r.font.size = Pt(9)
            r.font.bold = True
            r.font.color.rgb = WHITE
            r.font.name = BODY

        elif sh.has_text_frame and "SIH Idea submission" in sh.text_frame.text:
            tf = sh.text_frame
            p = tf.paragraphs[0]
            for r in list(p.runs):
                r._r.getparent().remove(r._r)
            # the template seeds these paragraphs with soft line breaks
            # (<a:br/>); left in place an empty first line is rendered and
            # shoves the text down out of its band
            for br in p._p.findall(qn("a:br")):
                p._p.remove(br)
            r = p.add_run()
            r.text = "@SIH Idea submission – PPT – Team Data_Drishti"
            r.font.size = Pt(9)
            r.font.color.rgb = WHITE
            r.font.name = BODY


def pointers(slide, number):
    """Render the template's mandated pointers as one quiet line."""
    for sh in slide.shapes:
        if sh.name == "TextBox 8":
            tf = sh.text_frame
            for i, p in enumerate(tf.paragraphs):
                for r in list(p.runs):
                    r._r.getparent().remove(r._r)
            p = tf.paragraphs[0]
            r = p.add_run()
            r.text = PTR[number]
            r.font.size = Pt(6.0)
            r.font.italic = True
            r.font.color.rgb = FAINT
            r.font.name = BODY
            for extra in list(tf.paragraphs)[1:]:
                extra._p.getparent().remove(extra._p)


def source_note(slide, text, x=LEFT, y=NOTE, w=FULL):
    txt(slide, x, y, w, 0.20,
        [{"runs": [(text, {"size": 6.2, "italic": True, "color": FAINT})],
          "line": 0.9}], margins=(0.0, 0.0, 0.0, 0.0))


# ===========================================================================
# SLIDE 1 — title page
# ===========================================================================

def slide1(prs, s):
    fields = [
        ("Problem Statement ID:  ", "⟨ fill from portal ⟩", True),
        ("Problem Statement Title:  ",
         "Creation of scripts/functions with a new programming language to "
         "commence computer & network forensic analysis without triggering "
         "security solutions", False),
        ("Theme:  ", "Blockchain & Cybersecurity", False),
        ("PS Category:  ", "Software", False),
        ("Team ID:  ", "148458  ⟨ verify ⟩", True),
        ("Team Name (Registered on portal):  ", "Data_Drishti", False),
    ]

    for sh in s.shapes:
        # the template's Title placeholder carries a second "TITLE PAGE" line
        if sh.has_text_frame:
            for p in list(sh.text_frame.paragraphs):
                if p.text.strip().upper() == "TITLE PAGE":
                    p._p.getparent().remove(p._p)

        if sh.name == "TextBox 9":
            tf = sh.text_frame
            tf.word_wrap = True
            tf.auto_size = MSO_AUTO_SIZE.NONE
            for p in list(tf.paragraphs):
                for r in list(p.runs):
                    r._r.getparent().remove(r._r)
            for i, (label, value, flag) in enumerate(fields):
                p = tf.paragraphs[i]
                no_bullet(p)
                p.line_spacing = 1.0
                p.space_after = Pt(8)
                r = p.add_run(); r.text = label
                r.font.bold = True; r.font.size = Pt(13.5); r.font.name = BODY
                r.font.color.rgb = NAVY
                r2 = p.add_run(); r2.text = value
                r2.font.size = Pt(13 if not flag else 13.5)
                r2.font.name = BODY
                r2.font.color.rgb = RGBColor(0xC0, 0x39, 0x2B) if flag else INK
            sh.left, sh.top = Inches(0.36), Inches(2.10)
            sh.width, sh.height = Inches(6.70), Inches(4.30)

        elif sh.name.startswith("Subtitle"):
            tf = sh.text_frame
            tf.word_wrap = True
            tf.auto_size = MSO_AUTO_SIZE.NONE
            p = tf.paragraphs[0]
            for r in list(p.runs):
                r._r.getparent().remove(r._r)
            # the template seeds these paragraphs with soft line breaks
            # (<a:br/>); left in place an empty first line is rendered and
            # shoves the text down out of its band
            for br in p._p.findall(qn("a:br")):
                p._p.remove(br)
            r = p.add_run()
            r.text = "JOCKY — a forensic scripting language for computer "\
                     "& network analysis"
            r.font.size = Pt(14); r.font.bold = True
            r.font.color.rgb = BLUE_D; r.font.name = BODY
            sh.left, sh.top = Inches(0.36), Inches(1.42)
            sh.width, sh.height = Inches(9.33), Inches(0.55)


# ===========================================================================
# SLIDE 2 — idea title
# ===========================================================================

def slide2(prs, s):
    dress(s, 2, "JOCKY",
          "one language for host and network forensics — analyse in "
          "place, cite every finding, prove the chain of custody",
          title_top=0.05)
    pointers(s, 2)

    # -- left: the console + the UVP --------------------------------------
    shot = os.path.join(ASSETS, "console-investigate.png")
    if os.path.exists(shot):
        s.shapes.add_picture(shot, Inches(LEFT), Inches(TOP), width=Inches(3.30))
    rect(s, LEFT, 3.07, 3.30, 0.24, fill=NAVY, line=None, radius=0.20)
    txt(s, LEFT + 0.05, 3.08, 3.20, 0.22,
        [{"runs": [("Operator console — findings cite the query that "
                    "produced them", {"size": 7, "bold": True, "color": WHITE})],
          "align": PP_ALIGN.CENTER}], anchor=MSO_ANCHOR.MIDDLE,
        margins=(0, 0, 0, 0))

    by = panel(s, LEFT, 3.38, 3.30, 3.22, "INNOVATION & UNIQUENESS (UVP)",
               accent=PURPLE, fill=PURPLE_L, title_size=9.5)
    bullets(s, LEFT + 0.10, by, 3.10, 2.80, [
        ("Findings cannot be uncited. ", "A finding must name the result set "
         "that raised it — provenance is enforced by the grammar, not by "
         "examiner discipline."),
        ("Offline and dependency-free. ", "Pure Python standard library. Runs "
         "on an air-gapped examiner workstation with nothing installed."),
        ("Compatible by design, not by stealth. ", "Signed reproducible builds "
         "with published hashes for vendor allowlisting — no kernel "
         "drivers, no injection, no log tampering."),
        ("Judge-independent. ", "Deterministic execution: the same script over "
         "the same digests yields the same findings, byte for byte."),
    ], size=8.0, gap=5, mcolor=PURPLE, lead_color=PURPLE)

    # -- middle: problem + solution ---------------------------------------
    py = panel(s, 3.74, TOP, 4.14, R1H, "THE PROBLEM IT TACKLES",
               accent=RED, fill=RED_L, title_size=9.5)
    bullets(s, 3.84, py, 3.94, 2.10, [
        ("Examiners stitch tools together. ", "Volatility, plaso, KAPE, "
         "Chainsaw and throwaway scripts — every hop loses provenance."),
        ("Findings arrive without a citable query. ", "Ad-hoc pipelines produce "
         "results no one can reproduce or defend on the stand."),
        ("Security tooling fights the endpoint. ", "Collection and analysis "
         "trigger AV/EDR, and the industry habit is to weaken the defence "
         "instead of documenting the telemetry."),
        ("The tooling becomes the risk. ", "Anything that hides from endpoint "
         "security is indistinguishable from the intrusion it is meant to "
         "investigate — examiners are asked to trade visibility for "
         "capability."),
    ], size=8.2, gap=5, mcolor=RED, lead_color=RED)

    sy = panel(s, 3.74, R2Y, 4.14, R2H, "PROPOSED SOLUTION", accent=BLUE,
               fill=LIGHT, title_size=9.5)
    bullets(s, 3.84, sy, 3.94, 2.52, [
        ("One language, one evidence model. ", "A pipeline DSL — "
         "source → |> where |> group by |> sort by — over host "
         "events, processes, netflow and CTI feeds alike."),
        ("Every finding is a citation. ", "A finding names the result set and "
         "record count behind it; the run logs source and script digests, so "
         "the report is reproducible."),
        ("Runs with the endpoint, not against it. ", "Read-only evidence "
         "access, loopback-only console, documented telemetry sources, signed "
         "builds — no evasion of any kind."),
        ("Small enough to audit. ", "Roughly 2,000 lines of Python across six "
         "modules with a 50-test suite — an examiner can read the whole "
         "interpreter before deciding to trust it."),
    ], size=8.2, gap=5)

    # -- right: graphical abstract ----------------------------------------
    gx, gw = 8.00, 5.03
    gy = panel(s, gx, TOP, gw, 3.52, "GRAPHICAL ABSTRACT", accent=NAVY,
               fill=WHITE, title_size=9.5)
    steps = [
        ("EVIDENCE", "EVTX · JSON · CSV · netflow · CTI "
                     "feeds — opened read-only, SHA-256 digest taken"),
        ("LEXER", "332 tokens · 11 ms — Windows paths, regex and "
                  "base64 survive verbatim"),
        ("PARSER → AST", "101 nodes · plain nested dicts — "
                              "inspectable and JSON-safe"),
        ("INTERPRETER", "pipeline stages · 14 builtins · entropy, "
                        "hashing, IP classification"),
        ("CORRELATION", "threat-intel match · timeline reconstruction "
                        "· severity assignment"),
        ("REPORT", "findings, each citing the result set that raised it"),
    ]
    sy0, rh = gy + 0.02, 0.475
    for i, (label, sub) in enumerate(steps):
        last = i == len(steps) - 1
        flow(s, gx + 0.42, sy0 + i * rh, gw - 0.84, 0.40, label, sub,
             fill=GREEN_L if last else WHITE,
             edge=GREEN if last else BORDER,
             tcolor=GREEN if last else NAVY, size=8.0, sub_size=6.2)
        if not last:
            arrow(s, gx + gw / 2 - 0.055, sy0 + i * rh + 0.40, 0.11, 0.075,
                  color=BLUE, direction="down")

    rect(s, gx + 0.10, 4.27, gw - 0.20, 0.24, fill=NAVY, line=None,
         radius=0.22)
    txt(s, gx + 0.12, 4.28, gw - 0.24, 0.22,
        [{"runs": [("no kernel drivers  ·  no injection  ·  no "
                    "obfuscation  ·  no log tampering",
                    {"size": 7.2, "bold": True, "color": WHITE})],
          "align": PP_ALIGN.CENTER}], anchor=MSO_ANCHOR.MIDDLE,
        margins=(0, 0, 0, 0))

    ch = [(1.24, "11 ms", "first finding\non 45 records"),
          (1.19, "0", "third-party\ndependencies"),
          (1.24, "6 / 6", "findings cite\ntheir query"),
          (1.24, "127.0.0.1", "console binds\nloopback only")]
    cx = gx
    for w, big, small in ch:
        chip(s, cx, 4.60, w, 0.62, big, small, accent=BLUE)
        cx += w + 0.105

    y = panel(s, gx, 5.28, gw, 1.32, "WHY IT IS DIFFERENT", accent=TEAL,
              fill=TEAL_L, title_size=9.5)
    bullets(s, gx + 0.10, y, gw - 0.20, 0.92, [
        ("Sigma detects, VQL queries — neither makes a finding citable. ",
         "JOCKY's grammar refuses a finding that does not name its source."),
        ("A DSL is a contract. ", "Scripts become reviewable, versionable "
         "artefacts that transfer between examiners and agencies."),
    ], size=7.8, gap=4, mcolor=TEAL, lead_color=TEAL)


# ===========================================================================
# SLIDE 3 — technical approach
# ===========================================================================

def slide3(prs, s):
    dress(s, 3, "TECHNICAL APPROACH")
    pointers(s, 3)

    # -- A: layered architecture ------------------------------------------
    ax, aw = LEFT, 6.05
    ay = panel(s, ax, TOP, aw, R1H, "LAYERED ARCHITECTURE", accent=NAVY)
    layers = [
        ("Presentation", "Operator console — one HTML file, 7 tabs, "
                         "deep-linkable, Ctrl+Enter to run", BLUE),
        ("Service", "serve.py — loopback API (/api/state, /run, /compile), "
                    "client-address check, path-traversal guard", BLUE_D),
        ("Language core", "lexer → parser → interpreter · AST as "
                          "plain nested dicts · 11 ms for a 332-token "
                          "script", PURPLE),
        ("Primitives", "14 builtins — entropy, sha256, md5, is_public_ip, "
                       "age_minutes, regex", TEAL),
        ("Evidence adapters", "JSON · CSV · line-based CTI — "
                              "read-only, digested at open", GREEN),
    ]
    ly = ay + 0.02
    for name, desc, col in layers:
        rect(s, ax + 0.08, ly, aw - 0.16, 0.375, fill=WHITE, line=col, lw=1.0)
        rect(s, ax + 0.08, ly, 0.070, 0.375, fill=col, line=None, radius=0.30)
        txt(s, ax + 0.20, ly + 0.01, 1.26, 0.355,
            [{"runs": [(name, {"bold": True, "size": 8.2, "color": col})],
              "line": 0.88}], anchor=MSO_ANCHOR.MIDDLE,
            margins=(0.0, 0.0, 0.0, 0.0))
        txt(s, ax + 1.48, ly + 0.01, aw - 1.60, 0.355,
            [{"runs": [(desc, {"size": 7.6, "color": INK})], "line": 0.9}],
            anchor=MSO_ANCHOR.MIDDLE, margins=(0.0, 0.0, 0.0, 0.0))
        ly += 0.415

    # -- B: methodology / data flow ---------------------------------------
    bx, bw = 6.48, 6.55
    by = panel(s, bx, TOP, bw, R1H, "METHODOLOGY — DATA FLOW", accent=BLUE,
               fill=LIGHT)
    steps = [
        ("Open & digest", "SHA-256 per file, read-only"),
        ("Tokenise", "strings survive verbatim"),
        ("Parse", "recursive descent → AST"),
        ("Bind", "sources resolved, lint-checked"),
        ("Execute", "pipeline stages, lazy rows"),
        ("Correlate", "CTI match, group, sort"),
        ("Narrate", "timeline on timestamp"),
        ("Report", "findings cite result sets"),
    ]
    serpentine(s, bx + 0.10, by + 0.04, 4, 2, 1.505, 0.78, 0.085, 0.20, steps,
               badge=lambda n: f"STEP {n}", label_size=8.2, sub_size=6.4)
    txt(s, bx + 0.10, 3.20, bw - 0.20, 0.28,
        [{"runs": [("Evidence is never written to; every artefact is digested "
                    "before it is parsed. A script that cites an undeclared "
                    "binding fails `lint` before it ever touches evidence.",
                    {"size": 6.8, "italic": True, "color": MUTE})],
          "line": 0.9}], margins=(0.0, 0.0, 0.0, 0.0))

    # -- C: state machine --------------------------------------------------
    cy2 = panel(s, ax, R2Y, aw, R2H, "STATE MACHINE — ONE SCRIPT RUN",
                accent=PURPLE, fill=PURPLE_L)
    states = [
        ("SOURCE", "evidence declared"), ("LEXED", "tokens"),
        ("PARSED", "AST built"), ("BOUND", "bindings resolved"),
        ("EXECUTING", "stages run"), ("REPORTED", "findings emitted"),
    ]
    sw, shh, sgx, sgy = 1.62, 0.52, 0.215, 0.20
    slots = [(0, 0), (1, 0), (2, 0), (2, 1), (1, 1), (0, 1)]
    pos = {}
    for i, (name, sub) in enumerate(states):
        c, r = slots[i]
        px = ax + 0.20 + c * (sw + sgx)
        py = cy2 + 0.04 + r * (shh + sgy)
        pos[i] = (px, py)
        last = i == len(states) - 1
        rect(s, px, py, sw, shh, fill=GREEN_L if last else WHITE,
             line=GREEN if last else BLUE, lw=1.0)
        txt(s, px + 0.02, py + 0.02, sw - 0.04, shh - 0.04,
            [{"runs": [(name, {"bold": True, "size": 7.6,
                               "color": GREEN if last else NAVY})],
              "align": PP_ALIGN.CENTER, "space_after": 0},
             {"runs": [(sub, {"size": 6.0, "color": MUTE})],
              "align": PP_ALIGN.CENTER, "line": 0.85}],
            anchor=MSO_ANCHOR.MIDDLE, margins=(0.01, 0.01, 0.0, 0.0))
    for i in range(len(states) - 1):
        px, py = pos[i]
        nx, ny = pos[i + 1]
        if abs(py - ny) < 0.01:
            ax0 = px + sw + 0.012 if nx > px else nx + sw + 0.012
            arrow(s, ax0, py + shh / 2 - 0.042, sgx - 0.024, 0.085, color=BLUE)
        else:
            arrow(s, px + sw / 2 - 0.055, py + shh + 0.015, 0.11, sgy - 0.03,
                  color=BLUE, direction="down")

    rect(s, ax + 0.10, 5.42, aw - 0.20, 1.10, fill=WHITE, line=RED, lw=1.0)
    txt(s, ax + 0.16, 5.45, aw - 0.32, 0.18,
        [{"runs": [("REJECTED STATES — a run fails loudly, never silently",
                    {"bold": True, "size": 7.0, "color": RED})]}],
        margins=(0, 0, 0, 0))
    fails = [
        ("SYNTAX ERROR", "line:col with a caret under the offending token"),
        ("UNKNOWN BINDING", "caught by `lint` before evidence is read"),
        ("RUNTIME ERROR", "missing evidence names the path it looked for"),
    ]
    for i, (name, desc) in enumerate(fails):
        fxx = ax + 0.16 + i * 1.93
        rect(s, fxx, 5.66, 1.84, 0.80, fill=RED_L, line=RED, lw=0.75)
        txt(s, fxx + 0.05, 5.68, 1.74, 0.76,
            [{"runs": [(name, {"bold": True, "size": 6.6, "color": RED})],
              "align": PP_ALIGN.CENTER, "space_after": 1},
             {"runs": [(desc, {"size": 6.0, "color": INK})],
              "align": PP_ALIGN.CENTER, "line": 0.88}],
            anchor=MSO_ANCHOR.MIDDLE, margins=(0.01, 0.01, 0.0, 0.0))

    # -- D: tech stack + a real script ------------------------------------
    dy = panel(s, bx, R2Y, bw, R2H, "TECHNOLOGY STACK & LANGUAGE", accent=TEAL,
               fill=TEAL_L)
    stack = ["Python 3.11+", "standard library only", "0 dependencies",
             "ThreadingHTTPServer", "SHA-256 / MD5", "unittest — 50 tests",
             "single-file console", "loopback binding"]
    for i, name in enumerate(stack):
        cx = bx + 0.10 + (i % 4) * 1.565
        cy = dy + 0.02 + (i // 4) * 0.315
        rect(s, cx, cy, 1.49, 0.28, fill=WHITE, line=TEAL, lw=0.75)
        txt(s, cx + 0.03, cy, 1.43, 0.28,
            [{"runs": [(name, {"size": 6.6, "bold": True, "color": TEAL})],
              "align": PP_ALIGN.CENTER}], anchor=MSO_ANCHOR.MIDDLE,
            margins=(0.01, 0.01, 0.0, 0.0))

    rect(s, bx + 0.10, 4.72, bw - 0.20, 1.72, fill=CODE_BG, line=None)
    code = [
        ('case "SIH-2026-014"', "#90CDF4"),
        ('source flows = ingest "evidence/netflow.csv"', "#90CDF4"),
        (None, None),
        ("let beacon = flows", "#C792EA"),
        ('    |> where (direction == "outbound")', "#A5D6A7"),
        ("    |> where (is_public_ip(dst_ip))", "#A5D6A7"),
        ("    |> where (bytes < 2000)", "#A5D6A7"),
        ("    |> group by (dst_ip, dst_port)", "#A5D6A7"),
        ("    |> sort by (count desc)", "#A5D6A7"),
        (None, None),
        ('finding "Beaconing to an external endpoint"', "#FFB86C"),
        ("    severity critical from beacon", "#FFB86C"),
    ]
    paras = []
    for line, colr in code:
        if colr is None:
            paras.append({"runs": [(" ", {"font": MONO, "size": 4.0})],
                          "space_after": 0, "line": 0.85})
        else:
            paras.append({"runs": [(line, {"font": MONO, "size": 7.4,
                                           "color": RGBColor.from_string(
                                               colr.lstrip("#"))})],
                          "space_after": 0, "line": 0.92})
    txt(s, bx + 0.18, 4.76, bw - 0.36, 1.66, paras, margins=(0.0, 0.0, 0.0, 0.0))
    txt(s, bx + 0.18, 6.46, bw - 0.36, 0.18,
        [{"runs": [("Real script from scripts/beacon_hunt.jky — 332 "
                    "tokens, 101 AST nodes, 6 findings, 11 ms.",
                    {"size": 6.2, "italic": True, "color": MUTE})]}],
        margins=(0.0, 0.0, 0.0, 0.0))


# ===========================================================================
# SLIDE 4 — feasibility and viability
# ===========================================================================

def slide4(prs, s):
    dress(s, 4, "FEASIBILITY AND VIABILITY")
    pointers(s, 4)

    with open(os.path.join(HERE, "bench_results.json"), encoding="utf-8") as fh:
        bench = json.load(fh)["scale"]
    with open(os.path.join(HERE, "bench_baseline.json"), encoding="utf-8") as fh:
        base = json.load(fh)["baseline"]

    cats = [f"{r['events'] // 1000}k" if r["events"] >= 1000 else str(r["events"])
            for r in bench]

    # -- chart 1: execution time ------------------------------------------
    c1 = panel(s, LEFT, TOP, 6.05, R1H,
               "EXECUTION TIME SCALES LINEARLY WITH EVIDENCE VOLUME",
               accent=BLUE, fill=LIGHT, title_size=9.5)
    bar_chart(s, LEFT + 0.08, c1 + 0.02, 5.89, 1.74, cats,
              [("Interpreter wall-clock (ms)",
                [r["exec_ms"] for r in bench])],
              colors=(BLUE,), number_format='#,##0', gap=70)
    txt(s, LEFT + 0.12, 3.15, 5.85, 0.34,
        [{"runs": [("One representative investigation — filter, entropy, "
                    "CTI join, group-by, sort, timeline, 3 findings. Lex + "
                    "parse stayed at 2.2–3.1 ms at every size, so script "
                    "cost is independent of data volume.",
                    {"size": 6.4, "italic": True, "color": MUTE})],
          "line": 0.9}], margins=(0.0, 0.0, 0.0, 0.0))

    # -- chart 2: throughput and honest overhead --------------------------
    c2 = panel(s, LEFT, R2Y, 6.05, R2H,
               "THROUGHPUT IS FLAT — THE OVERHEAD IS MEASURED, NOT HIDDEN",
               accent=AMBER, fill=AMBER_L, title_size=9.5)
    bar_chart(s, LEFT + 0.08, c2 + 0.02, 3.30, 1.88, cats,
              [("records / second",
                [r["records_per_sec"] for r in bench])],
              colors=(GREEN,), number_format='#,##0', gap=70)
    bar_chart(s, LEFT + 3.36, c2 + 0.02, 2.61, 1.88, cats,
              [("× vs hand-written Python",
                [b["overhead_x"] for b in base])],
              colors=(AMBER,), number_format='0.0"×"', gap=70)
    txt(s, LEFT + 0.12, 5.95, 5.85, 0.60,
        [{"runs": [("Throughput holds at 5.1k–7.4k records/sec, so cost is "
                    "linear and predictable. The tree-walking interpreter costs "
                    "20–26× the equivalent hand-written Python — "
                    "accepted for an auditable reference implementation, and "
                    "the reason a bytecode VM is the first roadmap item.",
                    {"size": 6.6, "italic": True, "color": MUTE})],
          "line": 0.92}], margins=(0.0, 0.0, 0.0, 0.0))

    # -- measured results --------------------------------------------------
    ry = panel(s, 6.48, TOP, 6.55, R1H, "MEASURED RESULTS", accent=NAVY,
               fill=WHITE, title_size=9.5)
    table(s, 6.56, ry - 0.02, 6.39, ["Measured result", "Value"], [
        ("Lex + parse", "2.2 – 3.1 ms — independent of evidence size"),
        ("Interpreter throughput", "5,079 – 7,363 records / second"),
        ("Peak interpreter memory", "1.9 MB @1k → 188 MB @100k, linear"),
        ("Overhead vs hand-written Python", "20 – 26 ×"),
        ("Result stability across scales", "identical findings at every size"),
        ("Third-party dependencies", "0 — standard library only"),
        ("Automated test suite", "50 tests, all passing"),
    ], [2.35, 4.04], row_h=0.255, head_h=0.28, size=7.4, head_size=7.8,
        head_fill=NAVY)

    # -- risks -------------------------------------------------------------
    ky = panel(s, 6.48, R2Y, 6.55, R2H, "RISKS AND MITIGATION STRATEGY",
               accent=RED, fill=WHITE, title_size=9.5)
    table(s, 6.56, ky - 0.02, 6.39, ["Risk", "Mitigation strategy"], [
        ("Interpreter too slow for full-disk images",
         "Measured and stated, not hidden. Scope scripts to triage sets "
         "(10⁴–10⁵ records) where first-response calls are made; "
         "bytecode VM is the next milestone."),
        ("Examiner over-trusts an automated finding",
         "Severity is authored by the examiner, never inferred. Every finding "
         "cites its result set and record count; the report is reproducible."),
        ("AV/EDR blocks the collector",
         "Not answered with obfuscation: signed reproducible builds with "
         "published hashes for vendor allowlisting, documented telemetry "
         "sources only, read-only access."),
        ("Evidence altered during analysis",
         "Sources opened read-only and SHA-256 digested at open; nothing is "
         "ever written back to a source system."),
        ("Console reachable from the network",
         "Loopback binding plus per-request client-address validation; fleet "
         "mode is opt-in, over TLS with pinned certificates."),
        ("Script path traversal",
         "Resolved path must remain inside scripts/; rejected, and covered by "
         "the test suite."),
    ], [2.05, 4.34], row_h=0.375, head_h=0.28, size=7.0, head_size=7.8,
        head_fill=RED, first_bold=False)

    source_note(s, "All figures measured on the target machine by deck/bench.py "
                   "and deck/bench_baseline.py — see "
                   "deck/bench_results.json. Ratios and throughputs, not "
                   "absolute speeds, are the portable result.")


# ===========================================================================
# SLIDE 5 — impact and benefits
# ===========================================================================

def slide5(prs, s):
    dress(s, 5, "IMPACT AND BENEFITS")
    pointers(s, 5)

    R1B, R1H5 = 4.70, 3.70       # this slide's panels run taller than the grid
    R2Y5, R2H5 = 4.84, 1.76

    # -- TAM / SAM / SOM ---------------------------------------------------
    tx, tw = LEFT, 4.35
    ty = panel(s, tx, TOP, tw, R1H5, "ADDRESSABLE IMPACT", accent=BLUE,
               fill=LIGHT, title_size=9.5)
    cx0, cy0 = tx + 1.48, ty + 1.06
    for r, col in ((1.14, GREEN), (0.76, BLUE), (0.40, NAVY)):
        rect(s, cx0 - r, cy0 - r, r * 2, r * 2, fill=None, line=col, lw=1.4,
             shape=MSO_SHAPE.OVAL)
    for name, dy, col in (("TAM", -0.94, GREEN), ("SAM", -0.58, BLUE),
                          ("SOM", -0.24, NAVY)):
        txt(s, cx0 - 0.60, cy0 + dy, 1.20, 0.22,
            [{"runs": [(name, {"bold": True, "size": 9, "color": col})],
              "align": PP_ALIGN.CENTER}], anchor=MSO_ANCHOR.MIDDLE,
            margins=(0, 0, 0, 0))

    rows = [
        ("TAM", "Global DFIR", "Every organisation that must investigate a "
         "breach or hold evidence. Software + services.",
         "~US$10–16 B by 2030", GREEN),
        ("SAM", "Indian obligation-holders", "Cyber cells, CERT-In empanelled "
         "auditors, MSSPs and university labs with a legal duty to handle "
         "evidence.", "~US$0.3–0.5 B", BLUE),
        ("SOM", "Budget-constrained labs", "District cyber cells and university "
         "forensic labs on air-gapped workstations, where a free offline tool "
         "wins on day one.", "~US$20–40 M", NAVY),
    ]
    ly = 3.28
    for name, sub, desc, size, col in rows:
        rect(s, tx + 0.10, ly, tw - 0.20, 0.40, fill=WHITE, line=col, lw=0.9)
        txt(s, tx + 0.16, ly + 0.01, 0.86, 0.38,
            [{"runs": [(name, {"bold": True, "size": 8.2, "color": col})],
              "space_after": 0},
             {"runs": [(size, {"size": 6.0, "bold": True, "color": MUTE})],
              "line": 0.85}], anchor=MSO_ANCHOR.MIDDLE, margins=(0, 0, 0, 0))
        txt(s, tx + 1.06, ly + 0.01, tw - 1.18, 0.38,
            [{"runs": [(sub + " — ", {"bold": True, "size": 6.7,
                                           "color": col}),
                       (desc, {"size": 6.4, "color": INK})], "line": 0.86}],
            anchor=MSO_ANCHOR.MIDDLE, margins=(0, 0, 0, 0))
        ly += 0.44

    # -- SWOT --------------------------------------------------------------
    wx, ww = 4.78, 4.05
    wy = panel(s, wx, TOP, ww, R1H5, "SWOT ANALYSIS", accent=PURPLE,
               fill=WHITE, title_size=9.5)
    quads = [
        ("S", "STRENGTHS", GREEN, GREEN_L, [
            "Zero dependencies — runs offline, air-gapped",
            "Findings are citable by grammar, not by habit",
            "50 unit tests; deterministic, reproducible runs",
            "Loopback-only console, read-only evidence access",
        ]),
        ("W", "WEAKNESSES", RED, RED_L, [
            "Tree-walking interpreter: ~6k records/sec (measured)",
            "14 builtins — no EVTX / USN / MFT adapter yet",
            "Single-host console; no central case management",
            "Correlation is signature-based, not behavioural",
        ]),
        ("O", "OPPORTUNITIES", BLUE, LIGHT, [
            "DPDP Act 2023 and CERT-In norms create evidence-handling duties",
            "Sigma / ATT&CK mapping is a natural next layer",
            "University curricula need a teachable forensic language",
            "Edge and IoT forensics need small, offline tooling",
        ]),
        ("T", "THREATS", AMBER, AMBER_L, [
            "Commercial suites bundled into lab contracts",
            "Free incumbents (plaso, Hayabusa, Velociraptor) already trusted",
            "Language adoption is slow without a script-sharing community",
            "Evidence formats change with every OS release",
        ]),
    ]
    qw, qh = 1.945, 1.55
    for i, (letter, name, col, fill, items) in enumerate(quads):
        qx = wx + 0.07 + (i % 2) * (qw + 0.09)
        qy = wy + 0.02 + (i // 2) * (qh + 0.10)
        rect(s, qx, qy, qw, qh, fill=fill, line=col, lw=1.0)
        rect(s, qx, qy, qw, 0.20, fill=col, line=None, radius=0.30)
        txt(s, qx, qy - 0.005, qw, 0.21,
            [{"runs": [(letter + "  ·  " + name,
                        {"bold": True, "size": 7.2, "color": WHITE})],
              "align": PP_ALIGN.CENTER}], anchor=MSO_ANCHOR.MIDDLE,
            margins=(0, 0, 0, 0))
        bullets(s, qx + 0.06, qy + 0.24, qw - 0.12, qh - 0.28,
                [(None, t) for t in items], size=6.4, gap=2.4, marker="▪",
                mcolor=col, lead_color=col)

    # -- impact ------------------------------------------------------------
    ix, iw = 8.98, 4.05
    iy = panel(s, ix, TOP, iw, R1H5, "IMPACT", accent=TEAL, fill=TEAL_L,
               title_size=9.5)
    points = [
        ("SOCIAL", TEAL,
         "A small cyber cell can defend its conclusion in court, and a citizen "
         "whose device was seized can see the reasoning behind the finding. "
         "Forensic conclusions stop being an expert's private judgement."),
        ("ECONOMIC", GREEN,
         "Removes a paid-tool dependency for labs that cannot license "
         "commercial DFIR suites, and removes re-work: one reviewable, cited "
         "script replaces a chain of throwaway scripts re-validated per case."),
        ("INDUSTRY", BLUE,
         "Gives DFIR a shared, versionable language. Investigation scripts "
         "become portable artefacts that can be peer-reviewed and exchanged "
         "between agencies — what Sigma did for detection rules."),
    ]
    py2 = iy + 0.02
    for name, col, body in points:
        rect(s, ix + 0.09, py2, iw - 0.18, 1.06, fill=WHITE, line=col, lw=0.9)
        rect(s, ix + 0.09, py2, 0.065, 1.06, fill=col, line=None, radius=0.4)
        txt(s, ix + 0.21, py2 + 0.05, iw - 0.34, 0.98,
            [{"runs": [(name, {"bold": True, "size": 7.8, "color": col})],
              "space_after": 2},
             {"runs": [(body, {"size": 7.2, "color": INK})], "line": 0.94}],
            margins=(0.0, 0.0, 0.0, 0.0))
        py2 += 1.12

    # -- who this reaches + at a glance -----------------------------------
    y = panel(s, LEFT, R2Y5, 8.35, R2H5, "WHO THIS REACHES FIRST",
              accent=NAVY, fill=WHITE, title_size=9.5)
    bullets(s, LEFT + 0.10, y, 8.15, 1.36, [
        ("District cyber cells and state CID units. ",
         "Small teams, mixed caseloads, no budget for per-seat commercial "
         "licences — and a legal duty to document what they did."),
        ("CERT-In empanelled auditors and MSSPs. ",
         "Repeatable scripts turn a per-engagement method into a reviewable, "
         "transferable asset."),
        ("University and police forensic labs. ",
         "An air-gapped workstation is the normal environment, not the "
         "exception — and a readable language is teachable."),
        ("The examiner herself. ",
         "The console shows the query behind every finding, so a conclusion "
         "can be checked rather than taken on trust."),
    ], size=7.6, gap=3.5)

    ay2 = panel(s, 8.98, R2Y5, 4.05, R2H5, "AT A GLANCE", accent=BLUE,
                fill=LIGHT, title_size=9.5)
    bullets(s, 8.98 + 0.10, ay2, 3.85, 1.36, [
        ("0", " — licence cost per seat; nothing to renew."),
        ("Air-gapped", " — no network calls; the console binds loopback."),
        ("Cited", " — every finding names the query that raised it."),
        ("Read-only", " — evidence is digested at open, never modified."),
    ], size=7.6, gap=4)

    source_note(s, "Sizing is a top-down estimate from published DFIR market "
                   "analyses, not a vendor forecast; the method and assumptions "
                   "are recorded in the repository README.")


# ===========================================================================
# SLIDE 6 — research and references
# ===========================================================================

def slide6(prs, s):
    dress(s, 6, "RESEARCH AND REFERENCES")
    pointers(s, 6)

    # -- references --------------------------------------------------------
    rx, rw = LEFT, 6.30
    ry = panel(s, rx, TOP, rw, 4.60,
               "STANDARDS AND WORKS IMPLEMENTED OR CITED", accent=NAVY,
               fill=WHITE, title_size=9.5)
    refs = [
        ("NIST SP 800-86", "Guide to Integrating Forensic Techniques into "
         "Incident Response — the collection / analysis / reporting "
         "workflow the case model follows."),
        ("RFC 3227", "Guidelines for Evidence Collection and Archiving — "
         "order of volatility governs what JOCKY ingests first."),
        ("ISO/IEC 27037:2012", "Identification, collection, acquisition and "
         "preservation of digital evidence."),
        ("NIST SP 800-61r2", "Computer Security Incident Handling Guide "
         "— the triage-first workflow triage.jky implements."),
        ("MITRE ATT&CK", "Technique vocabulary the findings map to "
         "(T1059, T1071, T1070.001)."),
        ("Sigma", "Prior art for a portable, shareable detection language; "
         "JOCKY is the forensic analogue."),
        ("Velociraptor VQL", "Closest existing art — a query language for "
         "endpoint DFIR; JOCKY adds cited findings and reproducible reports."),
        ("plaso · Chainsaw · Hayabusa", "Timeline and EVTX tooling "
         "the timeline stage is measured against."),
        ("E. Zimmerman's tools", "De-facto reference implementations for EVTX, "
         "USN journal and MFT parsing — the adapter roadmap."),
        ("Shannon (1948)", "A Mathematical Theory of Communication — basis "
         "of the entropy() builtin that separates base64 from prose."),
        ("FIPS 180-4", "Secure Hash Standard — SHA-256 for every evidence "
         "digest and script hash."),
        ("Python Software Foundation", "Standard library only; deliberately no "
         "third-party runtime dependency."),
    ]
    py = ry - 0.01
    for i, (name, desc) in enumerate(refs):
        bg = WHITE if i % 2 == 0 else GREY_L
        rect(s, rx + 0.07, py, rw - 0.14, 0.340, fill=bg, line=None,
             radius=0.12)
        txt(s, rx + 0.13, py, 0.30, 0.340,
            [{"runs": [(f"{i+1}.", {"bold": True, "size": 6.8,
                                    "color": BLUE})]}],
            anchor=MSO_ANCHOR.MIDDLE, margins=(0, 0, 0, 0))
        txt(s, rx + 0.40, py, 1.66, 0.340,
            [{"runs": [(name, {"bold": True, "size": 6.7, "color": NAVY})],
              "line": 0.86}], anchor=MSO_ANCHOR.MIDDLE, margins=(0, 0, 0, 0))
        txt(s, rx + 2.10, py, rw - 2.22, 0.340,
            [{"runs": [(desc, {"size": 6.2, "color": INK})], "line": 0.86}],
            anchor=MSO_ANCHOR.MIDDLE, margins=(0, 0, 0, 0))
        py += 0.348

    source_note(s, "Works JOCKY implements against, or deliberately departs "
                   "from — no result in this deck depends on an uncited "
                   "external claim.", x=rx, w=rw)

    # -- artefacts ---------------------------------------------------------
    qx, qw = 6.72, 6.31
    qy = panel(s, qx, TOP, qw, 1.42, "ARTEFACTS", accent=BLUE, fill=LIGHT,
               title_size=9.5)
    items = [
        ("jocky/", "lexer.py · parser.py · runtime.py · "
                   "builtins.py · cli.py · serve.py"),
        ("console/index.html", "operator console — seven tabs, no external "
                               "assets, no build step"),
        ("scripts/*.jky", "beacon_hunt · triage · insider_usb · "
                          "telemetry_audit"),
        ("evidence/", "one coherent synthetic incident on FIN-WS-014, "
                      "2026-09-21"),
    ]
    iy2 = qy - 0.01
    for name, desc in items:
        txt(s, qx + 0.11, iy2, 1.44, 0.215,
            [{"runs": [(name, {"bold": True, "size": 7.0, "font": MONO,
                               "color": BLUE_D})], "line": 0.86}],
            anchor=MSO_ANCHOR.MIDDLE, margins=(0, 0, 0, 0))
        txt(s, qx + 1.60, iy2, qw - 1.72, 0.215,
            [{"runs": [(desc, {"size": 6.5, "color": INK})], "line": 0.86}],
            anchor=MSO_ANCHOR.MIDDLE, margins=(0, 0, 0, 0))
        iy2 += 0.222
    txt(s, qx + 0.11, 2.22, qw - 0.22, 0.18,
        [{"runs": [("Repository and demo links: ⟨ paste before upload "
                    "⟩ — the whole prototype runs from one checkout "
                    "with no install step.",
                    {"size": 6.2, "italic": True,
                     "color": RGBColor(0xC0, 0x39, 0x2B)})], "line": 0.88}],
        margins=(0.0, 0.0, 0.0, 0.0))

    # -- research contribution --------------------------------------------
    cy = panel(s, qx, 2.52, qw, 2.16,
               "RESEARCH CONTRIBUTION & CORE FINDINGS", accent=PURPLE,
               fill=PURPLE_L, title_size=9.5)
    bullets(s, qx + 0.11, cy - 0.01, qw - 0.22, 1.76, [
        ("Provenance can be a grammar rule, not a discipline. ",
         "Requiring a finding to name the result set that raised it makes an "
         "uncited conclusion a parse error rather than a bad habit — the "
         "contribution this work claims is that formulation."),
        ("The interpreter envelope is measured. ",
         "5.1k–7.4k records/sec, linear memory, 20–26× over "
         "hand-written Python — which bounds the right workload to triage "
         "sets and names the next milestone."),
        ("Compilation cost is volume-independent. ",
         "Lex + parse held at 2.2–3.1 ms from 10³ to 10⁵ "
         "records, separating script complexity from data volume as cost "
         "centres."),
        ("“Without triggering security solutions”, read defensibly. ",
         "A tool that hides from EDR is indistinguishable from malware to the "
         "endpoint's own evidence. Compatibility engineering — signed "
         "builds, published hashes, vendor allowlisting, documented telemetry "
         "— is the reading that survives an audit."),
        ("Forensic text breaks conventional lexing. ",
         "Windows paths, regex and base64 force a minimal escape set; the "
         "textbook escape table silently turned \\Temp into a tab. Found by "
         "test, fixed by design."),
    ], size=6.5, gap=2.8, mcolor=PURPLE, lead_color=PURPLE)

    # -- evolution pipeline -----------------------------------------------
    ey = panel(s, qx, 4.78, qw, 1.82,
               "RESEARCH METHODOLOGY & EVOLUTION PIPELINE", accent=GREEN,
               fill=GREEN_L, title_size=9.5)
    stages = [
        ("Problem Identification", "tool sprawl, no provenance, AV friction"),
        ("Standards Review", "NIST 800-86 · RFC 3227 · ISO 27037"),
        ("Prior-Art Gap Analysis", "Sigma detects, VQL queries — neither "
                                   "cites"),
        ("Language Design", "pipeline stages, minimal escapes, plain-dict AST"),
        ("Reference Implementation", "lexer → parser → interpreter, "
                                      "0 deps"),
        ("Empirical Validation", "50 tests · benchmarked 10³–"
                                 "10⁵ records"),
        ("Adversarial Review", "lexer escape bug, case-override semantics fixed"),
        ("Evolution Pipeline", "bytecode VM · EVTX/USN/MFT · ATT&CK "
                               "· fleet"),
    ]
    serpentine(s, qx + 0.11, ey + 0.04, 4, 2, 1.455, 0.56, 0.115, 0.20, stages,
               badge=None, label_size=6.8, sub_size=5.9, arrow_color=GREEN,
               label_in_header=True)
    # each stage gets its own coloured header bar carrying the stage name
    cols = [BLUE, BLUE_D, PURPLE, TEAL, GREEN, AMBER, RED, NAVY]
    for i, (name, _) in enumerate(stages):
        c, r = [(0, 0), (1, 0), (2, 0), (3, 0),
                (3, 1), (2, 1), (1, 1), (0, 1)][i]
        px = qx + 0.11 + c * (1.455 + 0.115)
        py2 = ey + 0.04 + r * (0.56 + 0.20)
        rect(s, px, py2, 1.455, 0.155, fill=cols[i], line=None, radius=0.36)
        txt(s, px, py2 - 0.005, 1.455, 0.165,
            [{"runs": [(name, {"bold": True, "size": 5.9, "color": WHITE})],
              "align": PP_ALIGN.CENTER, "line": 0.82}],
            anchor=MSO_ANCHOR.MIDDLE, margins=(0.01, 0.01, 0, 0))

    source_note(s, "Prototype, benchmark harness, evidence set and test suite "
                   "are all in the submitted repository.", x=qx, w=qw)


# ===========================================================================
# build
# ===========================================================================

def main():
    prs = Presentation(TEMPLATE)
    slides = list(prs.slides)

    slide1(prs, slides[0])
    slide2(prs, slides[1])
    slide3(prs, slides[2])
    slide4(prs, slides[3])
    slide5(prs, slides[4])
    slide6(prs, slides[5])

    # The template ships a seventh "important pointers" slide. SIH says it may
    # be deleted before upload, and six slides is the cap.
    lst = prs.slides._sldIdLst
    ids = list(lst)
    rId = ids[6].get(
        "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
    prs.part.drop_rel(rId)
    lst.remove(ids[6])

    prs.save(OUT)
    print(f"wrote {OUT} ({len(list(prs.slides))} slides)")


if __name__ == "__main__":
    main()
