"""What Kokoro is asked to SAY, and the fingerprint of everything that shapes it.

Kokoro (misaki) guesses a word it does not know — Laplace, Kirchhoff, e.g. read
as letters, mA as "em ay". The correction table fixes those as phoneme
overrides, written inline as misaki's own `[word](/phonemes/)` markup. The word
itself stays the token's text, so the word timings still map onto the original,
un-annotated script, which is what `generate.synthesise` indexes.

Two identities are kept apart on purpose:

  * `text_key` hashes the ANNOTATED text and the engine FAMILY ("kokoro"), so
    editing one table entry re-keys only the sections containing that word.
  * `engine_id` ("kokoro@<12 hex>") fingerprints the whole table and
    `speech.SPEECH_VERSION`. It is stored on the track row, and the generator's
    cheap exit compares it, so a table or narration change is noticed at all —
    without it, the exit would report `have` forever and the old pronunciation
    would keep playing.

Only the kokoro engine is touched. For Polly (`neural`, `standard`) the text is
returned as is and the engine id is the engine, so no existing key moves.
"""

import hashlib
import json
from pathlib import Path

KOKORO = "kokoro"
_TABLE_FILE = Path(__file__).resolve().parent / "pronunciations.json"
_EDGE = "(),;:\"“”‘’"

# Kokoro-82M's phoneme vocabulary (config.json "vocab"), so a typo in the table
# is caught by a test rather than heard by a class.
KOKORO_VOCAB = frozenset(
    ' !"(),.:;?AIOQSTWYabcdefhijklmnopqrstuvwxyzæçðøŋœɐɑɒɔɕɖəɚɛɜɟɡɣɤɥɨɪɯɰɲɳɴ'
    'ɸɹɻɽɾʁʂʃʈʊʋʌʎʒʔʝʣʤʥʦʧʨʰʲˈˌː̃βθχᵊᵝᵻ—“”…→↓↗↘ꭧ')


def load_table() -> dict:
    """The packaged table, extended or overridden by the host's setting."""
    table = json.loads(_TABLE_FILE.read_text(encoding="utf-8"))
    try:
        from django.conf import settings
        extra = getattr(settings, "PARODY_WEB_READALOUD_PRONUNCIATIONS",
                        None) or {}
    except Exception:                      # noqa: BLE001 — no Django here
        extra = {}
    table.update(extra)
    return table


def _annotate(word, table):
    for core in (word.strip(_EDGE), word.strip(_EDGE + ".")):
        if core and core in table:
            at = word.index(core)
            return f"{word[:at]}[{core}](/{table[core]}/){word[at + len(core):]}"
    return word


def spoken_form(text: str, engine: str, table: dict | None = None) -> str:
    """The text as the engine should be asked to say it."""
    if engine_family(engine) != KOKORO:
        return text
    table = load_table() if table is None else table
    return " ".join(_annotate(word, table) for word in text.split())


def engine_id(engine: str, table: dict | None = None) -> str:
    """What the track row records as its engine: kokoro is fingerprinted."""
    if engine_family(engine) != KOKORO:
        return engine
    from .speech import SPEECH_VERSION
    table = load_table() if table is None else table
    digest = hashlib.sha256(
        (json.dumps(table, sort_keys=True, ensure_ascii=False)
         + "\0" + SPEECH_VERSION).encode("utf-8"))
    return f"{KOKORO}@{digest.hexdigest()[:12]}"


def engine_family(engine_id: str) -> str:
    return (engine_id or "").split("@", 1)[0]
