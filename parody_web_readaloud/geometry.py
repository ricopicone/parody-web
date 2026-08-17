"""Where things sit on the served page.

Geometry comes from the `--clozes blank` PDF the reader actually downloads, so
every box is true of the page in front of them. Text does NOT come from here —
see script.py for why.
"""

from dataclasses import dataclass

import fitz

# A blank is a wide, flat stroke. Environment frames, table borders and the
# short marks inside figures are excluded by demanding a rule be much wider
# than it is tall, and wide enough to write in.
MIN_RULE_WIDTH = 8.0
MAX_RULE_HEIGHT = 2.5


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


def extract_rules(pdf_bytes: bytes) -> list:
    """The horizontal rules `\\clozeblank` draws — i.e. the blanks.

    Found rather than inferred: the rule is a real vector stroke, so its box is
    exact, which matters because the reveal is positioned against it.
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        out = []
        for number, page in enumerate(doc):
            for drawing in page.get_drawings():
                rect = drawing["rect"]
                width, height = rect.x1 - rect.x0, rect.y1 - rect.y0
                if width < MIN_RULE_WIDTH or height > MAX_RULE_HEIGHT:
                    continue
                out.append({"page": number,
                            "x0": round(rect.x0, 2), "y0": round(rect.y0, 2),
                            "x1": round(rect.x1, 2), "y1": round(rect.y1, 2)})
        out.sort(key=lambda r: (r["page"], r["y0"], r["x0"]))
        return out
    finally:
        doc.close()


def page_sizes(pdf_bytes: bytes) -> list:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        return [(round(p.rect.width, 2), round(p.rect.height, 2)) for p in doc]
    finally:
        doc.close()
