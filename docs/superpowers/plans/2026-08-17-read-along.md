# Read-along Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A reading mode that reads a section's PDF aloud at lecture pace, highlighting each word as it is spoken, revealing each clozed answer above its typeset blank so the student can write it in by hand with the existing pen.

**Architecture:** Three layers. A pure-Python core (no Django, no network) turns a `--clozes key` artifact's HTML into an ordered script, extracts word boxes and blank rules from the served `--clozes blank` section PDF, and aligns the two. A Django app, `parody_web_readaloud`, wraps that core with a cache model keyed by `slice_key`, an AWS Polly synthesis step run at generation time only, and two serve-only endpoints. A client module in the existing esbuild bundle draws a per-page overlay above the pdf.js canvas and the Konva ink layer.

**Tech Stack:** Python 3.12+, Django, PyMuPDF (`fitz`), `difflib` (stdlib), boto3 (AWS Polly), esbuild, vanilla JS (no framework), pdf.js, Konva.

**Spec:** `docs/superpowers/specs/2026-08-17-read-along-design.md`

## Global Constraints

- **Serve-only audio.** No request path may ever synthesise. A cache miss is a 404. Lazy synthesis is the one way cost starts tracking requests instead of content.
- **Access is inherited, never invented.** Every endpoint asks `get_policy().can_download_section_pdf(request, section)` exactly as `parody_web_annotate.views._section_or_404` does. A refusal must be indistinguishable from an absence.
- **`parody_web_readaloud` must precede `parody_web` in `INSTALLED_APPS`** — it shadows PDF-view templates and Django resolves them in that order. Enforced by a boot check, mirroring `parody_web_annotate.E001`.
- **Version identity is `slice_key`** — `parody_web.printing.slice_key_for(book, section)`. Never a `Section` FK: sections are deleted and recreated on re-import.
- **parody is not modified.** The `key` artifact comes from the existing `parody build --clozes key`.
- **The committed bundle is the shipped artefact.** `assets/` is source; `parody_web_readaloud/static/**/js/*.js` is committed output. Hosts never run Node.
- **New static subdirectories must be listed in `pyproject.toml` `[tool.setuptools.package-data]`** or they are silently omitted from the wheel and the deploy ships a site with no assets.
- **Never `git add -A`.** These trees are shared with concurrent sessions. Stage only the files named in the task.

---

### Task 1: The script — key-mode HTML to an ordered token stream

**Files:**
- Create: `parody_web_readaloud/script.py`
- Test: `parody_web_readaloud/tests_script.py`

**Interfaces:**
- Produces:
  - `class Token` — `kind: str` (`"word"` | `"math"` | `"cloze"` | `"figure_cloze"`), `text: str`, `latex: str`, `display: bool`, `answer: list[str]`, `src: str`
  - `parse_script(html: str) -> list[Token]`

- [ ] **Step 1: Write the failing test**

```python
from parody_web_readaloud.script import parse_script


def test_plain_prose_becomes_word_tokens():
    tokens = parse_script("<p>The plant is sampled.</p>")
    assert [t.kind for t in tokens] == ["word"] * 4
    assert [t.text for t in tokens] == ["The", "plant", "is", "sampled."]


def test_inline_math_is_one_token_carrying_its_latex():
    html = '<p>the function <span class="math inline">\\(p(t)\\)</span> is</p>'
    tokens = parse_script(html)
    assert [t.kind for t in tokens] == ["word", "word", "math", "word"]
    assert tokens[2].latex == "p(t)"
    assert tokens[2].display is False


def test_display_math_is_flagged():
    html = '<p><span class="math display">\\[X(f) = 1\\]</span></p>'
    tokens = parse_script(html)
    assert tokens[0].kind == "math"
    assert tokens[0].display is True
    assert tokens[0].latex == "X(f) = 1"


def test_cloze_key_span_becomes_a_cloze_token_with_its_words():
    html = '<p>at a fixed <span class="cloze-key">sampling rate</span>, which</p>'
    tokens = parse_script(html)
    kinds = [t.kind for t in tokens]
    assert kinds == ["word", "word", "word", "cloze", "word"]
    assert tokens[3].answer == ["sampling", "rate"]


def test_figure_with_a_cloze_sibling_becomes_a_figure_cloze():
    html = '<figure><img src="media/bode.svg" data-cloze-of="1"></figure>'
    tokens = parse_script(html)
    assert [t.kind for t in tokens] == ["figure_cloze"]
    assert tokens[0].src == "media/bode.svg"


def test_script_ignores_captions_and_scripts():
    html = ('<p>read this</p><figcaption>Figure 1: not read</figcaption>'
            '<script>var x = 1;</script>')
    assert [t.text for t in parse_script(html)] == ["read", "this"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/picone/parody-web-worktrees/readaloud && python -m pytest parody_web_readaloud/tests_script.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'parody_web_readaloud.script'`

- [ ] **Step 3: Write minimal implementation**

`parody_web_readaloud/script.py`:

```python
"""The ordered stream of things to say, read out of a `--clozes key` artifact.

The text source is deliberately the HTML and not the PDF. Everything that makes
PDF text hard — running heads, folios, hyphenation, mangled math spacing, page
breaks — is an artifact of reading text back out of a typeset page, and none of
it exists here. See the spec's "The alignment" section.

`key` mode is the one that carries answers AND marks them: `filter.lua:775`
wraps them in `<span class="cloze-key">`. Blank mode strips them on purpose and
must not be used here.
"""

from dataclasses import dataclass, field
from html.parser import HTMLParser

# Read aloud: prose only. Captions are excluded because floats move them out of
# reading order in the PDF, so they would never align (spec, "Known limit").
SKIP_TAGS = {"script", "style", "figcaption", "table"}


@dataclass
class Token:
    kind: str                              # word | math | cloze | figure_cloze
    text: str = ""
    latex: str = ""
    display: bool = False
    answer: list[str] = field(default_factory=list)
    src: str = ""


class _ScriptParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tokens: list[Token] = []
        self._skip_depth = 0
        self._math: str | None = None      # "inline" | "display" while open
        self._cloze: list[str] | None = None
        self._buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        classes = (a.get("class") or "").split()
        if tag == "span" and "math" in classes:
            self._math = "display" if "display" in classes else "inline"
            self._buf = []
        elif tag == "span" and "cloze-key" in classes:
            self._cloze = []
            self._buf = []
        elif tag == "img" and a.get("data-cloze-of"):
            self.tokens.append(Token(kind="figure_cloze", src=a.get("src", "")))

    def handle_endtag(self, tag):
        if tag in SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return
        if tag == "span" and self._math:
            raw = "".join(self._buf).strip()
            self.tokens.append(Token(kind="math", latex=_strip_delims(raw),
                                     display=self._math == "display"))
            self._math, self._buf = None, []
        elif tag == "span" and self._cloze is not None:
            words = "".join(self._buf).split()
            self.tokens.append(Token(kind="cloze", answer=words,
                                     text=" ".join(words)))
            self._cloze, self._buf = None, []

    def handle_data(self, data):
        if self._skip_depth:
            return
        if self._math is not None or self._cloze is not None:
            self._buf.append(data)
            return
        for word in data.split():
            self.tokens.append(Token(kind="word", text=word))


def _strip_delims(raw: str) -> str:
    """Drop pandoc's \\(…\\) or \\[…\\] wrapper, leaving the expression."""
    for open_, close in (("\\(", "\\)"), ("\\[", "\\]")):
        if raw.startswith(open_) and raw.endswith(close):
            return raw[len(open_):-len(close)].strip()
    return raw


def parse_script(html: str) -> list[Token]:
    parser = _ScriptParser()
    parser.feed(html)
    parser.close()
    return parser.tokens
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/picone/parody-web-worktrees/readaloud && python -m pytest parody_web_readaloud/tests_script.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add parody_web_readaloud/script.py parody_web_readaloud/tests_script.py
git commit -m "read-along: parse a key-mode artifact into an ordered script"
```

---

### Task 2: Page geometry — words and blank rules from the served PDF

**Files:**
- Create: `parody_web_readaloud/geometry.py`
- Test: `parody_web_readaloud/tests_geometry.py`

**Interfaces:**
- Produces:
  - `class PageWord` — `text: str`, `page: int`, `x0/y0/x1/y1: float`
  - `extract_words(pdf_bytes: bytes) -> list[PageWord]` — document order, all pages, 0-indexed `page`
  - `extract_rules(pdf_bytes: bytes) -> list[dict]` — `{page, x0, y0, x1, y1}` for horizontal rules, i.e. cloze blanks
  - `page_sizes(pdf_bytes: bytes) -> list[tuple[float, float]]`

Rules are found rather than inferred because `\clozeblank` draws a real vector stroke, so `get_drawings()` reports its box exactly (spec, "parody_web_readaloud (server side)" step 4).

- [ ] **Step 1: Write the failing test**

The test builds its own PDF with fitz so it needs no fixture file.

