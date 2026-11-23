"""The laptop half of Kokoro voicing: `parody-voice-queue`.

The box (`generate_readalong --engine kokoro`) never runs Kokoro. It writes the
exact script of every section that needs audio to a queue — `todo-<key>.json`
under `readalong-queue/` in the media bucket — and this worker, run wherever
compute is cheap, voices each entry with Kokoro and leaves
`done-<key>.mp3` + `done-<key>.marks.json` for the box's next run to pick up.

It voices `spoken` exactly as the box wrote it (the correction table already
applied) and times the words of `text`, never re-deriving either: so a laptop
on a different parody-web or SRE than the box still cannot produce audio for
words other than the ones the timings index.

Deliberately free of Django, of `storage.py` and of the box's code, so it runs
from a bare `uv run --with 'parody-web[kokoro]'` with nothing but the bucket.
Kokoro needs Python <= 3.12; on macOS it needs Homebrew's espeak-ng, because
the copy bundled in espeakng-loader ignores its data path and kills the
process (`brew install espeak-ng`).

    parody-voice-queue --book system-dynamics --chapter introduction
"""

import argparse
import bisect
import io
import json
import os
import sys
import time
from pathlib import Path

RATE = 24_000
HOP = 600                    # samples per Kokoro duration frame (25 ms)
PREFIX = "readalong-queue/"
REPO = "hexgrad/Kokoro-82M"
_ESPEAK_PREFIXES = ("/opt/homebrew/opt/espeak-ng", "/usr/local/opt/espeak-ng")


def token_timings(tokens, pred_dur, vocab=None, hop: int = HOP,
                  rate: int = RATE) -> list:
    """[(token text, onset s, end s)] for one KPipeline result, from frames.

    Kokoro's own `start_ts` (KPipeline.join_timestamps) is not where a word
    starts: it begins each chunk 3 frames (75 ms) before the first phoneme and
    puts every later word in the middle of the space before it, and a
    phoneme-less token with whitespace shifts the rest of the chunk by one id.
    Measured against the audio, its marks ran from 100 ms early to 50 ms late
    (task 981: "the highlighter runs ahead of the voice").

    The model's `pred_dur` is how many 25 ms frames each input id lasts, and
    the audio is exactly sum(pred_dur) * 600 samples, so a token's onset is the
    frames before its first phoneme and its end the frames through its last.
    The ids are the phoneme string KPipeline builds (`tokens_to_ps`: each
    token's phonemes, a space after it when it has whitespace, stripped), less
    any character outside the model's vocabulary, between <bos> and <eos>.
    A token with no phonemes gets (text, None, None).
    """
    durations = [int(d) for d in pred_dur]
    cumulative = [0]
    for d in durations:
        cumulative.append(cumulative[-1] + d)
    full = "".join(t.phonemes + (" " if t.whitespace else "") for t in tokens)
    lead = len(full) - len(full.lstrip())
    kept = [vocab is None or c in vocab for c in full]
    # ids_before[k]: how many ids the characters before position k became.
    ids_before = [0]
    for k, c in enumerate(full):
        ids_before.append(ids_before[-1] + (1 if k >= lead and kept[k] else 0))
    last = len(cumulative) - 1

    def seconds(char_pos):
        frames = cumulative[min(1 + ids_before[char_pos], last)]   # +1: <bos>
        return frames * hop / rate

    out, pos = [], 0
    for t in tokens:
        if t.phonemes:
            out.append((t.text, seconds(pos), seconds(pos + len(t.phonemes))))
        else:
            out.append((t.text, None, None))
        pos += len(t.phonemes) + (1 if t.whitespace else 0)
    return out


