"""What gets said, and which script token said it.

`build_speech` returns the text handed to the TTS engine together with an owner
index per spoken word. Polly's speech marks are character offsets into exactly
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
import subprocess
from pathlib import Path

SRE_SCRIPT = (Path(__file__).resolve().parent.parent
              / "assets" / "readaloud-sre" / "speak.mjs")


class SkipMath:
    """Say nothing for math."""

    def speak_all(self, items):
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

    def speak_all(self, items):
        if not items:
            return []
        payload = {"items": [{"latex": latex, "display": bool(display)}
                             for latex, display in items],
                   "macros": self.macros}
        reply = self._invoke(payload)
        if reply is None:
            return [None] * len(items)
        texts = reply.get("texts") or []
        # Never let a short reply shift every later expression's narration.
        if len(texts) != len(items):
            return [None] * len(items)
        return [(t or "").strip() or None for t in texts]

    def _invoke(self, payload):
        """Run the Node helper. Returns the parsed reply, or None if it failed.

        Split out so the failure paths can be exercised without a subprocess.
        """
        try:
            done = subprocess.run(
                [self.node, str(SRE_SCRIPT)],
                input=json.dumps(payload),
                capture_output=True, text=True, timeout=self.timeout,
                check=True)
            return json.loads(done.stdout or "{}") or {}
        except (OSError, ValueError, subprocess.SubprocessError):
            return None


def build_speech(tokens, math=None):
    """Return (text_for_tts, owner_index_per_spoken_word).

    `len(owners) == len(text.split())` is the contract generate.py resolves
    Polly's character offsets against.
    """
    math = math or SkipMath()

    math_positions = [i for i, t in enumerate(tokens) if t.kind == "math"]
    spoken_math = math.speak_all(
        [(tokens[i].latex, tokens[i].display) for i in math_positions])
    said_by_index = dict(zip(math_positions, spoken_math))

    words = []
    owners = []

    for index, token in enumerate(tokens):
        if token.kind == "word":
            spoken = [token.text]
        elif token.kind == "cloze":
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
