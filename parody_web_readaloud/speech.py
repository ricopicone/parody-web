"""What gets said, and which script token said it.

`build_speech` returns the text handed to the TTS engine together with an owner
index per spoken word. Polly's speech marks are BYTE offsets into exactly
this text, so the owners list is what turns a timing into a box.

Math speech is a seam with two implementations. SRE is a JavaScript library, so
speaking math costs a Node subprocess — acceptable at generation time, which is
never a request path, and unreachable from one. `SkipMath` is the sanctioned
fallback from the spec: the voice carries the prose, the eye carries the
equation. Unlike the HTML reading mode, the eye here is on properly typeset
math, which is what makes that fallback defensible.

The seam is `speak_all`, not `speak`, because it must batch: SRE's engine setup
costs about a second and a chapter carries thousands of expressions.
"""

import json
import re
import subprocess
from pathlib import Path

def _sre_script():
    """Where the maths-speech helper lives.

    `PARODY_WEB_READALOUD_SRE` wins, and is how a host makes spoken maths work:
    speech-rule-engine resolves its own package data relative to where it is
    installed, so it cannot be bundled into a single file and shipped in the
    wheel — the script has to sit somewhere its two npm dependencies resolve.

        mkdir -p /srv/parody/sre && cd /srv/parody/sre
        npm install mathjax-full speech-rule-engine
        cp <site-packages>/parody_web_readaloud/static/parody_web_readaloud/js/speak.mjs .
        export PARODY_WEB_READALOUD_SRE=/srv/parody/sre/speak.mjs

    Absent that, a source checkout still works (its node_modules are there),
    and an installed wheel finds its own copy — which will fail to resolve its
    imports and fall back to silence. Loudly enough: see `sre_available`.
    """
    from django.conf import settings

    override = getattr(settings, "PARODY_WEB_READALOUD_SRE", "") or ""
    if override:
        return Path(override)
    here = Path(__file__).resolve().parent
    source = here.parent / "assets" / "readaloud-sre" / "speak.mjs"
    if source.exists():
        return source
    return here / "static" / "parody_web_readaloud" / "js" / "speak.mjs"


