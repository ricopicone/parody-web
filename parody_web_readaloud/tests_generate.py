"""The whole pipeline, end to end, without AWS."""
import fitz
from django.test import SimpleTestCase

from parody_web_readaloud.generate import build_track, chunk_text
from parody_web_readaloud.speech import SkipMath


def fake_synth(text):
    """One mark per word, 100ms apart, at the right character offsets."""
    marks, offset, time_ms = [], 0, 0
    for word in text.split():
        marks.append({"type": "word", "start": offset, "time": time_ms,
                      "value": word})
        offset += len(word) + 1
        time_ms += 100
    return b"ID3-fake-audio", marks


def _page_pdf():
    """A page reading `at a fixed ______, which sets` with a real rule."""
    doc = fitz.open()
    page = doc.new_page(width=300, height=100)
    page.insert_text((10, 20), "at a fixed", fontsize=10)
    page.insert_text((95, 20), ", which sets", fontsize=10)
    page.draw_line(fitz.Point(58, 22), fitz.Point(92, 22), width=0.6)
    out = doc.tobytes()
    doc.close()
    return out


HTML = ('<p>at a fixed <span class="cloze-key">sampling rate</span>'
        ', which sets</p>')


class BuildTrackTests(SimpleTestCase):
    def setUp(self):
        self.track = build_track(HTML, _page_pdf(), fake_synth, math=SkipMath())

    def test_every_spoken_word_carries_a_timing(self):
        self.assertTrue(self.track["words"])
        for word in self.track["words"]:
            self.assertIn("start_ms", word)
            self.assertIn("end_ms", word)
            self.assertLessEqual(word["start_ms"], word["end_ms"])

    def test_the_answer_is_spoken(self):
        spoken = [w["word"] for w in self.track["words"]]
        self.assertIn("sampling", spoken)
        self.assertIn("rate,", spoken)

    def test_prose_words_are_placed_on_the_page(self):
        placed = [w for w in self.track["words"] if "page" in w]
        self.assertTrue(placed)
        self.assertEqual(placed[0]["page"], 0)

    def test_the_cloze_is_reported_with_the_rule_box_and_a_window(self):
        self.assertEqual(len(self.track["clozes"]), 1)
        cloze = self.track["clozes"][0]
        self.assertEqual(cloze["answer"], "sampling rate")
        self.assertEqual(cloze["kind"], "cloze")
        self.assertEqual(cloze["page"], 0)
        self.assertLess(cloze["x0"], cloze["x1"])
        self.assertLessEqual(cloze["start_ms"], cloze["end_ms"])

    def test_the_cloze_becomes_due_after_its_answer_is_spoken(self):
        cloze = self.track["clozes"][0]
        said = {w["word"]: w for w in self.track["words"]}
        self.assertGreaterEqual(cloze["end_ms"], said["sampling"]["end_ms"])

    def test_audio_comes_back_for_storing(self):
        self.assertEqual(self.track["audio_bytes"], b"ID3-fake-audio")
        self.assertGreater(self.track["duration_ms"], 0)

    def test_a_section_with_no_clozes_still_produces_a_track(self):
        track = build_track("<p>just prose here</p>", _page_pdf(), fake_synth,
                            math=SkipMath())
        self.assertEqual(track["clozes"], [])
        self.assertTrue(track["words"])


class ChunkTextTests(SimpleTestCase):
    def test_short_text_is_one_chunk(self):
        self.assertEqual(chunk_text("One. Two."), ["One. Two."])

    def test_empty_text_is_no_chunks(self):
        self.assertEqual(chunk_text(""), [])

    def test_long_text_splits_on_sentence_boundaries(self):
        text = " ".join(["This is a sentence."] * 400)
        chunks = chunk_text(text, limit=200)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), 200)
            self.assertTrue(chunk.endswith("."))

    def test_no_words_are_lost_in_chunking(self):
        text = " ".join(["Alpha beta gamma."] * 50)
        rejoined = " ".join(chunk_text(text, limit=120))
        self.assertEqual(rejoined.split(), text.split())