```python
import fitz

from parody_web_readaloud.geometry import (extract_rules, extract_words,
                                           page_sizes)


def _pdf(draw_rule=False):
    doc = fitz.open()
    page = doc.new_page(width=200, height=100)
    page.insert_text((10, 20), "alpha beta", fontsize=10)
    if draw_rule:
        page.draw_line(fitz.Point(10, 50), fitz.Point(60, 50), width=0.6)
    out = doc.tobytes()
    doc.close()
    return out


def test_words_come_back_in_order_with_boxes_and_pages():
    words = extract_words(_pdf())
    assert [w.text for w in words] == ["alpha", "beta"]
    assert all(w.page == 0 for w in words)
    assert words[0].x0 < words[1].x0
    assert words[0].y1 > words[0].y0


def test_horizontal_rules_are_reported_as_blanks():
    rules = extract_rules(_pdf(draw_rule=True))
    assert len(rules) == 1
    assert rules[0]["page"] == 0
    assert round(rules[0]["x1"] - rules[0]["x0"]) == 50


def test_a_page_with_no_rule_reports_none():
    assert extract_rules(_pdf()) == []


def test_page_sizes_are_reported():
    assert page_sizes(_pdf()) == [(200.0, 100.0)]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest parody_web_readaloud/tests_geometry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'parody_web_readaloud.geometry'`

- [ ] **Step 3: Write minimal implementation**

`parody_web_readaloud/geometry.py`:

```python
"""Where things sit on the served page.

Geometry comes from the `--clozes blank` PDF the reader actually downloads, so
boxes are true of the page in front of them. Text does NOT come from here — see
script.py for why.
"""

from dataclasses import dataclass

import fitz

# A blank is a wide, flat stroke. Ordinary rules (table borders, the box frames
# around environments) are excluded by demanding it be far wider than it is
# tall and short enough not to be a full-measure divider.
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


def extract_words(pdf_bytes: bytes) -> list[PageWord]:
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


def extract_rules(pdf_bytes: bytes) -> list[dict]:
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


def page_sizes(pdf_bytes: bytes) -> list[tuple[float, float]]:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        return [(round(p.rect.width, 2), round(p.rect.height, 2)) for p in doc]
    finally:
        doc.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest parody_web_readaloud/tests_geometry.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add parody_web_readaloud/geometry.py parody_web_readaloud/tests_geometry.py
git commit -m "read-along: word boxes and blank rules from the served PDF"
```

---

### Task 3: The alignment — join the script to the page

**Files:**
- Create: `parody_web_readaloud/align.py`
- Test: `parody_web_readaloud/tests_align.py`

**Interfaces:**
- Consumes: `script.Token`, `geometry.PageWord`
- Produces:
  - `class Placed` — `token: Token`, `index: int` (index into the script), `page: int | None`, `box: tuple[float, float, float, float] | None`
  - `align(tokens: list[Token], words: list[PageWord], rules: list[dict]) -> list[Placed]`

The classification in the spec falls out of `difflib.SequenceMatcher.get_opcodes()`: `equal` places a token, `delete` (PDF words matching no script token) is furniture, and `insert`/`replace` runs are script tokens the page does not print — of which the clozes are the ones corroborated by a rule.

- [ ] **Step 1: Write the failing test**

```python
from parody_web_readaloud.align import align
from parody_web_readaloud.geometry import PageWord
from parody_web_readaloud.script import Token


def _w(text, page=0, x0=0.0):
    return PageWord(text=text, page=page, x0=x0, y0=10.0, x1=x0 + 8, y1=20.0)


def test_matching_words_get_their_boxes():
    tokens = [Token("word", "alpha"), Token("word", "beta")]
    words = [_w("alpha", x0=0), _w("beta", x0=10)]
    placed = align(tokens, words, [])
    assert [p.page for p in placed] == [0, 0]
    assert placed[1].box == (10.0, 10.0, 18.0, 20.0)


def test_running_heads_are_dropped_not_matched():
    tokens = [Token("word", "alpha")]
    words = [_w("Real-Time", x0=0), _w("Computing", x0=20), _w("alpha", x0=40)]
    placed = align(tokens, words, [])
    assert len(placed) == 1
    assert placed[0].box[0] == 40.0


def test_a_hyphenated_break_still_places_the_word():
    tokens = [Token("word", "continuous")]
    words = [_w("con-", x0=0), _w("tinuous", page=0, x0=0)]
    placed = align(tokens, words, [])
    assert placed[0].page == 0
    assert placed[0].box is not None


def test_a_cloze_takes_its_box_from_the_rule_not_the_words():
    tokens = [Token("word", "fixed"),
              Token("cloze", answer=["sampling", "rate"]),
              Token("word", "which")]
    words = [_w("fixed", x0=0), _w("which", x0=60)]
    rules = [{"page": 0, "x0": 20.0, "y0": 18.0, "x1": 55.0, "y1": 19.0}]
    placed = align(tokens, words, rules)
    cloze = [p for p in placed if p.token.kind == "cloze"][0]
    assert cloze.page == 0
    assert cloze.box == (20.0, 18.0, 55.0, 19.0)


def test_an_unmatched_run_with_no_rule_is_not_treated_as_a_cloze():
    tokens = [Token("word", "alpha"), Token("cloze", answer=["ghost"])]
    placed = align(tokens, [_w("alpha")], [])
    cloze = [p for p in placed if p.token.kind == "cloze"][0]
    assert cloze.box is None


def test_math_tokens_survive_alignment_even_though_their_glyphs_differ():
    tokens = [Token("word", "when"), Token("math", latex="p(t)"),
              Token("word", "rises")]
    words = [_w("when", x0=0), _w("\U0001d45d(\U0001d461)", x0=20),
             _w("rises", x0=40)]
    placed = align(tokens, words, [])
    assert [p.token.kind for p in placed] == ["word", "math", "word"]
    assert placed[1].box is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest parody_web_readaloud/tests_align.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'parody_web_readaloud.align'`

- [ ] **Step 3: Write minimal implementation**

`parody_web_readaloud/align.py`:

```python
"""Join the clean script to the typeset page.

Both streams come from one source in the same order, so they agree almost
everywhere and the disagreements classify themselves:

  - a PDF word matching no script token  -> page furniture (head, folio, mark)
  - two PDF words matching one token     -> a hyphenated line break
  - a script token the page never prints -> a cloze, IF a rule corroborates it

That last qualifier is what stops ordinary alignment noise being read as a
blank: a gap with no rule under it is noise, not an answer.
"""

import difflib
import re
import unicodedata
from dataclasses import dataclass

from .geometry import PageWord
from .script import Token

# Math extracts as mathematical-alphanumeric codepoints (U+1D400..U+1D7FF),
# which NFKD folds back to the Latin letters the aligner can compare against.
_PUNCT = re.compile(r"[^\w]", re.UNICODE)


@dataclass
class Placed:
    token: Token
    index: int
    page: int | None = None
    box: tuple[float, float, float, float] | None = None


def _key(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text)
    return _PUNCT.sub("", folded).casefold()


def _token_key(token: Token) -> str:
    if token.kind == "word":
        return _key(token.text)
    if token.kind == "math":
        return _key(token.latex)
    return ""            # clozes and figures are never on the page


def _join(boxes):
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def align(tokens: list[Token], words: list[PageWord],
          rules: list[dict]) -> list[Placed]:
    placed = [Placed(token=t, index=i) for i, t in enumerate(tokens)]

    a = [_token_key(t) for t in tokens]
    b = [_key(w.text) for w in words]
    matcher = difflib.SequenceMatcher(a=a, b=b, autojunk=False)

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(i2 - i1):
                _place(placed[i1 + offset], [words[j1 + offset]])
        elif tag == "replace":
            # A hyphenated break is the common case: several page words
            # collapsing onto one token. Give every token in the run the whole
            # run's extent rather than guessing a split.
            run = words[j1:j2]
            if run:
                for p in placed[i1:i2]:
                    _place(p, run)

    _attach_rules([p for p in placed if p.token.kind in ("cloze",
                                                         "figure_cloze")],
                  rules)
    return placed


def _place(p: Placed, run: list[PageWord]):
    if p.token.kind in ("cloze", "figure_cloze"):
        return                     # never takes a box from prose
    p.page = run[0].page
    p.box = _join([(w.x0, w.y0, w.x1, w.y1) for w in run])


def _attach_rules(clozes: list[Placed], rules: list[dict]):
    """The nth unprinted token gets the nth rule, in reading order.

    Both sequences are in document order, so position is the whole join. A
    cloze with no rule left over keeps `box=None` and the client skips it
    rather than revealing over the wrong part of the page.
    """
    for cloze, rule in zip(clozes, rules):
        cloze.page = rule["page"]
        cloze.box = (rule["x0"], rule["y0"], rule["x1"], rule["y1"])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest parody_web_readaloud/tests_align.py -v`
Expected: 6 passed

- [ ] **Step 5: Run the whole core together**

Run: `python -m pytest parody_web_readaloud/ -v`
Expected: 16 passed

- [ ] **Step 6: Commit**

```bash
git add parody_web_readaloud/align.py parody_web_readaloud/tests_align.py
git commit -m "read-along: align the script to the page, corroborating clozes with rules"
```

---

### Task 4: Speech text and the math seam

**Files:**
- Create: `parody_web_readaloud/speech.py`
- Create: `assets/readaloud-sre/speak.mjs`
- Test: `parody_web_readaloud/tests_speech.py`

**Interfaces:**
- Consumes: `script.Token`
- Produces:
  - `class SkipMath` — `speak(latex: str, display: bool) -> str | None`, returns `None`
  - `class SreMath` — same signature, shells out to Node
  - `build_speech(tokens: list[Token], math=None) -> tuple[str, list[int]]` — returns the text for the TTS engine and, for each space-joined word in it, the index of the script token it came from

