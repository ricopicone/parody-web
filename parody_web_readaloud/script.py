"""The ordered stream of things to say, read out of a `--clozes key` artifact.

The text source is deliberately the HTML and not the PDF. Everything that makes
PDF text hard — running heads, folios, hyphenation, mangled math spacing, page
breaks — is an artifact of reading text back out of a typeset page, and none of
it exists here.

`key` mode is the one that carries answers AND marks them: `filter.lua:775`
wraps them in `<span class="cloze-key">`, and because the mode is not `blank`,
`cloze_variant_src` returns nil so figures render complete. Blank mode strips
both on purpose and must never be used as the source here.
"""

from dataclasses import dataclass, field
from html.parser import HTMLParser

# Read aloud: prose only. Captions are excluded because LaTeX floats move them
# out of reading order on the page, so they would never align — see the spec's
# "Known limit: float reordering".
SKIP_TAGS = {"script", "style", "figcaption", "table"}


@dataclass
class Token:
    kind: str                              # word | math | cloze | figure_cloze
    text: str = ""
    latex: str = ""
    display: bool = False
    answer: list = field(default_factory=list)
    src: str = ""
    # A maths token can HIDE something: the author clozes part of an equation
    # rather than the whole of it, and key mode marks the answer with
    # \class{cloze-key}{...} INSIDE the maths. `blanks` counts those marks and
    # `plain` is the equation with them unwrapped — the complete equation, for
    # the picture a blank reveals. `latex` is left exactly as it arrived,
    # because it is what the aligner keys on and what SRE is given to speak.
    blanks: int = 0
    plain: str = ""
    # Punctuation that followed this token with no space before it. Kept here
    # rather than as a token of its own: the PDF glues punctuation to the word
    # it follows, so a standalone "," would have no counterpart to align
    # against, and its alignment key (punctuation stripped) is the empty
    # string, which matches anything. It is still spoken, for the prosody.
    trail: str = ""


CLOZE_KEY = "\\class{cloze-key}{"


def strip_cloze_markers(latex: str) -> "tuple[str, int]":
    """`\\class{cloze-key}{X}` -> `X`, and how many were unwrapped.

    Brace-matched rather than regexed: the thing being hidden is maths, so it
    is full of braces — `\\class{cloze-key}{\\frac{v} {i}}` ends at the LAST
    brace, not the first, and a non-greedy pattern silently keeps half an
    equation.

    The marker is stripped for RENDERING only. It is transparent to MathJax and
    to SRE — verified: both forms speak as "Z equals v over i period" — so the
    spoken text, and therefore the audio anyone has already paid for, does not
    depend on which form is used. But the class reaches the rendered SVG, where
    a stylesheet that hides `.cloze-key` would hide the very answer the reveal
    exists to show.
    """
    out, count, i = [], 0, 0
    while True:
        at = latex.find(CLOZE_KEY, i)
        if at < 0:
            out.append(latex[i:])
            return "".join(out), count
        out.append(latex[i:at])
        depth, j = 1, at + len(CLOZE_KEY)
        while j < len(latex) and depth:
            if latex[j] == "{":
                depth += 1
            elif latex[j] == "}":
                depth -= 1
                if not depth:
                    break
            j += 1
        if j >= len(latex):                # unbalanced: leave it alone
            out.append(latex[at:])
            return "".join(out), count
        out.append(latex[at + len(CLOZE_KEY):j])
        count += 1
        i = j + 1


def _strip_delims(raw: str) -> str:
    """Drop pandoc's \\(…\\) or \\[…\\] wrapper, leaving the expression."""
    for open_, close in (("\\(", "\\)"), ("\\[", "\\]")):
        if raw.startswith(open_) and raw.endswith(close):
            return raw[len(open_):-len(close)].strip()
    return raw


# TeX's specials, for prose being put inside \text{}.
_TEX_SPECIAL = {"\\": "\\textbackslash{}", "{": "\\{", "}": "\\}",
                "$": "\\$", "&": "\\&", "%": "\\%", "#": "\\#",
                "_": "\\_", "^": "\\^{}", "~": "\\~{}"}


def _tex_text(prose: str) -> str:
    return "".join(_TEX_SPECIAL.get(c, c) for c in prose)


