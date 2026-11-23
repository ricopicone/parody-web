"""The box half of Kokoro voicing: queue the exact text, or hand back the result."""
import json
import tempfile
from pathlib import Path

from django.test import SimpleTestCase, override_settings

from parody_web_readaloud.generate import text_key_for
from parody_web_readaloud.pronounce import spoken_form
from parody_web_readaloud.queued import NotVoicedYet, QueuedSynth
from parody_web_readaloud.storage import DiskAudio, queue_backend

TEXT = "The Laplace transform of v 1 (e.g. a step)."
MARKS = [{"time": 0, "type": "word", "start": 0, "value": "The"}]


class QueuedSynthTests(SimpleTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = DiskAudio(Path(self.tmp.name))
        self.synth = QueuedSynth("am_puck", "kokoro", self.store)
        self.synth.context = {"book": "system-dynamics",
                              "chapter": "introduction", "section": "0v"}
        self.spoken, self.key = self.synth.key_for(TEXT)

    def test_miss_queues_and_raises(self):
        with self.assertRaises(NotVoicedYet) as caught:
            self.synth(TEXT)
        self.assertEqual(caught.exception.text_key, self.key)
        entry = json.loads(self.store.read(f"todo-{self.key}.json"))
        self.assertEqual(entry["text"], TEXT)
        self.assertEqual(entry["spoken"], spoken_form(TEXT, "kokoro"))
        self.assertNotEqual(entry["spoken"], TEXT)     # Laplace, e.g.
        self.assertEqual(entry["voice"], "am_puck")
        self.assertEqual(entry["engine"], "kokoro")
        self.assertEqual(entry["text_key"], self.key)
        self.assertEqual((entry["book"], entry["chapter"], entry["section"]),
                         ("system-dynamics", "introduction", "0v"))
        self.assertTrue(entry["queued_at"].endswith("+00:00"))

    def test_requeue_is_idempotent(self):
        with self.assertRaises(NotVoicedYet):
            self.synth(TEXT)
        first = self.store.read(f"todo-{self.key}.json")
        with self.assertRaises(NotVoicedYet):
            self.synth(TEXT)
        self.assertEqual(self.store.read(f"todo-{self.key}.json"), first)

    def test_hit_returns_done_pair(self):
        self.store.write(f"done-{self.key}.mp3", b"ID3x")
        self.store.write(f"done-{self.key}.marks.json",
                         json.dumps(MARKS).encode(), "application/json")
        self.assertEqual(self.synth(TEXT), (b"ID3x", MARKS))

    def test_half_a_done_pair_is_still_a_miss(self):
        self.store.write(f"done-{self.key}.mp3", b"ID3x")
        with self.assertRaises(NotVoicedYet):
            self.synth(TEXT)

    def test_finish_deletes_done_pair(self):
        self.store.write(f"done-{self.key}.mp3", b"ID3x")
        self.store.write(f"done-{self.key}.marks.json", b"[]")
        self.synth.finish(self.key)
        self.assertFalse(self.store.exists(f"done-{self.key}.mp3"))
        self.assertFalse(self.store.exists(f"done-{self.key}.marks.json"))

    def test_key_matches_text_key_for_spoken(self):
        self.assertEqual(
            self.key,
            text_key_for(spoken_form(TEXT, "kokoro"), "am_puck", "kokoro"))
        self.assertEqual(self.spoken, spoken_form(TEXT, "kokoro"))


class QueueBackendTests(SimpleTestCase):
    def test_disk_queue_root_is_separate(self):
        with tempfile.TemporaryDirectory() as cache, override_settings(
                PARODY_WEB_READALOUD_CACHE=cache,
                PARODY_WEB_READALOUD_BUCKET=""):
            store = queue_backend()
            store.write("todo-abc.json", b"{}", "application/json")
            self.assertTrue((Path(cache) / "queue" / "todo-abc.json").exists())
            self.assertFalse((Path(cache) / "todo-abc.json").exists())
            self.assertEqual(store.read("todo-abc.json"), b"{}")

    def test_s3_queue_uses_its_own_prefix(self):
        with override_settings(PARODY_WEB_READALOUD_BUCKET="b",
                               PARODY_WEB_READALOUD_PREFIX="readalong/"):
            store = queue_backend()
        self.assertEqual(store.bucket, "b")
        self.assertEqual(store.key("todo-x.json"), "readalong-queue/todo-x.json")