The second return value is the whole trick: Polly's speech marks carry character offsets into the text we send, and this list maps each of those back to a script token — which by Task 3 already carries a page and a box.

- [ ] **Step 1: Write the failing test**

```python
import pytest

from parody_web_readaloud.script import Token
from parody_web_readaloud.speech import SkipMath, build_speech


def test_prose_is_joined_and_mapped_one_to_one():
    tokens = [Token("word", "the"), Token("word", "plant")]
    text, owners = build_speech(tokens, math=SkipMath())
    assert text == "the plant"
    assert owners == [0, 1]


def test_a_cloze_answer_is_spoken_and_owned_by_the_cloze():
    tokens = [Token("word", "fixed"),
              Token("cloze", answer=["sampling", "rate"]),
              Token("word", "which")]
    text, owners = build_speech(tokens, math=SkipMath())
    assert text == "fixed sampling rate which"
    assert owners == [0, 1, 1, 2]


def test_skipped_math_contributes_no_words():
    tokens = [Token("word", "when"), Token("math", latex="p(t)"),
              Token("word", "rises")]
    text, owners = build_speech(tokens, math=SkipMath())
    assert text == "when rises"
    assert owners == [0, 2]


def test_spoken_math_is_owned_entirely_by_its_token():
    class Fake:
        def speak(self, latex, display):
            return "p of t"

    tokens = [Token("word", "when"), Token("math", latex="p(t)")]
    text, owners = build_speech(tokens, math=Fake())
    assert text == "when p of t"
    assert owners == [0, 1, 1, 1]


def test_a_figure_cloze_says_nothing():
    tokens = [Token("word", "see"), Token("figure_cloze", src="a.svg")]
    text, owners = build_speech(tokens, math=SkipMath())
    assert text == "see"
    assert owners == [0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest parody_web_readaloud/tests_speech.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'parody_web_readaloud.speech'`

- [ ] **Step 3: Write minimal implementation**

`parody_web_readaloud/speech.py`:

```python
"""What gets said, and which script token said it.

`build_speech` returns the text handed to the TTS engine together with an
owner index per spoken word. Polly's speech marks are character offsets into
exactly this text, so the owners list is what turns a timing into a box.

Math speech is a seam. SRE is a JavaScript library, so speaking math costs a
Node subprocess — acceptable at generation time, which is never a request path,
and impossible to reach from one. `SkipMath` is the sanctioned fallback from
the spec: prose carries the sentence, the eye carries the equation.
"""

import json
import subprocess
from pathlib import Path

SRE_SCRIPT = Path(__file__).resolve().parent.parent / "assets" / "readaloud-sre" / "speak.mjs"


class SkipMath:
    """Say nothing for math."""

    def speak(self, latex: str, display: bool) -> str | None:
        return None


class SreMath:
    """Speak math via MathJax's Speech Rule Engine, through Node.

    Display expressions can run very long, which is why the client has a
    skip-ahead control: each expression is one timed region, so skipping is a
    seek to its end.
    """

    def __init__(self, node: str = "node", timeout: float = 30.0):
        self.node = node
        self.timeout = timeout

    def speak(self, latex: str, display: bool) -> str | None:
        try:
            done = subprocess.run(
                [self.node, str(SRE_SCRIPT)],
                input=json.dumps({"latex": latex, "display": display}),
                capture_output=True, text=True, timeout=self.timeout,
                check=True)
        except (OSError, subprocess.SubprocessError):
            return None
        text = (json.loads(done.stdout or "{}") or {}).get("text") or ""
        return text.strip() or None


def build_speech(tokens, math=None) -> tuple[str, list[int]]:
    math = math or SkipMath()
    words: list[str] = []
    owners: list[int] = []

    for index, token in enumerate(tokens):
        if token.kind == "word":
            spoken = [token.text]
        elif token.kind == "cloze":
            spoken = list(token.answer)
        elif token.kind == "math":
            said = math.speak(token.latex, token.display)
            spoken = said.split() if said else []
        else:                       # figure_cloze — nothing to say
            spoken = []
        for word in spoken:
            words.append(word)
            owners.append(index)

    return " ".join(words), owners
```

`assets/readaloud-sre/speak.mjs`:

```javascript
/**
 * LaTeX in on stdin, spoken English out on stdout.
 *
 * Run only at generation time, from speech.py. Hosts that never regenerate
 * audio never need Node — and if it is missing, SreMath falls back to
 * SkipMath rather than failing the build.
 */
import { SRE } from 'speech-rule-engine';

const chunks = [];
for await (const chunk of process.stdin) chunks.push(chunk);
const { latex, display } = JSON.parse(chunks.join('') || '{}');

await SRE.setupEngine({ domain: 'mathspeak', style: 'default', locale: 'en' });
const mathml = SRE.toMathml
  ? SRE.toMathml(latex)
  : `<math display="${display ? 'block' : 'inline'}"><mi>${latex}</mi></math>`;

process.stdout.write(JSON.stringify({ text: SRE.toSpeech(mathml) }));
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest parody_web_readaloud/tests_speech.py -v`
Expected: 5 passed

- [ ] **Step 5: Add the Node dependency, without making hosts need it**

```bash
npm install --save-dev speech-rule-engine
```

- [ ] **Step 6: Commit**

```bash
git add parody_web_readaloud/speech.py parody_web_readaloud/tests_speech.py assets/readaloud-sre/speak.mjs package.json package-lock.json
git commit -m "read-along: speech text with an owner map, and the SRE math seam"
```

---

### Task 5: The Django app skeleton and its boot check

**Files:**
- Create: `parody_web_readaloud/__init__.py`, `apps.py`, `checks.py`
- Modify: `runtests.py:17`
- Modify: `tests/settings.py` (add to `INSTALLED_APPS`, before `parody_web`)
- Test: `parody_web_readaloud/tests_checks.py`

**Interfaces:**
- Produces: `ParodyWebReadaloudConfig`, and check id `parody_web_readaloud.E001`

- [ ] **Step 1: Write the failing test**

```python
from django.test import SimpleTestCase, override_settings

from parody_web_readaloud.checks import readaloud_app_order


class AppOrderCheck(SimpleTestCase):
    @override_settings(INSTALLED_APPS=["parody_web", "parody_web_readaloud"])
    def test_listed_after_core_is_an_error(self):
        errors = readaloud_app_order(None)
        self.assertEqual([e.id for e in errors], ["parody_web_readaloud.E001"])

    @override_settings(INSTALLED_APPS=["parody_web_readaloud", "parody_web"])
    def test_listed_before_core_is_fine(self):
        self.assertEqual(readaloud_app_order(None), [])

    @override_settings(INSTALLED_APPS=["parody_web"])
    def test_absent_is_not_our_problem(self):
        self.assertEqual(readaloud_app_order(None), [])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python runtests.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'parody_web_readaloud.checks'`

- [ ] **Step 3: Write minimal implementation**

`parody_web_readaloud/__init__.py`:

```python
default_app_config = "parody_web_readaloud.apps.ParodyWebReadaloudConfig"
```

`parody_web_readaloud/apps.py`:

```python
from django.apps import AppConfig


class ParodyWebReadaloudConfig(AppConfig):
    name = "parody_web_readaloud"
    verbose_name = "parody-web read-along"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from . import checks  # noqa: F401  (registers the boot-time check)
```

`parody_web_readaloud/checks.py`:

```python
"""Boot-time checks.

parody-web's posture throughout: a misconfiguration should fail on boot, not at
the first reader's request.
"""

from django.core.checks import Error, register


@register()
def readaloud_app_order(app_configs, **kwargs):
    """Read-along's templates must win over parody_web's.

    Same failure as parody_web_annotate.E001, and just as silent: listed after
    core, the mode loads but the toolbar entry never appears and nothing says
    why.
    """
    from django.conf import settings

    apps = list(getattr(settings, "INSTALLED_APPS", []))
    try:
        mine = apps.index("parody_web_readaloud")
        core = apps.index("parody_web")
    except ValueError:
        return []
    if mine > core:
        return [Error(
            "parody_web_readaloud must come before parody_web in INSTALLED_APPS.",
            hint="It shadows parody_web's PDF-view templates, and Django "
                 "resolves app templates in INSTALLED_APPS order. Listed "
                 "after, read-along loads but never appears.",
            id="parody_web_readaloud.E001",
        )]
    return []
```

In `runtests.py`, change line 17 to:

```python
    sys.exit(bool(runner.run_tests(
        ["parody_web", "parody_web_annotate", "parody_web_readaloud"])))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python runtests.py`
Expected: OK, including the 3 new check tests

- [ ] **Step 5: Commit**

```bash
git add parody_web_readaloud/__init__.py parody_web_readaloud/apps.py parody_web_readaloud/checks.py parody_web_readaloud/tests_checks.py runtests.py tests/settings.py
git commit -m "read-along: app skeleton with the INSTALLED_APPS order check"
```

---

### Task 6: The track model

**Files:**
- Create: `parody_web_readaloud/models.py`, `parody_web_readaloud/migrations/__init__.py`, `parody_web_readaloud/migrations/0001_initial.py`
- Test: `parody_web_readaloud/tests_models.py`

