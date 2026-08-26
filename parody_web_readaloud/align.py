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


# A hyphenated break is one token against two page words. Allow a little more
# than that for ligatures and odd glyph splits, but nothing resembling a
# structural divergence.
MAX_LOCAL_TOKENS = 2
MAX_LOCAL_WORDS = 4


def _is_local(tokens: int, page_words: int) -> bool:
    return tokens <= MAX_LOCAL_TOKENS and page_words <= MAX_LOCAL_WORDS


def _sole_equation(placed: list, i1: int, i2: int):
    """The index of the block's ONE display-math token, or None.

    Not "a block that is a single token": an equation is very often grouped
    with a stray neighbour — a word the page renders differently, an inline
    symbol that extracted oddly — and thirteen clozed equations in the
    electronics primer fell outside the first version of this rule by exactly
    that margin. Each of them showed a reader a blank with no prompt beneath
    it. Two display equations in one block stay unplaced: which of them the
    run belongs to is not knowable, and a box on the wrong equation is worse
    than no box.

    Only that token is placed, never the block. Handing every token in a large
    block one box is precisely what the cap exists to prevent.

    A display equation is a SINGLE token that typesets as MANY extracted
    chunks — a line, a relation symbol, the fragments either side of a blank —
    and its alignment key is the whole LaTeX string, which can never equal any
    one of them. The local-replace hatch below is therefore the only route by
    which maths is ever placed, and a cap sized for a hyphenated line break
    denies it to anything longer than a one-liner: on the primer's opamp
    section six of twelve derivations extracted as 5 to 48 chunks and so took
    no box at all. An equation with no box freezes the karaoke mark for the
    whole minute SRE spends narrating it, which reads as the highlight
    skipping the passage.

    Widened for ONE token only, deliberately. What the cap exists to prevent
    is hundreds of TOKENS sharing a box spanning half a page while counting as
    placed; a single token taking the extent it typeset to is its own box by
    construction. Prose keeps the tight cap, where a long run really is a
    divergence and unplaced is the honest outcome.
    """
    found = [i for i in range(i1, i2)
             if placed[i].token.kind == "math" and placed[i].token.display]
    return found[0] if len(found) == 1 else None


# Maths extracts as mathematical-alphanumeric codepoints and operator glyphs;
# prose does not. That is the same fact the fold at the top of this module
# relies on, used here for the opposite purpose.
_MATHS_GLYPH = re.compile(r"[\U0001D400-\U0001D7FF"
                          r"\u2200-\u22FF\u27F0-\u27FF\u2A00-\u2AFF"
                          r"\u0391-\u03C9\u2212\u00D7\u221A\u2211\u222B]")


def _looks_like_maths(run: list) -> bool:
    """Whether a page run could be the typeset form of an equation.

    The guard on giving a lone equation a whole block. Without it, an equation
    whose glyphs are not on this page at all takes a box over whatever prose
    happens to lie between its neighbours — placed, and pointing at nothing,
    which is the failure the cap exists to prevent rather than a version of it.
    """
    return any(_MATHS_GLYPH.search(w.text or "") for w in run)


def _join(boxes):
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def _anchors(a: list, b: list) -> list:
    """Patience anchors: tokens occurring exactly once in each stream.

    Plain LCS matching goes wrong on a section-sized pair. Prose is mostly
    common words, so the longest common subsequence is free to pair "the" in
    one place with "the" in another, and a footnote or float that interleaves
    the two streams can send it down a path that abandons a whole passage —
    on the primer's opamp section it left 397 tokens unmatched against text
    that plainly appears on the page.

    Words unique on both sides cannot be paired wrongly, so the longest
    increasing run of them is a skeleton the rest can be fitted around.
    """
    from collections import Counter

    count_a, count_b = Counter(a), Counter(b)
    where_b = {}
    for j, key in enumerate(b):
        if count_b[key] == 1:
            where_b[key] = j

    pairs = [(i, where_b[key]) for i, key in enumerate(a)
             if count_a[key] == 1 and key in where_b]

    # Longest increasing subsequence on the b-positions keeps the skeleton
    # monotonic; a moved passage simply drops out of it.
    best, parent = [], [-1] * len(pairs)
    tails = []
    for index, (_, j) in enumerate(pairs):
        lo, hi = 0, len(tails)
        while lo < hi:
            mid = (lo + hi) // 2
            if pairs[tails[mid]][1] < j:
                lo = mid + 1
            else:
                hi = mid
        if lo:
            parent[index] = tails[lo - 1]
        if lo == len(tails):
            tails.append(index)
        else:
            tails[lo] = index
    if tails:
        node = tails[-1]
        while node != -1:
            best.append(pairs[node])
            node = parent[node]
        best.reverse()
    return best


