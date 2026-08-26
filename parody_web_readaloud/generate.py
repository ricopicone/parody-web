"""The generation pipeline: a key-mode artifact plus a served PDF in, a track out.

Runs at import or on an instructor's command. NEVER on a request — lazy
synthesis is the one path by which an anonymous visitor to a public book could
mint new audio, and the only way cost starts tracking requests instead of
content.

`synth` is injected so the whole pipeline is testable without AWS.

A track has TWO identities, and confusing them is what makes editing a book
expensive. Its geometry — the boxes, the page sizes — is true of one
pagination, and `printing.slice_key_for` is right to invalidate on any reflow.
Its audio and timings are true only of the spoken text, the voice and the
engine, which `text_key_for` hashes and pagination does not enter. `prepare`
does everything the first identity needs, for free; `synthesise` and `reuse`
are the two ways to arrive at the second, one of which costs money.
"""

import hashlib
import json
from dataclasses import dataclass

from .align import align
from .geometry import extract_blanks, extract_words, page_sizes
from .script import parse_script
from .speech import build_speech

CHUNK_LIMIT = 2900          # Polly's per-request character ceiling, with room
TAIL_MS = 300               # how long the last word is assumed to last
GAP_MS = 400                # assumed silence between synthesised chunks


def chunk_text(text: str, limit: int = CHUNK_LIMIT) -> list:
    """Partition the text into pieces Polly will accept.

    Works on words, not on sentences, and that matters twice.

    It has to be an exact partition: `build_speech` joins the text with single
    spaces and the timings are resolved against character offsets into it, so
    a chunking that dropped or added a character would shift every later word's
    box. Splitting on ' ' and rejoining with ' ' cannot drift.

    And it has to bound EVERY piece. An earlier version broke on sentence
    boundaries and emitted whatever lay between them whole — which is fine for
    prose and fatal for spoken maths, where SRE renders one equation as a
    single run of hundreds of words containing no sentence break at all. Polly
    rejected it outright. Found in production, mid-book.

    Sentence ends are still preferred as break points; they are just no longer
    relied upon to exist.
    """
    words = text.split(" ") if text else []
    chunks, current, length = [], [], 0
    last_stop = -1                      # index in `current` after a sentence end

    for word in words:
        extra = len(word) + (1 if current else 0)
        if current and length + extra > limit:
            # Prefer to break after the last sentence end, provided that does
            # not throw away most of the chunk.
            if last_stop > 0 and last_stop >= len(current) // 2:
                chunks.append(" ".join(current[:last_stop]))
                current = current[last_stop:]
                length = len(" ".join(current))
            else:
                chunks.append(" ".join(current))
                current, length = [], 0
            last_stop = -1
            extra = len(word)
        current.append(word)
        length += extra
        if word.endswith((".", "?", "!")):
            last_stop = len(current)

    if current:
        chunks.append(" ".join(current))

    # A single word longer than the limit cannot be split without corrupting
    # the offsets, so it goes out oversized and Polly's own error stands.
    return chunks


@dataclass
class Prepared:
    """Everything a track needs that costs nothing: script, geometry, text.

    Separated out because the two halves have different lifetimes. Repaginate
    the book and the geometry here is stale while `text` is not, which is the
    whole basis on which audio survives a reflow.
    """

    tokens: list
    placed: list
    pages: list
    svgs: dict
    text: str
    owners: list


def text_key_for(text: str, voice_id: str, engine: str) -> str:
    """Identity of the AUDIO: what is said, by whom, on which engine.

    Pagination is deliberately absent, and that absence is the point. Moving a
    section to a different page changes every box on it and not one syllable,
    so this key holds while `printing.slice_key_for` moves — and the mp3, which
    is the only part anyone pays for, is reused.

    Voice and engine are in the key because they change the recording without
    changing a word of the text, so a track made with one must never be handed
    to a run asking for the other.
    """
    digest = hashlib.sha256()
    digest.update(f"{voice_id}\x00{engine}\x00".encode("utf-8"))
    digest.update(text.encode("utf-8"))
    return digest.hexdigest()