**Interfaces:**
- Produces: `ReadAlongTrack` with fields `book_slug`, `edition_id`, `section_key`, `slice_key`, `voice_id`, `engine`, `audio_name`, `duration_ms`, `words` (JSON), `clozes` (JSON), `created_at`, `updated_at`; unique on `(book_slug, edition_id, section_key, slice_key, voice_id)`.

Deliberately **not** per-user: one synthesis serves every listener, which is exactly why decision 3 needed no new access tier.

- [ ] **Step 1: Write the failing test**

```python
from django.db.utils import IntegrityError
from django.test import TestCase

from parody_web_readaloud.models import ReadAlongTrack


class Track(TestCase):
    def _make(self, **over):
        kwargs = dict(book_slug="rtc", edition_id="", section_key="ch1/s2",
                      slice_key="abc123", voice_id="Matthew", engine="neural",
                      audio_name="abc123-Matthew.mp3", duration_ms=1000,
                      words=[], clozes=[])
        kwargs.update(over)
        return ReadAlongTrack.objects.create(**kwargs)

    def test_one_track_per_version_and_voice(self):
        self._make()
        with self.assertRaises(IntegrityError):
            self._make()

    def test_a_second_voice_is_a_second_track(self):
        self._make()
        self._make(voice_id="Joanna", audio_name="abc123-Joanna.mp3")
        self.assertEqual(ReadAlongTrack.objects.count(), 2)

    def test_a_new_version_of_the_section_is_a_new_track(self):
        self._make()
        self._make(slice_key="def456", audio_name="def456-Matthew.mp3")
        self.assertEqual(ReadAlongTrack.objects.count(), 2)

    def test_cloze_count_reports_what_the_student_will_fill(self):
        track = self._make(clozes=[{"index": 3}, {"index": 9}])
        self.assertEqual(track.cloze_count, 2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python runtests.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'parody_web_readaloud.models'`

- [ ] **Step 3: Write minimal implementation**

`parody_web_readaloud/models.py`:

```python
from django.db import models


class ReadAlongTrack(models.Model):
    """One synthesis of one version of one section.

    Not per-user: cached audio makes cost constant in the number of listeners,
    which is the whole reason read-along needs no access tier of its own (spec,
    "Cost and access").

    Keyed by slug/edition/section_key/slice_key rather than a Section foreign
    key, for the reason `docs/host-integration.md` section 5 gives: sections are
    deleted and recreated on re-import, and a FK would cascade the cache away
    on every publish.
    """

    book_slug = models.CharField(max_length=100)
    edition_id = models.CharField(max_length=50, blank=True, default="")
    section_key = models.CharField(max_length=200)

    # Which version of the section's PDF these boxes are true of.
    slice_key = models.CharField(max_length=64)

    voice_id = models.CharField(max_length=50)
    engine = models.CharField(max_length=20, default="neural")

    # Filename within PARODY_WEB_READALOUD_CACHE. Not a path: the cache root is
    # a setting and may move between deploys.
    audio_name = models.CharField(max_length=200)
    duration_ms = models.PositiveIntegerField(default=0)

    # [{word, start_ms, end_ms, page, x0, y0, x1, y1, token}]
    words = models.JSONField(default=list, blank=True)
    # [{token, kind, answer, src, page, x0, y0, x1, y1, start_ms, end_ms}]
    clozes = models.JSONField(default=list, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("book_slug", "edition_id", "section_key",
                           "slice_key", "voice_id")
        indexes = [
            models.Index(fields=["book_slug", "section_key"]),
            models.Index(fields=["slice_key"]),
        ]
        ordering = ["-updated_at"]

    def __str__(self):
        return f"{self.book_slug}/{self.section_key}@{self.slice_key[:8]} ({self.voice_id})"

    @property
    def cloze_count(self):
        return len(self.clozes or [])
```

- [ ] **Step 4: Generate the migration**

Run: `python -c "
import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'tests.settings')
django.setup()
from django.core.management import call_command
call_command('makemigrations', 'parody_web_readaloud')
"`
Expected: `0001_initial.py` created

- [ ] **Step 5: Run tests to verify they pass**

Run: `python runtests.py`
Expected: OK, including the 4 new model tests

- [ ] **Step 6: Commit**

```bash
git add parody_web_readaloud/models.py parody_web_readaloud/migrations/
git add parody_web_readaloud/tests_models.py
git commit -m "read-along: the track model, keyed by slice_key and voice"
```

---

### Task 7: Generation — tie the core to Polly

**Files:**
- Create: `parody_web_readaloud/generate.py`
- Create: `parody_web_readaloud/management/__init__.py`, `parody_web_readaloud/management/commands/__init__.py`, `parody_web_readaloud/management/commands/generate_readalong.py`
- Test: `parody_web_readaloud/tests_generate.py`

**Interfaces:**
- Consumes: `script.parse_script`, `geometry.extract_words/extract_rules`, `align.align`, `speech.build_speech`
- Produces:
  - `build_track(html: str, pdf_bytes: bytes, synth, math=None) -> dict` — the whole pipeline as one pure-ish function, `synth` being any callable `(text) -> (audio_bytes, marks)`
  - `PollySynth(client=None, voice_id=..., engine=...)` — callable with that signature
  - management command `generate_readalong <book_slug> [--section KEY] [--voice ID]`

`build_track` takes `synth` as a parameter so every test runs without AWS.

- [ ] **Step 1: Write the failing test**

```python
from django.test import SimpleTestCase

from parody_web_readaloud.generate import build_track
from parody_web_readaloud.speech import SkipMath


def _fake_synth(text):
    """One mark per word, 100ms apart, at the right character offsets."""
    marks, offset, time_ms = [], 0, 0
    for word in text.split():
        marks.append({"type": "word", "start": offset,
                      "time": time_ms, "value": word})
        offset += len(word) + 1
        time_ms += 100
    return b"ID3-fake-audio", marks


class BuildTrack(SimpleTestCase):
    def setUp(self):
        import fitz
        doc = fitz.open()
        page = doc.new_page(width=300, height=100)
        page.insert_text((10, 20), "at a fixed", fontsize=10)
        page.insert_text((90, 20), ", which sets", fontsize=10)
        page.draw_line(__import__("fitz").Point(60, 22),
                       __import__("fitz").Point(88, 22), width=0.6)
        self.pdf = doc.tobytes()
        doc.close()
        self.html = ('<p>at a fixed <span class="cloze-key">sampling rate</span>'
                     ', which sets</p>')

    def test_every_spoken_word_carries_a_timing(self):
        track = build_track(self.html, self.pdf, _fake_synth, math=SkipMath())
        self.assertTrue(track["words"])
        for word in track["words"]:
            self.assertIn("start_ms", word)
            self.assertIn("end_ms", word)

    def test_the_answer_is_spoken(self):
        track = build_track(self.html, self.pdf, _fake_synth, math=SkipMath())
        spoken = [w["word"] for w in track["words"]]
        self.assertIn("sampling", spoken)
        self.assertIn("rate", spoken)

    def test_the_cloze_is_reported_with_the_rule_box_and_a_time_window(self):
        track = build_track(self.html, self.pdf, _fake_synth, math=SkipMath())
        self.assertEqual(len(track["clozes"]), 1)
        cloze = track["clozes"][0]
        self.assertEqual(cloze["answer"], "sampling rate")
        self.assertEqual(cloze["page"], 0)
        self.assertLess(cloze["x0"], cloze["x1"])
        self.assertLessEqual(cloze["start_ms"], cloze["end_ms"])

    def test_audio_comes_back_for_storing(self):
        track = build_track(self.html, self.pdf, _fake_synth, math=SkipMath())
        self.assertEqual(track["audio_bytes"], b"ID3-fake-audio")
        self.assertGreater(track["duration_ms"], 0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python runtests.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'parody_web_readaloud.generate'`

- [ ] **Step 3: Write minimal implementation**

`parody_web_readaloud/generate.py`:

