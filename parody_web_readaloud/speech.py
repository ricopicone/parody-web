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

    `macros` is passed through to MathJax so a book's own \\newcommand set can
    be resolved; without it, an expression using a custom macro is silently
    unspeakable.
    """

    def __init__(self, node="node", timeout=300.0, macros=None):
        self.node = node
        self.timeout = timeout
        self.macros = macros or {}

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
    said_by_index = dict(zip(math_positions, spoken_math))

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
