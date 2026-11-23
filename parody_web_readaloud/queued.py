"""The box half of Kokoro voicing: queue the exact text, or return the result.

The production box never runs Kokoro (a t4g.small: 2 GB, shared with the site).
Instead `generate_readalong` hands this synth the section's script exactly as it
does Polly's. On a miss it writes `todo-<text_key>.json` — the text, and the
annotated text Kokoro must say — and raises `NotVoicedYet`; the laptop worker
(`kokoro_worker.py`) voices it and leaves `done-<text_key>.mp3` and
`done-<text_key>.marks.json`; the next run finds the pair and returns it like
any synth would, and `finish` clears it once the track row is written.

The box writes the text and its key, the laptop only voices what it is given:
so a parody-web or SRE version that differs between the two machines can never
produce audio for words other than the ones the timings index.
"""

import json
from datetime import datetime, timezone

from .generate import text_key_for
from .pronounce import engine_family, spoken_form


class NotVoicedYet(Exception):
    """The text is queued for the laptop worker; there is no audio yet."""

    def __init__(self, text_key: str):
        super().__init__(f"queued for voicing: {text_key}")
        self.text_key = text_key


class QueuedSynth:
    def __init__(self, voice: str, engine: str, store, table: dict | None = None):
        self.voice = voice
        self.engine = engine_family(engine)
        self.store = store
        self.table = table
        # Set by the caller before each section: what the worker shows and
        # filters on (book, chapter, section).
        self.context = {}

    def key_for(self, text: str) -> tuple:
        """(the annotated text Kokoro says, the text_key its audio is filed by)."""
        spoken = spoken_form(text, self.engine, self.table)
        return spoken, text_key_for(spoken, self.voice, self.engine)

    def __call__(self, text: str):
        spoken, key = self.key_for(text)
        audio, marks = f"done-{key}.mp3", f"done-{key}.marks.json"
        if self.store.exists(audio) and self.store.exists(marks):
            return (self.store.read(audio),
                    json.loads(self.store.read(marks).decode("utf-8")))
        todo = f"todo-{key}.json"
        if not self.store.exists(todo):
            entry = {
                "text": text, "spoken": spoken, "voice": self.voice,
                "engine": self.engine, "text_key": key,
                "book": self.context.get("book", ""),
                "chapter": self.context.get("chapter", ""),
                "section": self.context.get("section", ""),
                "queued_at": datetime.now(timezone.utc).isoformat(),
            }
            self.store.write(todo, json.dumps(entry, ensure_ascii=False)
                             .encode("utf-8"), "application/json")
        raise NotVoicedYet(key)

    def finish(self, text_key: str) -> None:
        """The track is written and its audio stored; the hand-off is spent."""
        for name in (f"done-{text_key}.mp3", f"done-{text_key}.marks.json"):
            self.store.delete(name)