```python
"""The generation pipeline: a key-mode artifact plus a served PDF, in; a track,
out.

Runs at import or on an instructor's command. NEVER on a request — see the
spec's "Cost and access". `synth` is injected so the whole pipeline is testable
without AWS.
"""

from .align import align
from .geometry import extract_rules, extract_words
from .script import parse_script
from .speech import build_speech

CHUNK_LIMIT = 2900          # Polly's per-request character ceiling, with room
TAIL_MS = 300               # how long the last word is assumed to last


def build_track(html: str, pdf_bytes: bytes, synth, math=None) -> dict:
    tokens = parse_script(html)
    placed = align(tokens, extract_words(pdf_bytes), extract_rules(pdf_bytes))
    text, owners = build_speech(tokens, math=math)

    audio_bytes, marks = synth(text)

    # Polly's marks are character offsets into exactly the text we sent, so the
    # offset of each space-joined word maps straight onto `owners`.
    offsets, cursor = {}, 0
    for position, word in enumerate(text.split()):
        offsets[cursor] = position
        cursor += len(word) + 1

    words = []
    for mark in marks:
        position = offsets.get(mark["start"])
        if position is None or position >= len(owners):
            continue                     # Polly split inside a word; skip it
        spot = placed[owners[position]]
        entry = {"word": mark["value"], "start_ms": mark["time"],
                 "token": spot.index}
        if spot.box:
            entry.update(page=spot.page, x0=spot.box[0], y0=spot.box[1],
                         x1=spot.box[2], y1=spot.box[3])
        words.append(entry)

    for i, entry in enumerate(words):
        entry["end_ms"] = (words[i + 1]["start_ms"] if i + 1 < len(words)
                           else entry["start_ms"] + TAIL_MS)

    by_token = {}
    for entry in words:
        window = by_token.setdefault(entry["token"],
                                     [entry["start_ms"], entry["end_ms"]])
        window[1] = max(window[1], entry["end_ms"])

    clozes = []
    for spot in placed:
        if spot.token.kind not in ("cloze", "figure_cloze") or not spot.box:
            continue
        start, end = by_token.get(spot.index, (0, 0))
        clozes.append({
            "token": spot.index, "kind": spot.token.kind,
            "answer": spot.token.text, "src": spot.token.src,
            "page": spot.page, "x0": spot.box[0], "y0": spot.box[1],
            "x1": spot.box[2], "y1": spot.box[3],
            "start_ms": start, "end_ms": end,
        })

    duration = words[-1]["end_ms"] if words else 0
    return {"words": words, "clozes": clozes, "audio_bytes": audio_bytes,
            "duration_ms": duration, "text": text}


def chunk_text(text: str, limit: int = CHUNK_LIMIT) -> list[str]:
    """Split on sentence boundaries under Polly's per-request ceiling."""
    chunks, current = [], ""
    for sentence in text.replace("? ", "?|").replace("! ", "!|") \
                        .replace(". ", ".|").split("|"):
        if len(current) + len(sentence) + 1 > limit and current:
            chunks.append(current.strip())
            current = ""
        current += sentence + " "
    if current.strip():
        chunks.append(current.strip())
    return chunks


class PollySynth:
    """Synthesise with AWS Polly, chunked, with word marks.

    Marks come back per chunk with offsets relative to that chunk, so each
    chunk's offsets are shifted by the running character total.
    """

    def __init__(self, client=None, voice_id="Matthew", engine="neural"):
        self._client = client
        self.voice_id = voice_id
        self.engine = engine

    @property
    def client(self):
        if self._client is None:
            import boto3
            self._client = boto3.client("polly")
        return self._client

    def __call__(self, text: str):
        import json

        audio, marks, offset, elapsed = bytearray(), [], 0, 0
        for chunk in chunk_text(text):
            common = dict(Text=chunk, VoiceId=self.voice_id,
                          Engine=self.engine)
            audio_response = self.client.synthesize_speech(
                OutputFormat="mp3", **common)
            chunk_audio = audio_response["AudioStream"].read()

            marks_response = self.client.synthesize_speech(
                OutputFormat="json", SpeechMarkTypes=["word"], **common)
            chunk_marks = [json.loads(line) for line
                           in marks_response["AudioStream"].read()
                           .decode("utf-8").splitlines() if line.strip()]

            for mark in chunk_marks:
                mark["start"] += offset
                mark["time"] += elapsed
                marks.append(mark)

            audio.extend(chunk_audio)
            offset += len(chunk) + 1
            elapsed = marks[-1]["time"] + 400 if marks else elapsed

        return bytes(audio), marks
```

`parody_web_readaloud/management/commands/generate_readalong.py`:

```python
"""Generate read-along tracks. The only place synthesis ever happens.

    python manage.py generate_readalong rtc --section ch1/s2

Reads the section HTML from a `--clozes key` artifact, which the host imports
alongside the published one and never serves.
"""

from django.core.management.base import BaseCommand, CommandError

from parody_web import printing
from parody_web.models import Book, Section
from parody_web_readaloud.generate import PollySynth, build_track
from parody_web_readaloud.models import ReadAlongTrack
from parody_web_readaloud.speech import SkipMath, SreMath
from parody_web_readaloud.storage import write_audio


class Command(BaseCommand):
    help = "Synthesise read-along audio and timings for a book's sections."

    def add_arguments(self, parser):
        parser.add_argument("book_slug")
        parser.add_argument("--section", default=None,
                            help="Section.key; omit for every section")
        parser.add_argument("--voice", default="Matthew")
        parser.add_argument("--engine", default="neural",
                            choices=["neural", "standard"])
        parser.add_argument("--skip-math", action="store_true",
                            help="Do not shell out to SRE; leave math silent.")
        parser.add_argument("--force", action="store_true",
                            help="Re-synthesise even if a track exists.")

    def handle(self, *args, **options):
        book = Book.objects.filter(slug=options["book_slug"]).first()
        if book is None:
            raise CommandError(f"no book {options['book_slug']!r}")

        sections = Section.objects.filter(book=book)
        if options["section"]:
            sections = sections.filter(key=options["section"])
        if not sections.exists():
            raise CommandError("no matching sections")

        math = SkipMath() if options["skip_math"] else SreMath()
        synth = PollySynth(voice_id=options["voice"], engine=options["engine"])

        for section in sections:
            slice_key = printing.slice_key_for(book, section)
            if not slice_key:
                self.stderr.write(f"skip {section.key}: no section pdf")
                continue

            existing = ReadAlongTrack.objects.filter(
                book_slug=book.slug, edition_id=book.edition_id or "",
                section_key=section.key, slice_key=slice_key,
                voice_id=options["voice"]).first()
            if existing and not options["force"]:
                self.stdout.write(f"have {section.key}")
                continue

            html = key_mode_html(book, section)
            if not html:
                self.stderr.write(
                    f"skip {section.key}: no key-mode html imported")
                continue

            pdf_path = printing.section_pdf_path(book, section)
            track = build_track(html, pdf_path.read_bytes(), synth, math=math)

            name = f"{slice_key}-{options['voice']}.mp3"
            write_audio(name, track["audio_bytes"])
            ReadAlongTrack.objects.update_or_create(
                book_slug=book.slug, edition_id=book.edition_id or "",
                section_key=section.key, slice_key=slice_key,
                voice_id=options["voice"],
                defaults={"engine": options["engine"], "audio_name": name,
                          "duration_ms": track["duration_ms"],
                          "words": track["words"], "clozes": track["clozes"]})
            self.stdout.write(
                f"made {section.key}: {len(track['words'])} words, "
                f"{len(track['clozes'])} blanks")


def key_mode_html(book, section):
    """The section's `--clozes key` HTML.

    Hosts import it beside the published artifact; `Section.key_html` is the
    agreed field (see docs/host-integration.md). Absent, read-along skips the
    section rather than falling back to blank-mode HTML, which has no answers.
    """
    return getattr(section, "key_html", "") or ""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python runtests.py`
Expected: OK, including the 4 new generate tests

- [ ] **Step 5: Commit**

```bash
git add parody_web_readaloud/generate.py parody_web_readaloud/tests_generate.py parody_web_readaloud/management/
git commit -m "read-along: the generation pipeline, with Polly injected"
```

---

### Task 8: Audio storage and the two serve-only endpoints

**Files:**
- Create: `parody_web_readaloud/storage.py`, `parody_web_readaloud/views.py`, `parody_web_readaloud/urls.py`
- Test: `parody_web_readaloud/tests_views.py`

**Interfaces:**
- Consumes: `models.ReadAlongTrack`
- Produces:
  - `storage.cache_root() -> Path`, `storage.write_audio(name, data) -> Path`, `storage.audio_path(name) -> Path`
  - view `track(request, chapter_slug, section_slug)` → JSON `{slice_key, duration_ms, words, clozes, audio_url}`
  - view `audio(request, chapter_slug, section_slug)` → the mp3, or 404
  - setting `PARODY_WEB_READALOUD_CACHE`

- [ ] **Step 1: Write the failing test**

```python
import shutil
import tempfile

from django.test import TestCase, override_settings
from django.urls import reverse

from parody_web_readaloud.models import ReadAlongTrack


class Endpoints(TestCase):
    """Uses the fixtures tests/ already builds for parody_web_annotate."""

    def setUp(self):
        self.cache = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.cache, ignore_errors=True)

    def _url(self, name):
        return reverse(f"parody_web_readaloud:{name}",
                       kwargs={"chapter_slug": "ch1", "section_slug": "s2"})

    def test_a_missing_track_is_a_404_and_never_synthesises(self):
        response = self.client.get(self._url("track"))
        self.assertEqual(response.status_code, 404)

    def test_a_present_track_comes_back_as_json(self):
        ReadAlongTrack.objects.create(
            book_slug="testbook", edition_id="", section_key="ch1/s2",
            slice_key=self.slice_key, voice_id="Matthew", engine="neural",
            audio_name="x.mp3", duration_ms=4200,
            words=[{"word": "at", "start_ms": 0, "end_ms": 100, "page": 0,
                    "x0": 1, "y0": 2, "x1": 3, "y1": 4, "token": 0}],
            clozes=[])
        response = self.client.get(self._url("track"))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["duration_ms"], 4200)
        self.assertEqual(len(body["words"]), 1)
        self.assertIn("audio_url", body)

    def test_missing_audio_is_a_404_not_a_500(self):
        with override_settings(PARODY_WEB_READALOUD_CACHE=self.cache):
            response = self.client.get(self._url("audio"))
        self.assertEqual(response.status_code, 404)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python runtests.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'parody_web_readaloud.storage'`

- [ ] **Step 3: Write minimal implementation**

`parody_web_readaloud/storage.py`:

