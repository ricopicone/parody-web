"""The generation command: what it refuses to do matters most."""
import json
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings

from parody_web_readaloud.models import ReadAlongTrack


class GenerateReadalongTests(TestCase):
    def setUp(self):
        from parody_web.tests_printing import (import_artifact,
                                               make_pdf_with_content)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        make_pdf_with_content(self.root / "print-book.pdf", 20)
        self.book = import_artifact()
        self.cache = tempfile.TemporaryDirectory()
        self.addCleanup(self.cache.cleanup)

    def _settings(self):
        return override_settings(
            PARODY_WEB_PRINT_ROOT=str(self.root),
            PARODY_WEB_READALOUD_CACHE=self.cache.name)

    def _run(self, *args, **kwargs):
        out, err = StringIO(), StringIO()
        with self._settings():
            call_command("generate_readalong", *args, stdout=out, stderr=err,
                         **kwargs)
        return out.getvalue(), err.getvalue()

    def test_an_unknown_book_is_an_error(self):
        with self.assertRaises(CommandError):
            self._run("nosuchbook")

    def test_an_unknown_section_is_an_error(self):
        with self.assertRaises(CommandError):
            self._run(self.book.slug, section="nosuchsection")

    def test_a_section_without_key_mode_html_is_skipped_not_guessed(self):
        """Blank-mode HTML has no answers; a track built from it would reveal
        nothing, and only in front of a student."""
        out, err = self._run(self.book.slug, skip_math=True)
        self.assertIn("no key-mode html", err)
        self.assertEqual(ReadAlongTrack.objects.count(), 0)

    def test_nothing_is_synthesised_without_key_html(self):
        self._run(self.book.slug, skip_math=True)
        self.assertEqual(list(Path(self.cache.name).iterdir()), [])


class KeyArtifactTests(TestCase):
    """The key artifact is read as-is; see key_html_index for why it is not
    numbered, and what has to be understood before it can be."""

    def test_sections_are_indexed_by_both_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            from parody_web_readaloud.management.commands import generate_readalong
            art = {"chapters": [{"slug": "ch", "sections": [
                {"slug": "s1", "hash": "ab", "html": "<p>hello world</p>"}]}]}
            path = Path(tmp) / "key.json"
            path.write_text(json.dumps(art))
            index = generate_readalong.key_html_index(path)
        self.assertEqual(index["ab"], "<p>hello world</p>")
        self.assertEqual(index["ch/s1"], "<p>hello world</p>")


class FakePolly:
    """Polly, minus AWS and minus the bill. Counts what it was asked to say."""

    def __init__(self, **_):
        self.calls = []

    def __call__(self, text):
        self.calls.append(text)
        marks, offset, clock = [], 0, 0
        for word in text.split():
            marks.append({"type": "word", "start": offset, "time": clock,
                          "value": word})
            offset += len(word) + 1
            clock += 100
        return b"ID3-fake-audio", marks


