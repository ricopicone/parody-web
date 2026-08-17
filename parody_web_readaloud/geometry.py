"""Where things sit on the served page.

Geometry comes from the `--clozes blank` PDF the reader actually downloads, so
every box is true of the page in front of them. Text does NOT come from here —
see script.py for why.
"""

from dataclasses import dataclass

import fitz

# Blanks come in two shapes and both reach us as flat strokes:
#
#   inline `\cloze{...}`  -> \clozeblank{measured width}, ONE short rule
#   block  `::: {.cloze}` -> a framed box, which TeX draws as its top and
#                            bottom rules (the sides do not survive extraction)
#
# So width cannot decide what is a blank: a short rule is either an inline
# blank or a fraction bar, and on the electronics primer, which is dense with
# maths, flat strokes outnumber blanks roughly 17 to 1.
#
# Candidates are therefore left permissive here and align.py decides — a blank
# has to fall between the words either side of its cloze, which rejects strays
# structurally instead of by tuning a threshold. Grouping still needs the
# measure test, because only a matched pair spanning the measure is a box.
#
# 0.8, not 0.9: a cloze inside a description list is indented, and one measured
# 0.905 of its page's text block — close enough to the threshold to be luck.
MIN_RULE_WIDTH = 8.0
MAX_RULE_HEIGHT = 2.5
FULL_MEASURE_RATIO = 0.8

# The gap between a box's top and bottom rule. Generous enough for a tall
# equation, tight enough that two separate blanks do not merge.
MAX_LINE_GAP = 40.0
SAME_COLUMN_TOL = 3.0


@dataclass
class PageWord:
    text: str
    page: int
    x0: float
    y0: float
    x1: float
    y1: float


def extract_words(pdf_bytes: bytes) -> list:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        out = []
        for number, page in enumerate(doc):
            # (x0, y0, x1, y1, word, block_no, line_no, word_no)
            for w in page.get_text("words", sort=True):
                out.append(PageWord(text=w[4], page=number,
                                    x0=round(w[0], 2), y0=round(w[1], 2),
                                    x1=round(w[2], 2), y1=round(w[3], 2)))
        return out
    finally:
        doc.close()


def _page_measure(page) -> float:
    """The width of this page's text block, which is what \\linewidth renders to."""
    words = page.get_text("words", sort=True)
    if not words:
        return page.rect.width
    return max(w[2] for w in words) - min(w[0] for w in words)


def extract_rules(pdf_bytes: bytes) -> list:
    """The individual full-measure rule lines a blank is drawn from.

    Found rather than inferred: each rule is a real vector stroke, so its box is
    exact, which matters because the reveal is positioned against it.
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        out = []
        for number, page in enumerate(doc):
            full = FULL_MEASURE_RATIO * _page_measure(page)
            for drawing in page.get_drawings():
                rect = drawing["rect"]
                width, height = rect.x1 - rect.x0, rect.y1 - rect.y0
                if height > MAX_RULE_HEIGHT or width < MIN_RULE_WIDTH:
                    continue
                out.append({"page": number,
                            "x0": round(rect.x0, 2), "y0": round(rect.y0, 2),
                            "x1": round(rect.x1, 2), "y1": round(rect.y1, 2),
                            "full": width >= full})
        out.sort(key=lambda r: (r["page"], r["y0"], r["x0"]))
        return out
    finally:
        doc.close()


def group_rules(rules: list) -> list:
    """Rules sharing a column and close together are ONE blank.

    A blanked block is a framed box the height of the passage it hides, and TeX
    emits that as a top and a bottom rule with the same x-extent. Ungrouped,
    the bottom rule would be handed to the NEXT cloze and every blank after it
    would land in the wrong place.

    (This also handled the earlier rendering, where a block was a stack of one
    rule per line — same grouping, more rules.)
    """
    groups = []
    for rule in rules:
        last = groups[-1] if groups else None
        if (last
                and last.get("full") and rule.get("full")
                and last["page"] == rule["page"]
                and abs(last["x0"] - rule["x0"]) <= SAME_COLUMN_TOL
                and abs(last["x1"] - rule["x1"]) <= SAME_COLUMN_TOL
                and 0 <= rule["y0"] - last["y1"] <= MAX_LINE_GAP):
            last["y1"] = rule["y1"]
            last["lines"] += 1
        else:
            groups.append({**rule, "lines": 1})
    return groups


def extract_blanks(pdf_bytes: bytes) -> list:
    """Where the student writes: one entry per cloze, in reading order."""
    return group_rules(extract_rules(pdf_bytes))


def page_sizes(pdf_bytes: bytes) -> list:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        return [(round(p.rect.width, 2), round(p.rect.height, 2)) for p in doc]
    finally:
        doc.close()