def sre_available(node="node"):
    """Can maths actually be spoken here? Returns (ok, why-not).

    Worth asking before a long generation run: SreMath treats every failure as
    silence, so a misconfigured host produces a whole book of tracks with the
    equations missing and says nothing about it.
    """
    script = _sre_script()
    if not script.exists():
        return False, f"no speak.mjs at {script}"
    try:
        done = subprocess.run(
            [node, str(script)], input='{"items":[{"latex":"x","display":false}]}',
            capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as err:
        return False, f"could not run node: {err}"
    if done.returncode != 0:
        first = (done.stderr or "").strip().splitlines()
        return False, (first[0] if first else "speak.mjs exited non-zero")
    try:
        texts = (json.loads(done.stdout or "{}") or {}).get("texts") or []
    except ValueError:
        return False, "speak.mjs produced no JSON"
    if not texts or not texts[0]:
        return False, "speak.mjs produced no speech"
    return True, ""


_LINE_COUNT = re.compile(r"^\s*\d+\s+lines\s+", re.IGNORECASE)
_LINE_MARK = re.compile(r"\s*\bline\s+\d+\s*:\s*(blank\s+)?",
                        re.IGNORECASE)


def tidy_math_speech(said: str) -> str:
    """Take SRE's line scaffolding out of a spoken equation.

    A multi-line equation comes back as

        "3 lines Line 1: v sub o equals A ... Line 2: blank equals A ..."

    The counts and the "Line N:" markers are structure spoken aloud, and the
    "blank" is SRE naming the empty left-hand cell of an aligned continuation —
    so a reader hears "line two, blank equals" in the middle of a derivation.
    The reader judged all three to be noise (task #615).

    Each marker becomes a full stop, so the lines still separate audibly: a
    derivation read as one unbroken sentence is worse than one read with the
    scaffolding in it.

    NOTE this changes the spoken text, and the spoken text is what `text_key`
    hashes — so changing anything here re-synthesises every section containing
    display maths, at Polly's per-character rate. It is not a free edit.
    """
    if not said:
        return said
    out = _LINE_COUNT.sub("", said)
    out = _LINE_MARK.sub(". ", out)
    return out.lstrip(". ").strip()


# Bumped whenever what `build_speech` says changes, so a fingerprinted engine
# (Kokoro: see `pronounce.engine_id`) knows its recordings describe an older
# script and re-voices the sections whose words moved. "2": simple subscripts
# are read without "sub" (task 981).
SPEECH_VERSION = "2"

# A subscript on one of these is a LIMIT ("the sum from k equals 0"), which SRE
# never reads as "sub" — so it is neither simple nor compound for the rule.
_LIMIT_OPERATORS = {
    "sum", "prod", "int", "oint", "lim", "max", "min", "sup", "inf",
    "bigcup", "bigcap",
}
_WORD_WRAPPERS = {"text", "mathrm", "mathbf", "mathit", "mathsf",
                  "operatorname"}
_SIMPLE_SUBSCRIPT = re.compile(r"^\s*(?:[A-Za-z0-9]+|\\[A-Za-z]+)\s*$")
_SUB_WORD = re.compile(r"(?<!\S)sub(?!\S)\s*")
_COMMAND = re.compile(r"\\([A-Za-z]+|.)")


def _braced(latex, start):
    """The balanced `{...}` group opening at `start`: (inner, end index)."""
    depth, i = 0, start
    while i < len(latex):
        if latex[i] == "\\":
            i += 2                      # an escaped brace is not a brace
            continue
        if latex[i] == "{":
            depth += 1
        elif latex[i] == "}":
            depth -= 1
            if depth == 0:
                return latex[start + 1:i], i + 1
        i += 1
    return latex[start + 1:], len(latex)


def _subscripts(latex):
    """Each subscript's argument, skipping escaped `\\_` and operator limits."""
    found, i = [], 0
    while i < len(latex):
        if latex[i] == "\\":
            i += len(_COMMAND.match(latex, i).group(0)) if \
                _COMMAND.match(latex, i) else 1
            continue
        if latex[i] != "_":
            i += 1
            continue
        # What is this `_` attached to? Look back past \limits / \nolimits.
        before = re.sub(r"\\(?:no)?limits\s*$", "", latex[:i]).rstrip()
        base = re.search(r"\\([A-Za-z]+)$", before)
        j = i + 1
        while j < len(latex) and latex[j] == " ":
            j += 1
        if j >= len(latex):
            break
        if latex[j] == "{":
            arg, end = _braced(latex, j)
        elif latex[j] == "\\":
            command = _COMMAND.match(latex, j)
            arg, end = command.group(0), j + len(command.group(0))
            if command.group(1) in _WORD_WRAPPERS and \
                    end < len(latex) and latex[end] == "{":
                inner, end = _braced(latex, end)
                arg = f"{arg}{{{inner}}}"
        else:
            arg, end = latex[j], j + 1
        if not (base and base.group(1) in _LIMIT_OPERATORS):
            found.append(arg)
        i = end
    return found


def _is_simple(arg):
    wrapped = re.match(r"^\s*\\([A-Za-z]+)\s*\{(.*)\}\s*$", arg, re.DOTALL)
    if wrapped and wrapped.group(1) in _WORD_WRAPPERS:
        arg = wrapped.group(2).replace("\\_", "")
    return bool(_SIMPLE_SUBSCRIPT.match(arg))


def subscripts_are_simple(latex: str) -> bool:
    """True when every subscript in `latex` is one symbol, or one word.

    Simple: digits, letters, a single Greek letter or other command, or a word
    in `\\text{}` / `\\mathrm{}` and the like. Compound: anything holding an
    operator, relation, comma, fraction, parenthesis or a nested script. Limits
    on \\sum, \\int, \\lim and friends are not subscripts for this purpose.
    """
    return all(_is_simple(arg) for arg in _subscripts(latex or ""))


def terse_subscripts(said: str, latex: str) -> str:
    """Drop the word "sub" from spoken maths whose subscripts are all simple.

    SRE never marks where a subscript ENDS, so "v sub 1 i sub 1" can lose its
    "sub"s safely ("v 1 i 1"), while "a sub n minus 1" cannot: there "sub" is
    the only cue that a subscript began, and without it a_{n-1} sounds like
    a·n − 1. So an expression holding any compound subscript keeps every "sub".

    NOTE this changes the spoken text, and the spoken text is what `text_key`
    hashes — so it changes the key of every section with subscripted maths.
    """
    if not said or not subscripts_are_simple(latex):
        return said
    return _SUB_WORD.sub("", said).strip()


class SkipMath:
    """Say nothing for math."""

    def speak_all(self, items):
        return [None] * len(items)

    def render_all(self, items):
        return [None] * len(items)


class SreMath:
    """Speak math via MathJax's Speech Rule Engine, through Node.

    Falls back to silence rather than raising: a host without Node, or an
    expression SRE cannot parse, should cost that equation its narration and
    nothing else.

    `macros` is passed through to MathJax so the books' own macros resolve.
    It defaults to the SAME list the web page typesets with
    (`parody_web.mathjax.MACROS`). It used to default to none, and an
    undefined macro does not fail here: MathJax keeps its name as text and SRE
    reads that aloud, so every \\bm{x} in a voiced section was spoken as
    "backslash B M x". Pass `macros={}` to really mean none.
    """

    def __init__(self, node="node", timeout=300.0, macros=None):
        from parody_web.mathjax import MACROS

        self.node = node
        self.timeout = timeout
        self.macros = MACROS if macros is None else macros

    @property
    def script(self):
        return _sre_script()

    def speak_all(self, items):
        return [tidy_math_speech(said) for said in self._call(items)["texts"]]

    def render_all(self, items):
        """SVG per expression, for the blanks that have to reveal one."""
        return self._call(items, render=True)["svgs"]

    def _call(self, items, render=False):
        if not items:
            return {"texts": [], "svgs": []}
        payload = {"items": [{"latex": latex, "display": bool(display),
                              "render": render}
                             for latex, display in items],
                   "macros": self.macros}
        reply = self._invoke(payload) or {}
        out = {}
        for field in ("texts", "svgs"):
            values = reply.get(field) or []
            # Never let a short reply shift every later expression's narration.
            if len(values) != len(items):
                values = [None] * len(items)
            out[field] = [(v or "").strip() or None if isinstance(v, str)
                          else None for v in values]
        return out

    def _invoke(self, payload):
        """Run the Node helper. Returns the parsed reply, or None if it failed.

        Split out so the failure paths can be exercised without a subprocess.
        """
        try:
            done = subprocess.run(
                [self.node, str(_sre_script())],
                input=json.dumps(payload),
                capture_output=True, text=True, timeout=self.timeout,
                check=True)
            return json.loads(done.stdout or "{}") or {}
        except (OSError, ValueError, subprocess.SubprocessError):
            return None


def build_speech(tokens, math=None):
    """Return (text_for_tts, owner_index_per_spoken_word).

    `len(owners) == len(text.split())` is the contract generate.py resolves
    Polly's BYTE offsets against — byte, because that is what Polly reports and
    counting characters instead desynchronises at the first curly quote.
    """
    math = math or SkipMath()

    # A cloze block usually hides an equation rather than words, so it needs
    # the maths engine too — and it must go in the SAME batch, or a section
    # full of them pays the engine's start-up cost once per blank.
    math_positions = [i for i, t in enumerate(tokens)
                      if t.latex and t.kind in ("math", "cloze")]
    spoken_math = math.speak_all(
        [(tokens[i].latex, tokens[i].display) for i in math_positions])
    said_by_index = {i: terse_subscripts(said, tokens[i].latex)
                     for i, said in zip(math_positions, spoken_math)}

    words = []
    owners = []

    for index, token in enumerate(tokens):
        if token.kind == "word":
            spoken = [token.text]
        elif token.kind == "cloze":
            if token.latex:
                said = said_by_index.get(index)
                spoken = said.split() if said else []
            else:
                spoken = list(token.answer)
        elif token.kind == "math":
            said = said_by_index.get(index)
            spoken = said.split() if said else []
        else:                       # figure_cloze — nothing to say
            spoken = []

        if spoken and token.trail:
            spoken[-1] = spoken[-1] + token.trail

        for word in spoken:
            words.append(word)
            owners.append(index)

    return " ".join(words), owners
