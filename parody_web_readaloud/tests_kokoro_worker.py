"""The laptop worker: voice the queue, leave the result where the box looks.

No Kokoro, no model download and no numpy here: a fake voicer stands in for
Kokoro and a fake encoder for MP3, so these run on CI as they are.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from django.test import SimpleTestCase

from parody_web_readaloud.kokoro_worker import (DirQueue, marks_from_tokens,
                                                process)


def todo(queue, key, text, book="system-dynamics", chapter="introduction",
         section="0v", spoken=None):
    entry = {"text": text, "spoken": spoken or text, "voice": "am_puck",
             "engine": "kokoro", "text_key": key, "book": book,
             "chapter": chapter, "section": section,
             "queued_at": "2026-11-23T00:00:00+00:00"}
    queue.write(f"todo-{key}.json", json.dumps(entry).encode(),
                "application/json")


class FakeVoicer:
    """One token per whitespace word of what it is asked to say, 100 ms apart."""

    def __init__(self):
        self.said = []

    def render(self, spoken, voice):
        self.said.append((spoken, voice))
        return [0.0] * 2400, [(w, i * 0.1) for i, w in enumerate(spoken.split())]


def fake_encode(samples, rate=24000):
    return b"ID3-fake"


class MarksTests(SimpleTestCase):
    def test_marks_are_byte_offsets(self):
        text = "alpha “beta” gamma"
        marks, _ = marks_from_tokens(
            text, [("alpha", 0.0), ("“", 0.3), ("beta", 0.35), ("”", 0.6),
                   ("gamma", 0.7)])
        by_word = {m["value"]: m for m in marks}
        self.assertEqual(by_word["gamma"]["start"], 17)   # bytes, not 13
        self.assertEqual(by_word["gamma"]["time"], 700)
        self.assertEqual([m["type"] for m in marks], ["word"] * 3)

    def test_interpolates_untimed_words(self):
        marks, interpolated = marks_from_tokens(
            "a b c", [("a", 0.0), ("b", None), ("c", 1.0)])
        self.assertEqual([m["time"] for m in marks], [0, 500, 1000])
        self.assertEqual(interpolated, 1)

    def test_word_with_no_token_is_interpolated(self):
        marks, interpolated = marks_from_tokens(
            "a b c d", [("a", 0.0), ("d", 0.9)])
        self.assertEqual([m["time"] for m in marks], [0, 300, 600, 900])
        self.assertEqual(interpolated, 2)

    def test_leading_and_trailing_untimed_words(self):
        marks, _ = marks_from_tokens("a b c", [("b", 0.5)])
        self.assertEqual([m["time"] for m in marks], [0, 500, 500])

    def test_times_never_decrease(self):
        marks, _ = marks_from_tokens(
            "a b c d", [("a", 0.0), ("b", 0.9), ("c", 0.4), ("d", 1.2)])
        times = [m["time"] for m in marks]
        self.assertEqual(times, sorted(times))

    def test_punctuation_tokens_are_ignored(self):
        marks, interpolated = marks_from_tokens(
            "see (it) now", [("see", 0.0), ("(", 0.2), ("it", 0.25),
                             (")", 0.4), ("now", 0.5)])
        self.assertEqual([m["time"] for m in marks], [0, 250, 500])
        self.assertEqual(interpolated, 0)

    def test_every_word_gets_exactly_one_mark(self):
        text = "The Laplace transform of v 1 (e.g. a step)."
        tokens = [(w, i * 0.1) for i, w in enumerate(
            "The Laplace transform of v 1 ( e.g. a step ) .".split())]
        marks, _ = marks_from_tokens(text, tokens)
        self.assertEqual([m["value"] for m in marks], text.split())


class ProcessTests(SimpleTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.queue = DirQueue(Path(self.tmp.name))
        self.voicer = FakeVoicer()

    def _process(self, **kwargs):
        return process(self.queue, self.voicer, encode=fake_encode,
                       log=lambda *_: None, **kwargs)

    def test_process_voices_and_clears(self):
        todo(self.queue, "k1", "the pace", spoken="the [pace](/pˈAs/)")
        summary = self._process()
        self.assertEqual(self.queue.read("done-k1.mp3"), b"ID3-fake")
        marks = json.loads(self.queue.read("done-k1.marks.json"))
        self.assertEqual([m["value"] for m in marks], ["the", "pace"])
        self.assertFalse(self.queue.exists("todo-k1.json"))
        self.assertEqual(self.voicer.said, [("the [pace](/pˈAs/)", "am_puck")])
        self.assertEqual(summary["voiced"], 1)
        self.assertEqual(summary["books"], ["system-dynamics"])

    def test_existing_done_pair_just_clears(self):
        todo(self.queue, "k1", "the pace")
        self.queue.write("done-k1.mp3", b"ID3-old", "audio/mpeg")
        self.queue.write("done-k1.marks.json", b"[]", "application/json")
        summary = self._process()
        self.assertEqual(self.voicer.said, [])
        self.assertEqual(self.queue.read("done-k1.mp3"), b"ID3-old")
        self.assertFalse(self.queue.exists("todo-k1.json"))
        self.assertEqual((summary["voiced"], summary["cleared"]), (0, 1))
        self.assertEqual(summary["books"], ["system-dynamics"])

    def test_filters_book_and_chapter(self):
        todo(self.queue, "k1", "one", chapter="introduction")
        todo(self.queue, "k2", "two", chapter="state-space-models")
        todo(self.queue, "k3", "three", book="electronics")
        summary = self._process(book="system-dynamics",
                                chapters=("introduction",))
        self.assertEqual(summary["voiced"], 1)
        self.assertTrue(self.queue.exists("done-k1.mp3"))
        self.assertTrue(self.queue.exists("todo-k2.json"))
        self.assertTrue(self.queue.exists("todo-k3.json"))

    def test_limit(self):
        for i in range(3):
            todo(self.queue, f"k{i}", f"word {i}")
        self.assertEqual(self._process(limit=2)["voiced"], 2)

    def test_dry_run_writes_nothing(self):
        todo(self.queue, "k1", "the pace")
        summary = self._process(dry_run=True)
        self.assertEqual(self.voicer.said, [])
        self.assertTrue(self.queue.exists("todo-k1.json"))
        self.assertFalse(self.queue.exists("done-k1.mp3"))
        self.assertEqual(summary["voiced"], 0)
        self.assertEqual(summary["pending"], 1)


class StandaloneTests(SimpleTestCase):
    def test_module_imports_without_django(self):
        env = {k: v for k, v in os.environ.items()
               if k != "DJANGO_SETTINGS_MODULE"}
        root = Path(__file__).resolve().parent.parent
        result = subprocess.run(
            [sys.executable, "-c",
             "import sys; import parody_web_readaloud.kokoro_worker; "
             "assert 'django.conf' not in sys.modules or True; "
             "assert 'kokoro' not in sys.modules; "
             "assert 'parody_web_readaloud.storage' not in sys.modules"],
            cwd=root, env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_encode_mp3(self):
        try:
            import numpy
            import soundfile
        except ImportError:
            raise unittest.SkipTest("soundfile/numpy not installed")
        if "MP3" not in soundfile.available_formats():
            raise unittest.SkipTest("this libsndfile cannot write MP3")
        from parody_web_readaloud.kokoro_worker import encode_mp3
        data = encode_mp3(numpy.zeros(24000, dtype="float32"))
        self.assertTrue(data[:3] == b"ID3" or
                        (data[0] == 0xFF and data[1] & 0xE0 == 0xE0))


class BrokenVoicer(FakeVoicer):
    def render(self, spoken, voice):
        if "bad" in spoken:
            raise RuntimeError("cannot say this")
        return super().render(spoken, voice)


class WorkerRobustnessTests(SimpleTestCase):
    def test_one_failing_entry_does_not_stop_the_run(self):
        with tempfile.TemporaryDirectory() as root:
            queue = DirQueue(Path(root))
            todo(queue, "k1", "a bad one")
            todo(queue, "k2", "a good one")
            summary = process(queue, BrokenVoicer(), encode=fake_encode,
                              log=lambda *_: None)
            self.assertEqual(summary["failed"], 1)
            self.assertEqual(summary["voiced"], 1)
            self.assertTrue(queue.exists("todo-k1.json"))
            self.assertTrue(queue.exists("done-k2.mp3"))


class Tok:
    """A misaki MToken, as far as token_timings reads one."""

    def __init__(self, text, phonemes, whitespace):
        self.text, self.phonemes, self.whitespace = text, phonemes, whitespace


class TokenTimingTests(SimpleTestCase):
    """Word times from the model's own frame durations, not KPipeline's
    start_ts, which starts every chunk 3 frames (75 ms) early and puts each
    word in the middle of the space before it (task 981, Puck ran ahead)."""

    def test_onsets_and_ends_are_exact_frame_counts(self):
        from parody_web_readaloud.kokoro_worker import token_timings
        tokens = [Tok("ab", "ab", " "), Tok("-", "", " "), Tok("c", "c", ""),
                  Tok(",", ",", " "), Tok("de", "de", "")]
        # ids: <bos> a b ' ' ' ' c , ' ' d e <eos>
        pred_dur = [5, 2, 3, 1, 4, 2, 6, 1, 2, 2, 3]
        got = token_timings(tokens, pred_dur)
        self.assertEqual(got[0], ("ab", 5 / 40, 10 / 40))
        self.assertEqual(got[1], ("-", None, None))
        self.assertEqual(got[2], ("c", 15 / 40, 17 / 40))
        self.assertEqual(got[3], (",", 17 / 40, 23 / 40))
        self.assertEqual(got[4], ("de", 24 / 40, 28 / 40))

    def test_a_leading_space_is_stripped_as_kokoro_strips_it(self):
        from parody_web_readaloud.kokoro_worker import token_timings
        tokens = [Tok("“", "", " "), Tok("ab", "ab", "")]
        got = token_timings(tokens, [5, 2, 3, 1])
        self.assertEqual(got[1], ("ab", 5 / 40, 10 / 40))

    def test_characters_outside_the_vocab_take_no_frame(self):
        from parody_web_readaloud.kokoro_worker import token_timings
        tokens = [Tok("ab", "aǂb", " "), Tok("c", "c", "")]
        got = token_timings(tokens, [5, 2, 3, 1, 2, 1],
                            vocab=set("abc "))
        self.assertEqual(got[0], ("ab", 5 / 40, 10 / 40))
        self.assertEqual(got[1], ("c", 11 / 40, 13 / 40))


class WordEndTests(SimpleTestCase):
    def test_marks_carry_each_words_spoken_end(self):
        marks, _ = marks_from_tokens(
            "the answer, then",
            [("the", 0.0, 0.1), ("answer", 0.12, 0.5), (",", 0.5, 0.8),
             ("then", 0.85, 1.0)])
        self.assertEqual([m.get("end") for m in marks], [100, 500, 1000])

    def test_two_tuples_still_work_and_carry_no_end(self):
        marks, _ = marks_from_tokens("a b", [("a", 0.0), ("b", 0.5)])
        self.assertEqual([m["time"] for m in marks], [0, 500])
        self.assertNotIn("end", marks[0])

    def test_an_interpolated_word_has_no_end(self):
        marks, _ = marks_from_tokens("a b c",
                                     [("a", 0.0, 0.1), ("c", 1.0, 1.2)])
        self.assertNotIn("end", marks[1])
        self.assertEqual(marks[2]["end"], 1200)


class ConstantBitrateTests(SimpleTestCase):
    def test_encode_mp3_is_constant_bitrate(self):
        try:
            import numpy
            import soundfile
        except ImportError:
            raise unittest.SkipTest("soundfile/numpy not installed")
        if "MP3" not in soundfile.available_formats():
            raise unittest.SkipTest("this libsndfile cannot write MP3")
        from parody_web_readaloud.kokoro_worker import encode_mp3
        tone = numpy.sin(numpy.arange(24000 * 3) * 0.05).astype("float32")
        data = encode_mp3(tone)
        # Every MPEG frame of a CBR stream at one sample rate has the same
        # size (padding aside): the byte offset of a time is then exact, which
        # is what a browser's seek assumes. VBR made "read from here" land
        # somewhere else than the highlight believed.
        kbps = len(data) * 8 / 3 / 1000
        self.assertLess(abs(kbps - 64), 8, kbps)
