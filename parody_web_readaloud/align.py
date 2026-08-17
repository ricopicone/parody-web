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
import itertools
import re
import unicodedata
from dataclasses import dataclass

# Math extracts as mathematical-alphanumeric codepoints (U+1D400..U+1D7FF),
# which NFKD folds back to the Latin letters the aligner can compare against.
_PUNCT = re.compile(r"[^\w]", re.UNICODE)

# Tokens that normalise to nothing (a dash, a lone symbol) would otherwise be
# equal to each other and to any other empty key, matching arbitrary places on
# the page. Give each one a private key instead so it simply never matches.
_UNIQUE = itertools.count()


@dataclass
class Placed:
    token: object
    index: int
    page: int = None
    box: tuple = None


def _fold(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text)
    return _PUNCT.sub("", folded).casefold()


def _key(text: str) -> str:
    return _fold(text) or f"\x00empty{next(_UNIQUE)}"


def _token_key(token) -> str:
    if token.kind == "word":
        return _key(token.text)
    if token.kind == "math":
        return _key(token.latex)
    # Clozes and figure clozes are never printed, so they must never match a
    # word on the page. Their position comes from the rules instead.
    return f"\x00cloze{next(_UNIQUE)}"


def _join(boxes):
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def align(tokens: list, words: list, rules: list) -> list:
    placed = [Placed(token=t, index=i) for i, t in enumerate(tokens)]

    a = [_token_key(t) for t in tokens]
    b = [_key(w.text) for w in words]
    matcher = difflib.SequenceMatcher(a=a, b=b, autojunk=False)

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(i2 - i1):
                _place(placed[i1 + offset], [words[j1 + offset]])
        elif tag == "replace":
            # A hyphenated break is the common case here: several page words
            # collapsing onto one token. Give every token in the run the run's
            # whole extent rather than guessing a split.
            run = words[j1:j2]
            if run:
                for p in placed[i1:i2]:
                    _place(p, run)

    _attach_rules([p for p in placed
                   if p.token.kind in ("cloze", "figure_cloze")], rules)
    return placed


def _place(p: Placed, run: list):
    if p.token.kind in ("cloze", "figure_cloze"):
        return                     # never takes a box from prose
    p.page = run[0].page
    p.box = _join([(w.x0, w.y0, w.x1, w.y1) for w in run])


def _attach_rules(clozes: list, rules: list):
    """The nth unprinted token gets the nth rule, in reading order.

    Both sequences are in document order, so position is the whole join. A
    cloze with no rule left over keeps `box=None`, and the client skips it
    rather than revealing over the wrong part of the page.
    """
    for cloze, rule in zip(clozes, rules):
        cloze.page = rule["page"]
        cloze.box = (rule["x0"], rule["y0"], rule["x1"], rule["y1"])