def prepare(html: str, pdf_bytes: bytes, math=None) -> Prepared:
    """Parse the script, align it to the page, and work out what to say.

    Costs a maths-engine subprocess and a PDF parse — about a second, and no
    API call. Everything after this either spends money or reuses what a
    previous run already spent.
    """
    tokens = parse_script(html)
    text, owners = build_speech(tokens, math=math)
    return Prepared(
        tokens=tokens,
        placed=align(tokens, extract_words(pdf_bytes),
                     extract_blanks(pdf_bytes)),
        # [[widthPt, heightPt], ...]. The client divides the rendered page
        # width by this to recover the zoom scale, which is how it converts a
        # PDF box to CSS pixels without holding the annotator's viewport.
        pages=[list(size) for size in page_sizes(pdf_bytes)],
        svgs=_render_cloze_maths(tokens, math),
        text=text,
        owners=owners,
    )


def is_math_cloze(token) -> bool:
    """A maths token that HIDES something.

    The author clozes part of an equation rather than the whole of it, so the
    blank never becomes a cloze token: key mode marks the answer inside the
    maths and the equation stays one token. It is still a blank on the page and
    still needs a reveal, and the equation's own box is where to put it — the
    rules inside an equation are a mix of blanks and fraction bars, and telling
    those apart is a problem this deliberately does not take on.

    What the reader sees is the WHOLE equation, filled in: one picture per
    equation however many blanks it holds, and the missing part shown in the
    place it belongs rather than floating on its own.
    """
    return token.kind == "math" and token.blanks > 0


def cloze_count(prep: Prepared) -> int:
    """How many blanks this section would store — known before synthesis."""
    return sum(1 for spot in prep.placed
               if (spot.token.kind in ("cloze", "figure_cloze")
                   or is_math_cloze(spot.token)) and spot.box)


def build_track(html: str, pdf_bytes: bytes, synth, math=None) -> dict:
    """Prepare and synthesise in one call. The path that costs money."""
    return synthesise(prepare(html, pdf_bytes, math=math), synth)


def synthesise(prep: Prepared, synth) -> dict:
    """Buy the audio, and derive every timing from the marks it comes with."""
    audio_bytes, marks = synth(prep.text)

    # Polly reports a mark's `start` as a BYTE offset into exactly the text we
    # sent, so the cursor that maps it onto `owners` has to count bytes too.
    #
    # Counting characters works perfectly until the first character that is
    # not one byte wide, and typeset prose is full of them: curly quotes, en
    # and em dashes, accented names, degree signs. From there the two run
    # apart and never resynchronise, so every later mark either matches
    # nothing — the word is dropped, and the karaoke mark sits still through
    # it — or lands on some OTHER word's offset by coincidence and takes that
    # word's box, putting the highlight somewhere else on the page entirely.
    #
    # Verified against the live API: in `alpha “beta” gamma delta`, Polly puts
    # `gamma` at 17, which is its byte offset; its character offset is 13.
    # Measured on the corpus this shipped to: 46 of 183 tracks ran under 100
    # words per minute against real speech of about 150, the worst at 30.
    offsets, cursor = {}, 0
    for position, word in enumerate(prep.text.split()):
        offsets[cursor] = position
        cursor += len(word.encode("utf-8")) + 1

    words = []
    for mark in marks:
        position = offsets.get(mark.get("start"))
        if position is None or position >= len(prep.owners):
            continue                     # Polly split inside a word; skip it
        index = prep.owners[position]
        words.append(_boxed({"word": mark.get("value", ""),
                             "start_ms": mark.get("time", 0), "token": index},
                            prep.placed[index]))

    for i, entry in enumerate(words):
        entry["end_ms"] = (words[i + 1]["start_ms"] if i + 1 < len(words)
                           else entry["start_ms"] + TAIL_MS)

    return _assemble(prep, words, audio_bytes)