class RepaginationTests(TestCase):
    """Editing chapter 1 must not re-buy chapter 12.

    Reflow cascades, so a one-word edit early in a book changes the slice key
    of nearly every section after it. The audio is keyed on the text instead,
    and this is the test that says so.
    """

    def setUp(self):
        from parody_web.tests_printing import (ARTIFACT, import_artifact,
                                               make_pdf_with_content)
        self.ARTIFACT = ARTIFACT
        self.import_artifact = import_artifact
        self.make_pdf = make_pdf_with_content
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cache = tempfile.TemporaryDirectory()
        self.addCleanup(self.cache.cleanup)

        self.key_artifact = self.root / "key.json"
        self.key_artifact.write_text(json.dumps({"chapters": [{
            "slug": "one", "sections": [
                {"slug": "alpha", "hash": "al",
                 "html": '<p>at a fixed <span class="cloze-key">sampling '
                         'rate</span>, which sets the pace.</p>'}]}]}))

        self.polly = FakePolly()
        self._repaginate(seed=0, sha="c")

    def _repaginate(self, seed, sha):
        """Rebuild the book PDF so every page's content stream differs.

        Stands in for a reflow: the same section, the same words, drawn
        somewhere else — which is exactly what `slice_key_for` is right to
        notice and what the audio must not be charged for.
        """
        self.make_pdf(self.root / "print-book.pdf", 20, seed=seed)
        data = json.loads(json.dumps(self.ARTIFACT))
        data["print"]["sha256"] = sha * 64
        self.book = self.import_artifact(data)

    def _run(self, **kwargs):
        from unittest import mock

        from parody_web_readaloud.management.commands import generate_readalong

        out, err = StringIO(), StringIO()
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root),
                               PARODY_WEB_READALOUD_CACHE=self.cache.name), \
                mock.patch.object(generate_readalong, "PollySynth",
                                  lambda **kw: self.polly):
            call_command("generate_readalong", self.book.slug,
                         key_artifact=str(self.key_artifact), skip_math=True,
                         stdout=out, stderr=err, **kwargs)
        return out.getvalue(), err.getvalue()

    def _track(self):
        return ReadAlongTrack.objects.filter(section_key="al").first()

    def test_the_first_run_synthesises_and_records_both_keys(self):
        out, _ = self._run()
        self.assertIn("made al", out)
        row = self._track()
        self.assertTrue(row.slice_key)
        self.assertTrue(row.text_key)
        self.assertGreater(row.token_count, 0)
        self.assertEqual(len(self.polly.calls), 1)

    def test_the_audio_file_is_named_from_the_text_not_the_pages(self):
        """So the same recording is one file however the book is paginated."""
        self._run()
        row = self._track()
        self.assertTrue(row.audio_name.startswith(row.text_key))
        self.assertNotIn(row.slice_key, row.audio_name)

    def test_an_unchanged_book_is_left_alone(self):
        self._run()
        out, _ = self._run()
        self.assertIn("have al", out)
        self.assertEqual(len(self.polly.calls), 1)

    def test_a_reflow_re_aligns_and_does_not_pay_for_the_audio_again(self):
        self._run()
        before = self._track()

        self._repaginate(seed=5, sha="d")
        out, _ = self._run()

        self.assertIn("moved al", out)
        self.assertIn("0 made, 1 moved", out)
        self.assertEqual(len(self.polly.calls), 1, "Polly was asked twice")

        after = ReadAlongTrack.objects.filter(
            section_key="al").exclude(pk=before.pk).first()
        self.assertIsNotNone(after)
        self.assertNotEqual(after.slice_key, before.slice_key)
        self.assertEqual(after.text_key, before.text_key)
        self.assertEqual(after.audio_name, before.audio_name)
        self.assertEqual(after.duration_ms, before.duration_ms)
        self.assertEqual([(w["word"], w["start_ms"], w["end_ms"], w["token"])
                          for w in after.words],
                         [(w["word"], w["start_ms"], w["end_ms"], w["token"])
                          for w in before.words])

    def test_the_reused_audio_file_is_the_original_one_untouched(self):
        """Not merely a file of the right name: the same bytes, never rewritten.

        Stamped with a sentinel between the runs, so a second synthesis — or a
        needless re-write of identical audio — would be visible here.
        """
        self._run()
        first = Path(self.cache.name) / self._track().audio_name
        first.write_bytes(b"ID3-the-original-recording")

        self._repaginate(seed=5, sha="d")
        self._run()

        row = ReadAlongTrack.objects.filter(section_key="al").first()
        served = Path(self.cache.name) / row.audio_name
        self.assertEqual(served, first)
        self.assertEqual(served.read_bytes(), b"ID3-the-original-recording")

    def test_changing_the_words_does_pay_for_new_audio(self):
        self._run()
        self.key_artifact.write_text(json.dumps({"chapters": [{
            "slug": "one", "sections": [
                {"slug": "alpha", "hash": "al",
                 "html": "<p>at a wholly different fixed pace.</p>"}]}]}))
        self._repaginate(seed=5, sha="d")
        out, _ = self._run()
        self.assertIn("made al", out)
        self.assertEqual(len(self.polly.calls), 2)

    def test_force_re_buys_even_unchanged_words(self):
        """Which is why it must not be the habit for a content edit."""
        self._run()
        self._run(force=True)
        self.assertEqual(len(self.polly.calls), 2)

    def test_dry_run_says_which_sections_would_cost_money(self):
        self._run()
        self._repaginate(seed=5, sha="d")
        out, _ = self._run(dry_run=True)
        self.assertIn("would move al", out)
        self.assertEqual(len(self.polly.calls), 1)
        self.assertEqual(ReadAlongTrack.objects.count(), 1)

    def test_a_track_from_before_the_split_is_given_a_text_key(self):
        """So the FIRST reflow after upgrading is already free, rather than
        one last full-price run to teach every row its own key."""
        self._run()
        ReadAlongTrack.objects.update(text_key="", token_count=0)
        out, _ = self._run()
        self.assertIn("text key recorded", out)
        row = self._track()
        self.assertTrue(row.text_key)
        self.assertGreater(row.token_count, 0)
        self.assertEqual(len(self.polly.calls), 1)

    def test_a_token_stream_that_moved_under_the_same_words_is_not_trusted(self):
        """A figure cloze says nothing at all, so the spoken text can be
        identical while every token index after it has shifted. Timings are
        indexed BY token, so that must fall back to synthesis, not be used."""
        self._run()
        ReadAlongTrack.objects.update(token_count=9999)
        self._repaginate(seed=5, sha="d")
        out, err = self._run()
        self.assertIn("synthesising rather than reusing its timings", err)
        self.assertIn("made al", out)
        self.assertEqual(len(self.polly.calls), 2)

    def test_a_preview_track_is_never_handed_out_as_the_real_thing(self):
        """--no-audio makes timings and no sound, and hashes to the same text
        key. Reusing one for a paid run would leave a class listening to
        silence, which is exactly the failure that only shows up in a room."""
        self._run(no_audio=True)
        self.assertEqual(self._track().audio_name, "")

        self._repaginate(seed=5, sha="d")
        out, _ = self._run()

        self.assertIn("made al", out)
        self.assertEqual(len(self.polly.calls), 1)
        row = ReadAlongTrack.objects.filter(section_key="al").exclude(
            audio_name="").first()
        self.assertIsNotNone(row)
        self.assertTrue((Path(self.cache.name) / row.audio_name).exists())