def _segments(a: list, b: list):
    """(i1, i2, j1, j2) windows between successive anchors, anchors included."""
    anchors = _anchors(a, b)
    if not anchors:
        yield 0, len(a), 0, len(b)
        return
    prev_i = prev_j = 0
    for i, j in anchors:
        yield prev_i, i, prev_j, j
        yield i, i + 1, j, j + 1          # the anchor itself
        prev_i, prev_j = i + 1, j + 1
    yield prev_i, len(a), prev_j, len(b)


def align(tokens: list, words: list, rules: list) -> list:
    placed = [Placed(token=t, index=i) for i, t in enumerate(tokens)]

    a = [_token_key(t) for t in tokens]
    b = [_key(w.text) for w in words]

    for si, ei, sj, ej in _segments(a, b):
        if si >= ei and sj >= ej:
            continue
        _align_window(placed, words, a, b, si, ei, sj, ej)

    _attach_rules(placed, rules)
    return placed


def _align_window(placed, words, a, b, si, ei, sj, ej):
    """Match one window between anchors, where LCS is safe to use."""
    matcher = difflib.SequenceMatcher(a=a[si:ei], b=b[sj:ej], autojunk=False)

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        i1, i2, j1, j2 = i1 + si, i2 + si, j1 + sj, j2 + sj
        if tag == "equal":
            for offset in range(i2 - i1):
                _place(placed[i1 + offset], [words[j1 + offset]])
        elif tag == "replace":
            run = words[j1:j2]
            if not run:
                continue
            if _is_local(i2 - i1, j2 - j1):
                # ONLY a small local disagreement — a hyphenated line break, a
                # ligature, a symbol that extracted oddly. Give every token in
                # the run the run's whole extent rather than guessing a split.
                #
                # Bounded deliberately. Applied to any replace block, one large
                # divergence hands hundreds of tokens a single box spanning
                # half a page: they then count as "placed" while pointing at
                # nothing, and every cloze after them gets a window derived
                # from that garbage. Unplaced is the honest outcome for a run
                # this size.
                for p in placed[i1:i2]:
                    _place(p, run)
            else:
                only = _sole_equation(placed, i1, i2)
                if only is not None and _looks_like_maths(run):
                    _place(placed[only], run)


def _place(p: Placed, run: list):
    if p.token.kind in ("cloze", "figure_cloze"):
        return                     # never takes a box from prose
    # The run's FIRST page only. An equation broken over a page break
    # extracts as chunks on both, and a box joined across them describes
    # nowhere at all — it spans the gutter and lands on neither page.
    page = run[0].page
    here = [w for w in run if w.page == page]
    p.page = page
    p.box = _join([(w.x0, w.y0, w.x1, w.y1) for w in here])


def _attach_rules(placed: list, rules: list):
    """Give each cloze the blank that lies between its neighbours on the page.

    NOT simply the nth rule for the nth cloze. A page carries flat strokes that
    are not blanks — table rules, dividers — and on the electronics primer a
    full-measure filter still left 24 candidate regions for 21 clozes. Handing
    them out in order puts three clozes on the wrong rule and shifts every one
    after them.

    A cloze sits between two pieces of prose whose boxes the alignment already
    knows, so the blank has to lie between them in reading order. That rejects
    strays structurally rather than by tuning a threshold, and it degrades
    honestly: a cloze with no candidate in its window keeps `box=None`, and the
    client stays silent about it instead of revealing over the wrong place.
    """
    # The window runs from the TOP of the preceding word to the BOTTOM of the
    # following one, not between their baselines: an inline blank shares a line
    # with its neighbours, so its rule sits below their y0 while still
    # belonging between them.
    def top(p):
        return (p.page, p.box[1]) if p.box else None

    def bottom(p):
        return (p.page, p.box[3]) if p.box else None

    taken = set()
    for index, p in enumerate(placed):
        if p.token.kind not in ("cloze", "figure_cloze"):
            continue

        lo = next((top(q) for q in reversed(placed[:index]) if q.box), None)
        hi = next((bottom(q) for q in placed[index + 1:] if q.box), None)

        for number, rule in enumerate(rules):
            if number in taken:
                continue
            here = (rule["page"], rule["y0"])
            if lo is not None and here < lo:
                continue
            if hi is not None and here > hi:
                break
            taken.add(number)
            p.page = rule["page"]
            p.box = (rule["x0"], rule["y0"], rule["x1"], rule["y1"])
            break