def reuse(prep: Prepared, prior_words: list) -> "dict | None":
    """Re-box a previous run's timings against this pagination. Free.

    The words were spoken in an order the script fixes, and every stored word
    carries the `token` that said it, so a word's timing and a word's box are
    separable: keep the first, look the second up afresh. Nothing is asked of
    the TTS engine and nothing is asked of AWS.

    Returns None if the stored tokens do not index this script — the caller
    must then synthesise rather than place words by an index that has moved.
    """
    words = []
    for prior in prior_words:
        index = prior.get("token")
        if not isinstance(index, int) or not 0 <= index < len(prep.placed):
            return None
        words.append(_boxed({"word": prior.get("word", ""),
                             "start_ms": prior.get("start_ms", 0),
                             "end_ms": prior.get("end_ms", 0),
                             "token": index},
                            prep.placed[index]))
    # None, not b"": there is no new audio, and the caller keeps the file the
    # timings were made from rather than writing a second copy of it.
    return _assemble(prep, words, None)


def _boxed(entry: dict, spot) -> dict:
    """Attach this pagination's box for the token, if it has one."""
    if spot.box:
        entry.update(page=spot.page, x0=spot.box[0], y0=spot.box[1],
                     x1=spot.box[2], y1=spot.box[3])
    return entry


def _assemble(prep: Prepared, words: list, audio_bytes) -> dict:
    """Everything downstream of "when was each word said, and where is it".

    Shared by both routes on purpose: a reused track must be assembled by the
    same code as a synthesised one, or the two would drift apart in exactly the
    place nobody would look.
    """
    # When each token stops being spoken — the moment a cloze becomes due.
    window = {}
    for entry in words:
        span = window.setdefault(entry["token"],
                                 [entry["start_ms"], entry["end_ms"]])
        span[0] = min(span[0], entry["start_ms"])
        span[1] = max(span[1], entry["end_ms"])

    clozes = []
    for spot in prep.placed:
        math_cloze = is_math_cloze(spot.token)
        if spot.token.kind not in ("cloze", "figure_cloze") and not math_cloze:
            continue
        if not spot.box:
            continue                     # no rule found: stay silent about it
        # A clozed equation with no picture to show is not a blank the client
        # can do anything with — it would pause playback to reveal nothing.
        if math_cloze and not prep.svgs.get(spot.index):
            continue
        start, end = window.get(spot.index, (0, 0))
        clozes.append({
            "token": spot.index,
            "kind": "math_cloze" if math_cloze else spot.token.kind,
            # The picture when there is one, the words when there is not.
            # A maths answer whose SVG could not be drawn used to reveal an
            # empty plate — a blank with nothing under it, which is what a
            # reader reported.
            "answer": ("" if (spot.token.latex and prep.svgs.get(spot.index))
                       else spot.token.text),
            "svg": prep.svgs.get(spot.index) or "",
            "src": spot.token.src,
            "page": spot.page, "x0": spot.box[0], "y0": spot.box[1],
            "x1": spot.box[2], "y1": spot.box[3],
            "start_ms": start, "end_ms": end,
        })

    # A figure cloze is never spoken, so it has no window of its own. Make it
    # due when the word before it finishes, or it would sit at 0 and fire at
    # the very start of the section.
    _time_silent_clozes(prep.placed, clozes, window)

    # Timed maths regions, so a reader can skip the rest of a long expression.
    # SRE is verbose by necessity — a modest integral becomes a long sentence —
    # and a student who has understood it should not have to sit through it.
    # Clozes are deliberately excluded: their narration IS the answer.
    regions = []
    for spot in prep.placed:
        if spot.token.kind != "math":
            continue
        span = window.get(spot.index)
        if not span or span[1] <= span[0]:
            continue
        regions.append({"token": spot.index, "display": spot.token.display,
                        "start_ms": span[0], "end_ms": span[1]})

    duration = words[-1]["end_ms"] if words else 0
    return {"words": words, "clozes": clozes, "regions": regions,
            "audio_bytes": audio_bytes,
            "duration_ms": duration, "text": prep.text,
            "token_count": len(prep.tokens),
            "pages": prep.pages}