def marks_from_tokens(text: str, timed: list) -> tuple:
    """Word marks for `text`, in Polly's shape, from Kokoro's timed tokens.

    `timed` is [(token text, start s or None[, end s or None])], in speaking
    order. A word whose tokens carry an end gets `"end"` (ms): when its own
    sound stops, before any pause or punctuation after it — which is where a
    blank should hold, rather than at the next word's start. Each
    whitespace word of `text` takes the start of the first token found inside
    it by a forward search; tokens with no letter or digit (brackets, quotes,
    full stops) mark no word. A word no token timed is interpolated between its
    timed neighbours (0 before the first, the previous time after the last),
    and times are forced non-decreasing.

    `start` is a BYTE offset, because that is what `generate.synthesise`
    resolves marks against (it was built for Polly, which counts bytes).
    Returns (marks, how many words were interpolated).
    """
    words, char_starts, byte_starts = [], [], []
    at = 0
    for word in text.split():
        at = text.index(word, at)
        words.append(word)
        char_starts.append(at)
        byte_starts.append(len(text[:at].encode("utf-8")))
        at += len(word)

    times = [None] * len(words)
    ends = [None] * len(words)
    cursor = 0
    for item in timed:
        token, start = item[0], item[1]
        end = item[2] if len(item) > 2 else None
        if not token or not any(c.isalnum() for c in token):
            continue
        found = text.find(token, cursor)
        if found < 0:
            continue
        cursor = found + len(token)
        index = bisect.bisect_right(char_starts, found) - 1
        if index < 0:
            continue
        if times[index] is None and start is not None:
            times[index] = float(start)
        if end is not None:
            ends[index] = max(float(end), ends[index] or 0.0)

    known = [i for i, t in enumerate(times) if t is not None]
    interpolated = 0
    for i, t in enumerate(times):
        if t is not None:
            continue
        interpolated += 1
        after = bisect.bisect_right(known, i)
        prev_i = known[after - 1] if after > 0 else None
        next_i = known[after] if after < len(known) else None
        # Never before the previous word's own sound has ended: an untimed
        # dash after a blank's answer must not start inside the answer, or the
        # blank (which holds at the next word's start) would hold mid-answer.
        floor = (None if prev_i is None else
                 ends[prev_i] if ends[prev_i] is not None else times[prev_i])
        if prev_i is None:
            times[i] = 0.0
        elif next_i is None:
            times[i] = floor
        else:
            ceiling = max(times[next_i], floor)
            share = (i - prev_i) / (next_i - prev_i)
            times[i] = floor + (ceiling - floor) * share

    marks, last = [], 0
    for word, start, seconds, end in zip(words, byte_starts, times, ends):
        ms = max(last, int(round(seconds * 1000)))
        mark = {"time": ms, "type": "word", "start": start, "value": word}
        if end is not None:
            mark["end"] = max(ms, int(round(end * 1000)))
        marks.append(mark)
        last = ms
    return marks, interpolated


class DirQueue:
    """The queue as files in a directory: for tests and a disk-backed host."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def todo(self) -> list:
        if not self.root.is_dir():
            return []
        return sorted(p.name for p in self.root.glob("todo-*.json"))

    def read(self, name) -> bytes:
        return (self.root / name).read_bytes()

    def write(self, name, data: bytes, content_type: str) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / name).write_bytes(data)

    def exists(self, name) -> bool:
        return (self.root / name).exists()

    def delete(self, name) -> None:
        (self.root / name).unlink(missing_ok=True)


class S3Queue:
    """The queue as objects under `prefix` in the host's media bucket."""

    def __init__(self, bucket: str, prefix: str = PREFIX,
                 region: str = "us-west-2"):
        import boto3
        self.bucket, self.prefix = bucket, prefix
        self.client = boto3.client("s3", region_name=region)

    def todo(self) -> list:
        names = []
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket,
                                       Prefix=self.prefix + "todo-"):
            for obj in page.get("Contents", []) or []:
                names.append(obj["Key"][len(self.prefix):])
        return sorted(names)

    def read(self, name) -> bytes:
        return self.client.get_object(
            Bucket=self.bucket, Key=self.prefix + name)["Body"].read()

    def write(self, name, data: bytes, content_type: str) -> None:
        self.client.put_object(Bucket=self.bucket, Key=self.prefix + name,
                               Body=data, ContentType=content_type)

    def exists(self, name) -> bool:
        from botocore.exceptions import ClientError
        try:
            self.client.head_object(Bucket=self.bucket, Key=self.prefix + name)
        except ClientError as error:
            if str(error.response.get("Error", {}).get("Code", "")) in (
                    "404", "NoSuchKey", "NotFound"):
                return False
            raise
        return True

    def delete(self, name) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=self.prefix + name)


