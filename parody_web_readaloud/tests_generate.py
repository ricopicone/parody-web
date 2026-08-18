"""The whole pipeline, end to end, without AWS."""
import fitz
from django.test import SimpleTestCase

from parody_web_readaloud.generate import (build_track, chunk_text,
                                          prepare, reuse, synthesise,
                                          text_key_for)
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


def _page_pdf(drop=0):
    """A page reading `at a fixed ______, which sets` with a real rule.

    `drop` shifts everything down the page, standing in for a repagination:
    the same words, typeset somewhere else. Every box moves; not a syllable of
    the narration does.
    """
    doc = fitz.open()
    page = doc.new_page(width=300, height=100)
    page.insert_text((10, 20 + drop), "at a fixed", fontsize=10)
    page.insert_text((95, 20 + drop), ", which sets", fontsize=10)
    page.draw_line(fitz.Point(58, 22 + drop), fitz.Point(92, 22 + drop),
                   width=0.6)
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


class TextKeyTests(SimpleTestCase):
    """The key that pagination is not allowed to touch."""

    def test_the_same_words_in_the_same_voice_key_the_same(self):
        self.assertEqual(text_key_for("hello there", "Matthew", "neural"),
                         text_key_for("hello there", "Matthew", "neural"))

    def test_repagination_cannot_reach_it(self):
        """The whole point: a text key is computed from text, so there is
        nowhere for a page number to enter it."""
        moved = prepare(HTML, _page_pdf(drop=40), math=SkipMath())
        still = prepare(HTML, _page_pdf(), math=SkipMath())
        self.assertNotEqual([s.box for s in moved.placed],
                            [s.box for s in still.placed])
        self.assertEqual(text_key_for(moved.text, "Matthew", "neural"),
                         text_key_for(still.text, "Matthew", "neural"))

    def test_a_different_voice_is_a_different_recording(self):
        self.assertNotEqual(text_key_for("hello", "Matthew", "neural"),
                            text_key_for("hello", "Joanna", "neural"))

    def test_a_different_engine_is_a_different_recording(self):
        self.assertNotEqual(text_key_for("hello", "Matthew", "neural"),
                            text_key_for("hello", "Matthew", "standard"))

    def test_changing_a_word_changes_the_key(self):
        self.assertNotEqual(text_key_for("hello there", "Matthew", "neural"),
                            text_key_for("hello here", "Matthew", "neural"))


class ReuseTests(SimpleTestCase):
    """Repaginating must move the boxes and leave the timings alone.

    This is the whole cost argument: reflow cascades through a book, so editing
    chapter 1 changes the slice key of nearly every section after it. If the
    audio were keyed on that, a typo would re-buy the book.
    """

    def setUp(self):
        self.original = build_track(HTML, _page_pdf(), fake_synth,
                                    math=SkipMath())
        self.moved = prepare(HTML, _page_pdf(drop=40), math=SkipMath())
        self.track = reuse(self.moved, self.original["words"])

    def test_every_timing_survives_untouched(self):
        before = [(w["word"], w["start_ms"], w["end_ms"], w["token"])
                  for w in self.original["words"]]
        after = [(w["word"], w["start_ms"], w["end_ms"], w["token"])
                 for w in self.track["words"]]
        self.assertEqual(before, after)

    def test_the_boxes_are_taken_from_the_new_pagination(self):
        was = [w["y0"] for w in self.original["words"] if "y0" in w]
        now = [w["y0"] for w in self.track["words"] if "y0" in w]
        self.assertTrue(was and now)
        self.assertNotEqual(was, now)
        self.assertEqual(len(was), len(now))

    def test_the_cloze_moves_with_its_rule_and_keeps_its_window(self):
        was, now = self.original["clozes"][0], self.track["clozes"][0]
        self.assertEqual(was["answer"], now["answer"])
        self.assertEqual((was["start_ms"], was["end_ms"]),
                         (now["start_ms"], now["end_ms"]))
        self.assertGreater(now["y0"], was["y0"])

    def test_no_audio_comes_back_because_none_was_bought(self):
        """None, not b"" — the caller must keep the file it already has
        rather than write a second copy of the same recording."""
        self.assertIsNone(self.track["audio_bytes"])
        self.assertEqual(self.track["duration_ms"],
                         self.original["duration_ms"])

    def test_a_token_index_off_the_end_refuses_rather_than_guessing(self):
        """Boxing a word by an index that has moved would put the karaoke mark
        somewhere arbitrary. Paying for the audio again is the lesser harm."""
        stale = [dict(self.original["words"][0], token=9999)]
        self.assertIsNone(reuse(self.moved, stale))

    def test_it_agrees_with_synthesising_the_same_page_afresh(self):
        """Both routes assemble through the same code, so a reused track and a
        freshly bought one of the same words on the same page must match."""
        fresh = synthesise(self.moved, fake_synth)
        for field in ("words", "clozes", "regions", "pages"):
            self.assertEqual(fresh[field], self.track[field])


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


class ChunkTextPartitionTests(SimpleTestCase):
    """Chunking must bound every piece and lose nothing.

    The timings are resolved against character offsets into the joined text, so
    a chunking that drops or adds a character shifts every later word's box.
    """

    def test_an_overlong_run_with_no_sentence_break_is_still_split(self):
        """SRE renders one equation as hundreds of words and no full stop.
        Polly rejected exactly this, mid-book, in production."""
        text = " ".join(["StartFraction"] * 800)
        chunks = chunk_text(text, limit=200)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), 200)

    def test_the_partition_is_exact(self):
        text = " ".join(f"w{i}" for i in range(500))
        chunks = chunk_text(text, limit=97)
        self.assertEqual(" ".join(chunks), text)

    def test_the_partition_is_exact_with_sentences(self):
        text = " ".join(["alpha beta gamma."] * 60)
        chunks = chunk_text(text, limit=120)
        self.assertEqual(" ".join(chunks), text)

    def test_sentence_ends_are_still_preferred(self):
        text = "one two three. four five six. seven eight nine."
        chunks = chunk_text(text, limit=30)
        self.assertTrue(all(c.endswith(".") for c in chunks[:-1]), chunks)

    def test_a_single_word_over_the_limit_goes_out_whole(self):
        """Splitting inside a word would corrupt the offset mapping."""
        text = "x" * 50
        self.assertEqual(chunk_text(text, limit=10), [text])