def _render_cloze_maths(tokens, math):
    """An SVG per maths cloze, so a blank can reveal what it hides.

    The reader is looking at a pdf.js canvas with no MathJax anywhere near it,
    so the picture is made here, once, rather than typeset in the browser.
    """
    if math is None or not hasattr(math, "render_all"):
        return {}
    positions = [i for i, t in enumerate(tokens)
                 if (t.kind == "cloze" and t.latex) or is_math_cloze(t)]
    if not positions:
        return {}
    # `plain` for a clozed equation — the marker unwrapped, so the picture is
    # the complete equation and carries no class a stylesheet might hide.
    svgs = math.render_all([(tokens[i].plain or tokens[i].latex,
                             tokens[i].display) for i in positions])
    return {i: svg for i, svg in zip(positions, svgs) if svg}


def _time_silent_clozes(placed, clozes, window):
    """Give unspoken clozes the end time of the last spoken token before them."""
    by_token = {c["token"]: c for c in clozes}
    running = 0
    for spot in placed:
        span = window.get(spot.index)
        if span:
            running = span[1]
            continue
        cloze = by_token.get(spot.index)
        if cloze and cloze["end_ms"] == 0:
            cloze["start_ms"] = running
            cloze["end_ms"] = running


class EstimatedSynth:
    """Word timings at a reading pace, with no audio and no AWS.

    For judging the interaction — pacing, where the reveal lands, whether the
    rhythm works — before committing to a voice or paying for one. The client
    drives itself from a clock when a track has no audio.

    Not an approximation of Polly's timings so much as a stand-in for them:
    real speech varies per word, this does not.
    """

    def __init__(self, wpm=150):
        self.wpm = wpm

    def __call__(self, text: str):
        per_word = 60_000 / max(1, self.wpm)
        marks, offset, clock = [], 0, 0
        for word in text.split():
            marks.append({"type": "word", "start": offset,
                          "time": int(clock), "value": word})
            offset += len(word) + 1
            # Longer words take longer; enough variation to feel like speech.
            clock += per_word * (0.6 + 0.4 * min(len(word), 12) / 6)
        return b"", marks


class PollySynth:
    """Synthesise with AWS Polly, chunked, with word marks.

    Marks come back per chunk with offsets relative to that chunk, so each
    chunk's offsets are shifted by the running BYTE total — Polly's offsets are
    byte offsets, and so must anything they are added to be — and its times by
    the running duration.
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
        audio, marks, offset, elapsed = bytearray(), [], 0, 0
        for chunk in chunk_text(text):
            common = dict(Text=chunk, VoiceId=self.voice_id, Engine=self.engine)

            audio_response = self.client.synthesize_speech(
                OutputFormat="mp3", **common)
            audio.extend(audio_response["AudioStream"].read())

            marks_response = self.client.synthesize_speech(
                OutputFormat="json", SpeechMarkTypes=["word"], **common)
            raw = marks_response["AudioStream"].read().decode("utf-8")
            chunk_marks = [json.loads(line) for line in raw.splitlines()
                           if line.strip()]

            for mark in chunk_marks:
                mark["start"] += offset
                mark["time"] += elapsed
                marks.append(mark)

            # Bytes, to match the offsets it is being added to. The joining
            # space is one byte; the chunk's own characters may not be.
            offset += len(chunk.encode("utf-8")) + 1
            if chunk_marks:
                elapsed = marks[-1]["time"] + GAP_MS

        return bytes(audio), marks
