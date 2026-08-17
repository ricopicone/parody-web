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
    # Punctuation that followed this token with no space before it. Kept here
    # rather than as a token of its own: the PDF glues punctuation to the word
    # it follows, so a standalone "," would have no counterpart to align
    # against, and its alignment key (punctuation stripped) is the empty
    # string, which matches anything. It is still spoken, for the prosody.
    trail: str = ""


def _strip_delims(raw: str) -> str:
    """Drop pandoc's \\(…\\) or \\[…\\] wrapper, leaving the expression."""
    for open_, close in (("\\(", "\\)"), ("\\[", "\\]")):
        if raw.startswith(open_) and raw.endswith(close):
            return raw[len(open_):-len(close)].strip()
    return raw


class _ScriptParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tokens = []
        self._skip_depth = 0
        self._math = None                  # "inline" | "display" while open
        self._cloze = False
        self._buf = []

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
            self._cloze = True
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
        if tag == "span" and self._math:
            raw = "".join(self._buf).strip()
            self.tokens.append(Token(kind="math", latex=_strip_delims(raw),
                                     display=self._math == "display"))
            self._math, self._buf = None, []
        elif tag == "span" and self._cloze:
            words = "".join(self._buf).split()
            self.tokens.append(Token(kind="cloze", answer=words,
                                     text=" ".join(words)))
            self._cloze, self._buf = False, []

    def handle_data(self, data):
        if self._skip_depth:
            return
        if self._math is not None or self._cloze:
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