def _setup_espeak():
    """Point misaki's out-of-vocabulary fallback at a working espeak-ng."""
    if sys.platform != "darwin":
        return
    for prefix in _ESPEAK_PREFIXES:
        library = Path(prefix, "lib", "libespeak-ng.dylib")
        if library.exists():
            import misaki.espeak  # noqa: F401 — sets the broken bundled lib
            from phonemizer.backend.espeak.wrapper import EspeakWrapper
            EspeakWrapper.set_library(str(library))
            EspeakWrapper.set_data_path(
                str(Path(prefix, "share", "espeak-ng-data")))
            return
    raise SystemExit(
        "Kokoro needs Homebrew's espeak-ng on macOS (the bundled one is "
        "broken): brew install espeak-ng")


class KokoroVoice:
    """Kokoro-82M, loaded on first use. `pipeline_factory` is for tests."""

    def __init__(self, pipeline_factory=None):
        self._factory = pipeline_factory
        self._pipeline = None

    def _pipe(self):
        if self._pipeline is None:
            if self._factory is not None:
                self._pipeline = self._factory()
            else:
                _setup_espeak()
                from kokoro import KPipeline
                self._pipeline = KPipeline(lang_code="a", repo_id=REPO)
        return self._pipeline

    def render(self, spoken: str, voice: str):
        """(samples at 24 kHz, [(token, absolute onset s, absolute end s)]).

        Times come from the model's frame durations (`token_timings`), not
        KPipeline's `start_ts`; chunks are laid end to end by their sample
        counts, which are exactly their frame counts times 600.
        """
        import numpy as np

        pipe = self._pipe()
        vocab = getattr(getattr(pipe, "model", None), "vocab", None)
        chunks, timed, elapsed = [], [], 0.0
        for result in pipe(spoken, voice=voice):
            audio = result.audio
            audio = audio.numpy() if hasattr(audio, "numpy") else np.asarray(audio)
            pred_dur = getattr(result, "pred_dur", None)
            if pred_dur is not None:
                durations = (pred_dur.tolist() if hasattr(pred_dur, "tolist")
                             else list(pred_dur))
                for text, start, end in token_timings(result.tokens or [],
                                                      durations, vocab):
                    timed.append((text,
                                  None if start is None else elapsed + start,
                                  None if end is None else elapsed + end))
            else:                                   # no durations: best effort
                for token in result.tokens or []:
                    start = getattr(token, "start_ts", None)
                    timed.append((token.text,
                                  None if start is None else elapsed + start))
            chunks.append(audio)
            elapsed += len(audio) / RATE
        samples = (np.concatenate(chunks) if chunks
                   else np.zeros(0, dtype="float32"))
        return samples, timed


def encode_mp3(samples, rate: int = RATE) -> bytes:
    import soundfile

    # Constant bitrate, ~64 kbps at 24 kHz mono. A VBR stream is seeked by its
    # Xing table of contents, which is approximate: "read from here" and a
    # restored position landed away from where the highlight believed the
    # voice was. In CBR a time's byte offset is exact (Polly's were CBR too).
    buffer = io.BytesIO()
    soundfile.write(buffer, samples, rate, format="MP3",
                    bitrate_mode="CONSTANT", compression_level=0.6)
    return buffer.getvalue()


