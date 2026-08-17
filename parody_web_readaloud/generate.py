"""The generation pipeline: a key-mode artifact plus a served PDF in, a track out.

Runs at import or on an instructor's command. NEVER on a request — lazy
synthesis is the one path by which an anonymous visitor to a public book could
mint new audio, and the only way cost starts tracking requests instead of
content.

`synth` is injected so the whole pipeline is testable without AWS.
"""

import json

from .align import align
from .geometry import extract_blanks, extract_words, page_sizes
from .script import parse_script
from .speech import build_speech

CHUNK_LIMIT = 2900          # Polly's per-request character ceiling, with room
TAIL_MS = 300               # how long the last word is assumed to last
GAP_MS = 400                # assumed silence between synthesised chunks


def chunk_text(text: str, limit: int = CHUNK_LIMIT) -> list:
    """Split on sentence boundaries, under Polly's per-request ceiling.

    Splitting mid-sentence would change the prosody at the seam, which is
    audible; splitting mid-word would also break the character-offset mapping
    the timings depend on.
    """
    if not text:
        return []
    marked = (text.replace("? ", "?\x00").replace("! ", "!\x00")
                  .replace(". ", ".\x00"))
    chunks, current = [], ""
    for sentence in marked.split("\x00"):
        if current and len(current) + len(sentence) + 1 > limit:
            chunks.append(current.strip())
            current = ""
        current += sentence + " "
    if current.strip():
        chunks.append(current.strip())
    return chunks


def build_track(html: str, pdf_bytes: bytes, synth, math=None) -> dict:
    tokens = parse_script(html)
    placed = align(tokens, extract_words(pdf_bytes), extract_blanks(pdf_bytes))
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
        position = offsets.get(mark.get("start"))
        if position is None or position >= len(owners):
            continue                     # Polly split inside a word; skip it
        spot = placed[owners[position]]
        entry = {"word": mark.get("value", ""), "start_ms": mark.get("time", 0),
                 "token": spot.index}
        if spot.box:
            entry.update(page=spot.page, x0=spot.box[0], y0=spot.box[1],
                         x1=spot.box[2], y1=spot.box[3])
        words.append(entry)

    for i, entry in enumerate(words):
        entry["end_ms"] = (words[i + 1]["start_ms"] if i + 1 < len(words)
                           else entry["start_ms"] + TAIL_MS)

    # When each token stops being spoken — the moment a cloze becomes due.
    window = {}
    for entry in words:
        span = window.setdefault(entry["token"],
                                 [entry["start_ms"], entry["end_ms"]])
        span[0] = min(span[0], entry["start_ms"])
        span[1] = max(span[1], entry["end_ms"])

    clozes = []
    for spot in placed:
        if spot.token.kind not in ("cloze", "figure_cloze"):
            continue
        if not spot.box:
            continue                     # no rule found: stay silent about it
        start, end = window.get(spot.index, (0, 0))
        clozes.append({
            "token": spot.index, "kind": spot.token.kind,
            "answer": spot.token.text, "src": spot.token.src,
            "page": spot.page, "x0": spot.box[0], "y0": spot.box[1],
            "x1": spot.box[2], "y1": spot.box[3],
            "start_ms": start, "end_ms": end,
        })

    # A figure cloze is never spoken, so it has no window of its own. Make it
    # due when the word before it finishes, or it would sit at 0 and fire at
    # the very start of the section.
    _time_silent_clozes(placed, clozes, window)

    duration = words[-1]["end_ms"] if words else 0
    return {"words": words, "clozes": clozes, "audio_bytes": audio_bytes,
            "duration_ms": duration, "text": text,
            # [[widthPt, heightPt], ...]. The client divides the rendered page
            # width by this to recover the zoom scale, which is how it converts
            # a PDF box to CSS pixels without holding the annotator's viewport.
            "pages": [list(size) for size in page_sizes(pdf_bytes)]}


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
    chunk's offsets are shifted by the running character total and its times by
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

            offset += len(chunk) + 1
            if chunk_marks:
                elapsed = marks[-1]["time"] + GAP_MS

        return bytes(audio), marks
