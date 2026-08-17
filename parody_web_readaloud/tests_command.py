"""The generation command: what it refuses to do matters most."""
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