def process(queue, voicer, *, encode=encode_mp3, book=None, chapters=(),
            limit=None, dry_run=False, log=print) -> dict:
    """Voice every matching todo entry; returns a summary for the host."""
    voiced = cleared = pending = interpolated = failed = 0
    books = set()
    for name in queue.todo():
        entry = json.loads(queue.read(name).decode("utf-8"))
        if book and entry.get("book") != book:
            continue
        if chapters and entry.get("chapter") not in chapters:
            continue
        where = "/".join(entry.get(k, "") for k in ("book", "chapter",
                                                    "section"))
        key = entry["text_key"]
        audio_name, marks_name = f"done-{key}.mp3", f"done-{key}.marks.json"
        if dry_run:
            pending += 1
            log(f"would voice {where}: {len(entry['text'])} chars")
            continue
        if limit is not None and voiced >= limit:
            break
        if queue.exists(audio_name) and queue.exists(marks_name):
            queue.delete(name)              # an earlier run got this far
            cleared += 1
            books.add(entry.get("book", ""))
            continue
        began = time.monotonic()
        try:
            samples, timed = voicer.render(entry["spoken"], entry["voice"])
            marks, filled = marks_from_tokens(entry["text"], timed)
            queue.write(audio_name, encode(samples), "audio/mpeg")
            queue.write(marks_name, json.dumps(marks).encode("utf-8"),
                        "application/json")
        except Exception as error:          # noqa: BLE001
            # One entry Kokoro cannot say must not wedge the queue: the list
            # is sorted, so every re-run would die at the same place.
            failed += 1
            log(f"FAILED {where}: {type(error).__name__}: {error}")
            continue
        queue.delete(name)                  # last: a crash re-voices, never loses
        voiced += 1
        interpolated += filled
        books.add(entry.get("book", ""))
        log(f"voiced {where}: {len(marks)} words "
            f"({filled} interpolated) in {time.monotonic() - began:.1f}s")
    return {"voiced": voiced, "cleared": cleared, "pending": pending,
            "interpolated": interpolated, "failed": failed,
            "books": sorted(b for b in books if b)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="parody-voice-queue",
        description="Voice the read-along queue with Kokoro.")
    parser.add_argument(
        "--bucket", default=(os.environ.get("PARODY_WEB_READALOUD_BUCKET")
                             or os.environ.get("AWS_STORAGE_BUCKET_NAME")))
    parser.add_argument("--prefix", default=PREFIX)
    parser.add_argument("--region", default="us-west-2")
    parser.add_argument("--queue-dir", default=None,
                        help="a local queue directory instead of S3")
    parser.add_argument("--book", default=None)
    parser.add_argument("--chapter", action="append", default=[])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if not args.dry_run:
        # Fail before a single section is synthesised, not after every one
        # has been: an old soundfile (no bitrate_mode) or a libsndfile without
        # MP3 would otherwise discard hours of Kokoro output, one by one.
        try:
            encode_mp3([0.0] * RATE)
        except Exception as error:                  # noqa: BLE001
            print(f"cannot write MP3 here ({type(error).__name__}: {error}); "
                  "needs soundfile >= 0.13 with an MP3-capable libsndfile",
                  file=sys.stderr, flush=True)
            return 2

    if args.queue_dir:
        queue = DirQueue(Path(args.queue_dir))
    elif args.bucket:
        queue = S3Queue(args.bucket, args.prefix, args.region)
    else:
        parser.error("no queue: pass --bucket (or set AWS_STORAGE_BUCKET_NAME)"
                     " or --queue-dir")
    summary = process(queue, KokoroVoice(), book=args.book,
                      chapters=tuple(args.chapter), limit=args.limit,
                      dry_run=args.dry_run,
                      log=lambda line: print(line, flush=True))
    print(json.dumps(summary), flush=True)     # last line: the host parses it
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