def _inline_cloze_token(parts: list) -> Token:
    """One inline cloze, from its prose and maths parts in order.

    An answer that is partly or wholly maths becomes a MATHS cloze: the parts
    are stitched into one expression, prose wrapped in \\text{}, so the single
    picture the reveal shows is the whole answer and SRE speaks the whole
    answer. A purely verbal answer is left exactly as it was.
    """
    if not any(kind == "math" for kind, _ in parts):
        words = "".join(value for _, value in parts).split()
        return Token(kind="cloze", answer=words, text=" ".join(words))

    latex, readable = [], []
    for kind, value in parts:
        if kind == "math":
            latex.append(value)
            readable.append(value)
            continue
        if not value.strip():
            continue
        latex.append(f"\\text{{{_tex_text(value.strip())}}}")
        readable.append(value.strip())
    # `text` is the fallback the reveal falls back to if the picture cannot be
    # drawn — better a line of source than a blank with nothing under it.
    return Token(kind="cloze", latex=" ".join(latex),
                 text=" ".join(readable),
                 answer=" ".join(readable).split())


def _block_cloze(raw: str) -> Token:
    """One `::: {.cloze}` block, as a single cloze token.

    A block usually hides display maths, in which case the token carries the
    LaTeX and no words: it is spoken through the maths engine, and the reveal
    has to render it rather than print it as text. A block of ordinary prose
    still yields words, so both forms come out of here.
    """
    body = raw.strip()
    latex = _strip_delims(body)
    if latex != body:                      # the whole block was one equation
        return Token(kind="cloze", latex=latex, display=True, text=body)
    words = body.split()
    return Token(kind="cloze", answer=words, text=" ".join(words))


class _ScriptParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tokens = []
        self._skip_depth = 0
        self._math = None                  # "inline" | "display" while open
        self._inline_cloze = False
        # An inline cloze can HIDE MATHS — "\\cloze{$V_e$}" — and the answer is
        # then a mixture of prose and expressions. Collected as parts so the
        # maths is not lost: opening a math span used to reset the buffer, so
        # the cloze ended up empty (invisible AND unspoken, because the answer
        # is also what is read aloud) and the maths was emitted as a token of
        # its own, which is never printed and so could never align.
        self._cloze_parts = []
        self._block_depth = 0              # >0 while inside a cloze block
        self._buf = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return

        # Everything inside a cloze block is the answer, maths included, so it
        # is buffered whole rather than handled tag by tag.
        if self._block_depth:
            if tag == "div":
                self._block_depth += 1
            return

        classes = (a.get("class") or "").split()
        if tag == "div" and "cloze-key-block" in classes:
            # A `::: {.cloze}` block, blanked to its own height in print. Its
            # content is usually display maths rather than words — all 21 of
            # the electronics primer's clozes are of this kind, and none are
            # inline.
            self._block_depth = 1
            self._buf = []
        elif tag == "span" and "math" in classes:
            if self._inline_cloze:
                self._cloze_parts.append(("text", "".join(self._buf)))
            self._math = "display" if "display" in classes else "inline"
            self._buf = []
        elif tag == "span" and "cloze-key" in classes:
            self._inline_cloze = True
            self._cloze_parts = []
            self._buf = []
        elif tag == "img" and a.get("data-cloze-of"):
            self.tokens.append(Token(kind="figure_cloze", src=a.get("src", "")))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag in SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return

        if self._block_depth:
            if tag != "div":
                return
            self._block_depth -= 1
            if self._block_depth:
                return
            self.tokens.append(_block_cloze("".join(self._buf)))
            self._buf = []
            return

        if tag == "span" and self._math:
            raw = "".join(self._buf).strip()
            latex = _strip_delims(raw)
            if self._inline_cloze:
                # Part of the answer, not a token. It is behind the blank, so
                # the page never prints it and an alignment could only fail.
                self._cloze_parts.append(("math", latex))
                self._math, self._buf = None, []
                return
            plain, blanks = strip_cloze_markers(latex)
            self.tokens.append(Token(kind="math", latex=latex,
                                     display=self._math == "display",
                                     blanks=blanks,
                                     plain=plain if blanks else ""))
            self._math, self._buf = None, []
        elif tag == "span" and self._inline_cloze:
            self._cloze_parts.append(("text", "".join(self._buf)))
            self.tokens.append(_inline_cloze_token(self._cloze_parts))
            self._inline_cloze, self._buf = False, []
            self._cloze_parts = []

    def handle_data(self, data):
        if self._skip_depth:
            return
        if self._block_depth:
            self._buf.append(data)
            return
        if self._math is not None or self._inline_cloze:
            self._buf.append(data)
            return
        # Punctuation abutting the previous element — the `, which` after a
        # cloze span — belongs to it, not to a token of its own.
        if self.tokens and data[:1] and not data[0].isspace():
            head = ""
            for char in data:
                if char.isspace() or char.isalnum():
                    break
                head += char
            if head:
                self.tokens[-1].trail += head
                data = data[len(head):]

        for word in data.split():
            self.tokens.append(Token(kind="word", text=word))


def parse_script(html: str) -> list:
    parser = _ScriptParser()
    parser.feed(html or "")
    parser.close()
    return parser.tokens