```python
"""Where generated audio lives.

Local disk under PARODY_WEB_READALOUD_CACHE, mirroring the print cache rather
than reaching for S3: the deploy already knows how to keep a directory, and the
same X-Accel prefix can hand the file off to nginx.
"""

from pathlib import Path

from django.conf import settings


def cache_root() -> Path:
    value = getattr(settings, "PARODY_WEB_READALOUD_CACHE", "")
    if not value:
        raise RuntimeError(
            "PARODY_WEB_READALOUD_CACHE is unset; read-along cannot store or "
            "serve audio. Set it to a writable directory.")
    return Path(value)


def audio_path(name: str) -> Path:
    # Names are generated from slice_key + voice, never from user input, but
    # resolve anyway so a malformed row cannot escape the cache directory.
    root = cache_root().resolve()
    path = (root / name).resolve()
    if not str(path).startswith(str(root)):
        raise ValueError(f"audio name escapes the cache root: {name!r}")
    return path


def write_audio(name: str, data: bytes) -> Path:
    path = audio_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path
```

`parody_web_readaloud/views.py`:

```python
"""Read-along endpoints.

Both ask the access policy exactly the question `parody_web.views.section_pdf`
asks. Anything a reader may not download, they may not listen to.

NEITHER SYNTHESISES. A miss is a 404. Lazy synthesis is the one path by which
an anonymous visitor to a public book could mint new audio, and the only way
cost starts tracking requests instead of content.
"""

from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from parody_web import printing
from parody_web.access import get_policy
from parody_web.models import Section
from parody_web.views import _resolve_book

from . import storage
from .models import ReadAlongTrack

DEFAULT_VOICE = "Matthew"


def _section_or_404(request, chapter_slug, section_slug):
    book, _ = _resolve_book(request)
    section = get_object_or_404(
        Section, book=book, chapter__slug=chapter_slug, slug=section_slug)
    if not get_policy().can_download_section_pdf(request, section):
        raise Http404("no pdf for this section")
    return book, section


def _track_or_404(request, chapter_slug, section_slug):
    book, section = _section_or_404(request, chapter_slug, section_slug)
    voice = request.GET.get("voice") or DEFAULT_VOICE
    track = ReadAlongTrack.objects.filter(
        book_slug=book.slug, edition_id=book.edition_id or "",
        section_key=section.key,
        slice_key=printing.slice_key_for(book, section),
        voice_id=voice).first()
    if track is None:
        raise Http404("no read-along for this section")
    return book, section, track


@require_http_methods(["GET"])
def track(request, chapter_slug, section_slug):
    _, _, row = _track_or_404(request, chapter_slug, section_slug)
    return JsonResponse({
        "slice_key": row.slice_key,
        "voice_id": row.voice_id,
        "duration_ms": row.duration_ms,
        "words": row.words,
        "clozes": row.clozes,
        "audio_url": reverse("parody_web_readaloud:audio", kwargs={
            "chapter_slug": chapter_slug, "section_slug": section_slug,
        }) + f"?voice={row.voice_id}",
    })


@require_http_methods(["GET"])
def audio(request, chapter_slug, section_slug):
    _, _, row = _track_or_404(request, chapter_slug, section_slug)
    try:
        path = storage.audio_path(row.audio_name)
    except (RuntimeError, ValueError):
        raise Http404("read-along audio is not configured")
    if not path.exists():
        raise Http404("read-along audio has not been generated")
    return FileResponse(path.open("rb"), content_type="audio/mpeg")
```

`parody_web_readaloud/urls.py`:

```python
"""Read-along routes, mounted alongside parody_web's under the same book prefix."""

from django.urls import path

from . import views

app_name = "parody_web_readaloud"

urlpatterns = [
    path("<slug:chapter_slug>/<slug:section_slug>/readalong/",
         views.track, name="track"),
    path("<slug:chapter_slug>/<slug:section_slug>/readalong/audio/",
         views.audio, name="audio"),
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python runtests.py`
Expected: OK, including the 3 new endpoint tests

- [ ] **Step 5: Commit**

```bash
git add parody_web_readaloud/storage.py parody_web_readaloud/views.py parody_web_readaloud/urls.py parody_web_readaloud/tests_views.py
git commit -m "read-along: serve-only track and audio endpoints"
```

---

### Task 9: The client — karaoke highlight

**Files:**
- Create: `assets/readaloud/track.js`, `assets/readaloud/highlight.js`
- Test: `assets/readaloud/track.test.js`, `assets/readaloud/highlight.test.js`

**Interfaces:**
- Produces:
  - `wordAt(words, ms) -> index | -1` — binary search over the timing array
  - `class Highlight` — `constructor(entry, {theme})`, `resize(viewport)`, `show(box)`, `clear()`, `destroy()`

Pure logic is separated from the DOM so it runs under `node --test`, matching how `assets/annotate/*.test.js` is already structured.

- [ ] **Step 1: Write the failing test**

`assets/readaloud/track.test.js`:

```javascript
import { strict as assert } from 'node:assert';
import { test } from 'node:test';
import { wordAt, clozeAt } from './track.js';

const WORDS = [
  { start_ms: 0, end_ms: 100 },
  { start_ms: 100, end_ms: 250 },
  { start_ms: 250, end_ms: 400 },
];

test('finds the word being spoken', () => {
  assert.equal(wordAt(WORDS, 0), 0);
  assert.equal(wordAt(WORDS, 150), 1);
  assert.equal(wordAt(WORDS, 399), 2);
});

test('before the first and after the last are misses', () => {
  assert.equal(wordAt(WORDS, -1), -1);
  assert.equal(wordAt(WORDS, 900), -1);
});

test('an empty track never matches', () => {
  assert.equal(wordAt([], 10), -1);
});

test('a cloze is due once playback reaches the end of its answer', () => {
  const clozes = [{ token: 4, start_ms: 100, end_ms: 250 }];
  assert.equal(clozeAt(clozes, 90), -1);
  assert.equal(clozeAt(clozes, 250), 0);
  assert.equal(clozeAt(clozes, 260), 0);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test assets/readaloud/track.test.js`
Expected: FAIL, cannot find module `./track.js`

- [ ] **Step 3: Write minimal implementation**

`assets/readaloud/track.js`:

```javascript
/**
 * Reading the timing array.
 *
 * Timings are sorted and non-overlapping, so both lookups are binary searches
 * — they run on every animation frame and a linear scan over a section's few
 * thousand words is enough to drop frames on a tablet.
 */

/** Index of the word being spoken at `ms`, or -1. */
export function wordAt(words, ms) {
  let low = 0;
  let high = words.length - 1;
  while (low <= high) {
    const mid = (low + high) >> 1;
    const word = words[mid];
    if (ms < word.start_ms) high = mid - 1;
    else if (ms >= word.end_ms) low = mid + 1;
    else return mid;
  }
  return -1;
}

/**
 * Index of the cloze whose answer has just finished being spoken, or -1.
 *
 * Due at `end_ms`, not `start_ms`: the answer is spoken first and the reveal
 * holds afterwards, so the pause lands once the student has heard the whole
 * term.
 */
export function clozeAt(clozes, ms) {
  for (let i = 0; i < clozes.length; i += 1) {
    if (ms >= clozes[i].end_ms) {
      if (i + 1 === clozes.length || ms < clozes[i + 1].end_ms) return i;
    }
  }
  return -1;
}
```

`assets/readaloud/highlight.js`:

```javascript
/**
 * The karaoke mark, one canvas per page above the pdf.js canvas.
 *
 * A canvas rather than positioned DOM: it sits in the same stacking context as
 * the ink layer and repaints on one rAF without touching layout.
 *
 * Dark mode inverts the PAGE canvas through a CSS filter (see annotate.css).
 * This layer deliberately sits outside that filter, so its colour is chosen
 * for the theme here rather than being inverted along with the paper.
 */
export class Highlight {
  constructor(entry, { theme } = {}) {
    this.entry = entry;
    this.theme = theme || { dark: false };
    this.canvas = document.createElement('canvas');
    this.canvas.className = 'readalong-highlight';
    entry.el.appendChild(this.canvas);
    this.resize(entry.viewport);
  }

  resize(viewport) {
    this.viewport = viewport;
    const dpr = window.devicePixelRatio || 1;
    this.canvas.width = Math.floor(viewport.width * dpr);
    this.canvas.height = Math.floor(viewport.height * dpr);
    this.canvas.style.width = `${viewport.width}px`;
    this.canvas.style.height = `${viewport.height}px`;
    this.ctx = this.canvas.getContext('2d');
    this.ctx.scale(dpr, dpr);
    if (this.box) this.show(this.box);
  }

  setTheme(theme) {
    this.theme = theme;
    if (this.box) this.show(this.box);
  }

  /** `box` is [x0, y0, x1, y1] in PDF points. */
  show(box) {
    this.box = box;
    const [x0, y0, x1, y1] = this.viewport.convertToViewportRectangle(box);
    this.clear(false);
    this.ctx.fillStyle = this.theme.dark
      ? 'rgba(255, 214, 102, 0.28)'
      : 'rgba(255, 214, 102, 0.55)';
    const top = Math.min(y0, y1);
    const height = Math.abs(y1 - y0);
    // A touch of bleed so descenders and the leading are covered evenly.
    this.ctx.fillRect(x0 - 1, top - 1, x1 - x0 + 2, height + 2);
  }

  clear(forget = true) {
    if (forget) this.box = null;
    this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
  }

  destroy() {
    this.canvas.remove();
  }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `node --test assets/readaloud/track.test.js`
Expected: 4 passing

- [ ] **Step 5: Commit**

```bash
git add assets/readaloud/track.js assets/readaloud/track.test.js assets/readaloud/highlight.js
git commit -m "read-along: timing lookup and the karaoke highlight layer"
```

---

### Task 10: The client — reveal, pause, and continue

**Files:**
- Create: `assets/readaloud/reveal.js`, `assets/readaloud/index.js`
- Modify: `esbuild.config.js`
- Test: `assets/readaloud/reveal.test.js`

**Interfaces:**
- Consumes: `track.wordAt`, `track.clozeAt`, `highlight.Highlight`
- Produces:
  - `placeReveal(box, viewport, plate) -> {left, top}` — where the plate goes, given the blank's box
  - `class Reveal` — `show(cloze, entry)`, `fade()`, `destroy()`
  - `boot()` in `index.js`, wired to the existing `[data-ink-root]`

- [ ] **Step 1: Write the failing test**

```javascript
import { strict as assert } from 'node:assert';
import { test } from 'node:test';
import { placeReveal } from './reveal.js';

// A viewport stub matching pdf.js's contract: PDF points in, CSS px out.
const viewport = {
  convertToViewportRectangle: ([x0, y0, x1, y1]) => [x0, y0 * 2, x1, y1 * 2],
};

test('the plate sits above the blank, not on it', () => {
  const at = placeReveal([100, 50, 160, 56], viewport,
                         { width: 80, height: 20 });
  assert.ok(at.top + 20 <= 100, 'plate bottom must clear the blank top');
});

test('the plate is centred on the blank', () => {
  const at = placeReveal([100, 50, 160, 56], viewport,
                         { width: 80, height: 20 });
  assert.equal(at.left + 40, 130);
});

test('a blank at the very top of the page pushes the plate below it', () => {
  const at = placeReveal([100, 0, 160, 3], viewport,
                         { width: 80, height: 20 });
  assert.ok(at.top > 0, 'must not render off the top of the page');
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test assets/readaloud/reveal.test.js`
Expected: FAIL, cannot find module `./reveal.js`

- [ ] **Step 3: Write minimal implementation**

`assets/readaloud/reveal.js`:

```javascript
/**
 * The answer, shown so it can be copied.
 *
 * ABOVE the blank, never in it. The blank is where the student writes, and the
 * annotation canvas is live over it — a plate in the blank would be drawn on
 * top of. Above rather than below because a stylus hand rests below the line
 * being written, so a plate below is the one that ends up under the palm.
 *
 * It holds until the student continues, rather than fading on a timer: this is
 * the board in class, and it stays up while you write it down.
 */
const GAP = 6;          // clear space between plate and blank, in CSS px

export function placeReveal(box, viewport, plate) {
  const [x0, y0, x1] = viewport.convertToViewportRectangle(box);
  const left = (x0 + x1) / 2 - plate.width / 2;
  let top = y0 - plate.height - GAP;
  // Flip below when there is no room above, so it never renders off-page.
  if (top < 0) top = y0 + GAP;
  return { left, top };
}

export class Reveal {
  constructor(root) {
    this.root = root;
    this.el = document.createElement('div');
    this.el.className = 'readalong-reveal';
    this.el.hidden = true;
    root.appendChild(this.el);
  }

  /**
   * Figure clozes reveal into the margin pad instead: the complete artwork
   * cannot cover the incomplete figure the student is drawing into, and the
   * pad is half a page wide and immediately adjacent.
   */
  show(cloze, entry) {
    if (cloze.kind === 'figure_cloze') return this._showFigure(cloze, entry);
    this.el.textContent = cloze.answer;
    this.el.dataset.kind = 'text';
    this.el.hidden = false;
    this.el.classList.remove('is-fading');
    entry.el.appendChild(this.el);
    const plate = this.el.getBoundingClientRect();
    const at = placeReveal([cloze.x0, cloze.y0, cloze.x1, cloze.y1],
                           entry.viewport, plate);
    this.el.style.left = `${at.left}px`;
    this.el.style.top = `${at.top}px`;
    return this.el;
  }

  _showFigure(cloze, entry) {
    this.el.dataset.kind = 'figure';
    this.el.innerHTML = '';
    const img = document.createElement('img');
    img.src = cloze.src;
    img.alt = '';
    this.el.appendChild(img);
    this.el.hidden = false;
    this.el.classList.remove('is-fading');
    // The pad is an ink surface whose strokes are glued on at export. This is
    // a transient overlay child, never pad content, so the exporter cannot
    // mistake it for something the reader drew.
    entry.pad.appendChild(this.el);
    this.el.style.left = '0px';
    this.el.style.top = `${entry.viewport.height * 0.05}px`;
    return this.el;
  }

  fade() {
    this.el.classList.add('is-fading');
    const done = () => { this.el.hidden = true; };
    this.el.addEventListener('transitionend', done, { once: true });
    // Belt and braces: a hidden tab fires no transitions.
    setTimeout(done, 1200);
  }

  destroy() {
    this.el.remove();
  }
}
```

`assets/readaloud/index.js`:

```javascript
/**
 * Read-along: the section, read aloud, over the PDF the student writes on.
 *
 * Boots only when the server has a track for this section. Absent one, the
 * viewer is left exactly as it was — read-along is additive, never a
 * precondition for annotating.
 */
import { Highlight } from './highlight.js';
import { Reveal } from './reveal.js';
import { clozeAt, wordAt } from './track.js';

async function boot() {
  const root = document.querySelector('[data-ink-root]');
  if (!root) return;

  const base = root.dataset.base;
  const response = await fetch(`${base}readalong/`, {
    headers: { Accept: 'application/json' },
  });
  if (!response.ok) return;             // no track: leave the viewer alone
  const track = await response.json();

  const audio = new Audio(track.audio_url);
  audio.preload = 'auto';

  const layers = new Map();             // page number -> Highlight
  const reveal = new Reveal(root);
  let paused = null;                    // index of the cloze we stopped at
  let lastCloze = -1;

  root.dataset.readalong = '1';

  // The viewer holds canvases only for pages near the viewport, so a layer may
  // not exist yet when the audio reaches its page. Ask the page view to bring
  // it in rather than assuming one is there.
  function layerFor(page) {
    return layers.get(page + 1) || null;
  }

  function frame() {
    if (!audio.paused) {
      const ms = audio.currentTime * 1000;
      const index = wordAt(track.words, ms);
      if (index >= 0) {
        const word = track.words[index];
        if (word.page !== undefined) {
          const layer = layerFor(word.page);
          if (layer) layer.show([word.x0, word.y0, word.x1, word.y1]);
          scrollTo(word);
        }
      }
      const due = clozeAt(track.clozes, ms);
      if (due >= 0 && due !== lastCloze) {
        lastCloze = due;
        holdAt(due);
      }
    }
    requestAnimationFrame(frame);
  }

  function holdAt(index) {
    const cloze = track.clozes[index];
    const layer = layerFor(cloze.page);
    audio.pause();
    paused = index;
    const entry = layer && layer.entry;
    if (entry) reveal.show(cloze, entry);
    root.dataset.readalongHolding = '1';
  }

  function resume() {
    if (paused === null) return;
    paused = null;
    delete root.dataset.readalongHolding;
    reveal.fade();
    audio.play();
  }

  let following = true;
  function scrollTo(word) {
    if (!following) return;
    const layer = layerFor(word.page);
    if (!layer) return;
    const [, y0] = layer.viewport.convertToViewportRectangle(
      [word.x0, word.y0, word.x1, word.y1]);
    const scroller = root.querySelector('[data-ink-pages]');
    const target = layer.entry.row.offsetTop + y0 - scroller.clientHeight / 2;
    if (Math.abs(scroller.scrollTop - target) > scroller.clientHeight / 3) {
      scroller.scrollTo({ top: target, behavior: 'smooth' });
    }
  }

  // Auto-scroll must not fight a reader who is scrolling or drawing. Any
  // manual scroll hands control back; the follow button takes it again.
  root.querySelector('[data-ink-pages]')?.addEventListener('wheel', () => {
    following = false;
  }, { passive: true });

  document.addEventListener('keydown', (event) => {
    if (event.key === ' ' && paused !== null) {
      event.preventDefault();
      resume();
    }
  });
  root.addEventListener('pointerdown', (event) => {
    if (paused !== null && event.target.closest('.readalong-reveal')) resume();
  });

  window.parodyReadAlong = { audio, track, resume, follow: (on) => {
    following = on;
  } };

  requestAnimationFrame(frame);
  document.dispatchEvent(new CustomEvent('readalong:ready', {
    detail: { layers, Highlight },
  }));
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', boot);
} else {
  boot();
}
```

In `esbuild.config.js`, after the annotate build, add:

```javascript
const READALOUD_OUT = 'parody_web_readaloud/static/parody_web_readaloud/js';
await mkdir(READALOUD_OUT, { recursive: true });
await build({
  entryPoints: ['assets/readaloud/index.js'],
  bundle: true,
  minify: true,
  format: 'esm',
  target: ['es2020'],
  outfile: `${READALOUD_OUT}/readalong.js`,
  logLevel: 'info',
});
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `node --test assets/readaloud/*.test.js`
Expected: 7 passing

- [ ] **Step 5: Build the bundle**

Run: `npm run build`
Expected: writes `parody_web_readaloud/static/parody_web_readaloud/js/readalong.js`

- [ ] **Step 6: Commit**

```bash
git add assets/readaloud/reveal.js assets/readaloud/reveal.test.js assets/readaloud/index.js esbuild.config.js parody_web_readaloud/static/
git commit -m "read-along: reveal above the blank, hold, and continue"
```

---

### Task 11: Styling, template wiring, and packaging

**Files:**
- Create: `parody_web_readaloud/static/parody_web_readaloud/css/readalong.css`
- Create: `parody_web_readaloud/templates/parody_web/_pdf_view_head.html`
- Create: `parody_web_readaloud/templatetags/__init__.py`, `parody_web_readaloud/templatetags/parody_web_readaloud.py`
- Modify: `pyproject.toml` (`[tool.setuptools.package-data]`, `[project.optional-dependencies]`)
- Test: `parody_web_readaloud/tests_packaging.py`

**Interfaces:**
- Produces: the `readalong` extra (`boto3`, `PyMuPDF`), and the shipped static tree

The template shadows `parody_web_annotate`'s `_pdf_view_head.html`, so it must include the annotator's own tag as well as its own — read-along adds to the viewer, it does not replace it.

- [ ] **Step 1: Write the failing test**

```python
import tomllib
from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parent.parent


class Packaging(SimpleTestCase):
    def test_static_is_declared_or_the_wheel_ships_a_site_with_no_assets(self):
        data = tomllib.loads((ROOT / "pyproject.toml").read_text())
        patterns = data["tool"]["setuptools"]["package-data"]
        mine = patterns.get("parody_web_readaloud", [])
        self.assertIn("static/parody_web_readaloud/js/*.js", mine)
        self.assertIn("static/parody_web_readaloud/css/*.css", mine)
        self.assertIn("templates/parody_web/*.html", mine)

    def test_the_readalong_extra_names_its_dependencies(self):
        data = tomllib.loads((ROOT / "pyproject.toml").read_text())
        extra = data["project"]["optional-dependencies"]["readalong"]
        joined = " ".join(extra)
        self.assertIn("boto3", joined)
        self.assertIn("PyMuPDF", joined)

    def test_the_bundle_is_committed(self):
        bundle = ROOT / ("parody_web_readaloud/static/parody_web_readaloud"
                         "/js/readalong.js")
        self.assertTrue(bundle.exists(), "run `npm run build` and commit it")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python runtests.py`
Expected: FAIL — `parody_web_readaloud` absent from package-data

- [ ] **Step 3: Write minimal implementation**

`parody_web_readaloud/static/parody_web_readaloud/css/readalong.css`:

```css
/* The karaoke mark sits above the page canvas and the ink layer, but below
   the toolbar. It never takes pointer events: the pen must reach the page. */
.readalong-highlight {
  position: absolute;
  inset: 0;
  z-index: 3;
  pointer-events: none;
}

/* The answer, on paper-coloured stock so it stays legible over whatever line
   of prose it covers. Above the blank; see reveal.js. */
.readalong-reveal {
  position: absolute;
  z-index: 4;
  padding: 0.15rem 0.45rem;
  border-radius: 0.2rem;
  background: var(--parody-paper, #fdfcf8);
  color: var(--parody-ink, #1b1a17);
  border: 1px solid color-mix(in srgb, var(--parody-ink, #1b1a17) 25%, transparent);
  box-shadow: 0 2px 8px rgb(0 0 0 / 18%);
  font-family: 'Palatino', 'Palatino Linotype', 'Source Serif 4', serif;
  white-space: nowrap;
  opacity: 1;
  transition: opacity 900ms ease-out;
}

.readalong-reveal.is-fading { opacity: 0; }

.readalong-reveal[data-kind='figure'] {
  white-space: normal;
  max-width: 100%;
}

.readalong-reveal[data-kind='figure'] img {
  display: block;
  max-width: 100%;
  height: auto;
}

/* Dark mode: the page canvas is inverted by a CSS filter, but this layer is
   not — so its colours are chosen here rather than inherited and flipped. */
[data-dark='1'] .readalong-reveal {
  background: #26241f;
  color: #f2eee4;
}
```

`parody_web_readaloud/templates/parody_web/_pdf_view_head.html`:

```html
{% load parody_web_annotate %}{% load parody_web_readaloud %}{% annotate_head %}{% readalong_head %}
```

`parody_web_readaloud/templatetags/parody_web_readaloud.py`:

```python
"""The head tag that loads read-along.

Kept separate from the annotator's so that shadowing one template pulls in
both: read-along adds to the viewer, it never replaces it.
"""

from django import template
from django.templatetags.static import static
from django.utils.html import format_html

register = template.Library()


@register.simple_tag
def readalong_head():
    return format_html(
        '<link rel="stylesheet" href="{}">'
        '<script type="module" src="{}" defer></script>',
        static("parody_web_readaloud/css/readalong.css"),
        static("parody_web_readaloud/js/readalong.js"),
    )
```

In `pyproject.toml` add to `[tool.setuptools.package-data]`:

```toml
parody_web_readaloud = [
    "static/parody_web_readaloud/js/*.js",
    "static/parody_web_readaloud/css/*.css",
    "templates/parody_web/*.html",
]
```

and to `[project.optional-dependencies]`:

```toml
readalong = ["boto3>=1.34", "PyMuPDF>=1.24"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python runtests.py && node --test assets/readaloud/*.test.js`
Expected: both green

- [ ] **Step 5: Commit**

```bash
git add parody_web_readaloud/static/ parody_web_readaloud/templates/ parody_web_readaloud/templatetags/ pyproject.toml parody_web_readaloud/tests_packaging.py
git commit -m "read-along: styling, head wiring, and packaging"
```

---

### Task 12: Host documentation and the version bump

**Files:**
- Modify: `docs/host-integration.md`
- Modify: `pyproject.toml` (version), `uv.lock`
- Modify: `README.md`

- [ ] **Step 1: Document the seam**

Add a section to `docs/host-integration.md` covering: the `key`-mode artifact the host must import and the `Section.key_html` field it lands in; `PARODY_WEB_READALOUD_CACHE`; `INSTALLED_APPS` order (read-along **before** `parody_web`, alongside the annotator); the `readalong` extra; the `generate_readalong` command; and the fact that audio is never synthesised on a request, so a host that never runs the command simply has no read-along and nothing breaks.

- [ ] **Step 2: Bump the version**

Re-derive the version against `origin/main` at merge time, not now — parallel sessions move it, and an identical version on both sides merges without conflict and silently ships a duplicate release. Assuming main is still 0.49.x, this is a minor bump: **0.50.0**.

```bash
git fetch origin && git log --oneline -1 origin/main
```

Edit `pyproject.toml`'s `version`, then update the lock — `uv.lock` pins the project's own version, and a bump touching only `pyproject.toml` leaves it stale:

```bash
uv lock
```

- [ ] **Step 3: Full suite**

Run: `python runtests.py && node --test assets/annotate/*.test.js assets/readaloud/*.test.js`
Expected: all green

- [ ] **Step 4: Commit**

```bash
git add docs/host-integration.md README.md pyproject.toml uv.lock
git commit -m "0.50.0: read-along, the TTS-paced cloze reading mode"
```

---

## Self-Review

**Spec coverage.** Every spec section maps to a task: the `key`-mode source (T1, T7), geometry and rules (T2), alignment with its self-classifying disagreements (T3), math via the SRE seam with `SkipMath` as the decided fallback (T4), the app and its order check (T5), `slice_key` identity (T6), serve-only endpoints and inherited access (T8), karaoke (T9), reveal-hold-continue and the figure-into-the-pad case (T10), theming and packaging (T11), host docs (T12).

**Two spec items deliberately deferred, and they must not be claimed as done:**

1. **Skip-ahead over a long math region.** The spec calls for it; no task implements it. It needs math regions to carry `start_ms`/`end_ms` the way clozes do — `build_track` already groups timings by token, so the data is there, but neither the payload nor the client exposes it. Add as a follow-up task once the interaction is on screen.
2. **`Section.key_html`.** `generate_readalong.key_mode_html` reads it and skips the section when absent, so the pipeline degrades honestly rather than silently using answer-free blank-mode HTML. But nothing in this plan makes the host *populate* it — that is homepage-django importer work, outside this repo. T12 documents the requirement; the first end-to-end run will need it.

**Type consistency.** `Token` fields are consistent across T1/T3/T4. `Placed.box` is a 4-tuple everywhere. `words[]` entries carry `token`, `page`, `x0..y1`, `start_ms`, `end_ms` from T7 through T8's JSON to T9's `wordAt`. `clozes[]` carry `kind`, `answer`, `src`, `page`, box, and the time window used by `clozeAt`. `Highlight.show` and `placeReveal` both take `[x0, y0, x1, y1]` in PDF points and both go through `viewport.convertToViewportRectangle`.

**One known rough edge:** T10's `layerFor` returns `null` when the page holding the current word has had its canvas released — pdf.js keeps only about three. The frame loop then skips the highlight for that word while `scrollTo` is also inert, so a fast-forward into a distant page shows nothing until the reader scrolls. Correct behaviour is to drive the page view to that page and await the render. This is called out in the spec's risks; fix it during T10 execution if it bites in practice, and do not close the task claiming smooth playback without checking.
