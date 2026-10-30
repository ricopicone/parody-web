"""prune_print_cache: the print cache holds only what can be cut again, and
keeps nothing that can no longer be reached."""

import io
import os
import tempfile
import time
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from parody_web.models import BookPrintVersion, TwinPdf
from parody_web.tests_printing import import_artifact, make_pdf_with_content

OLD = "0" * 12
DAY = 86400


def _file(path, age=0.0, size=10):
    """A file of ``size`` bytes written ``age`` seconds ago."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    when = time.time() - age
    os.utime(path, (when, when))
    return path


class PruneCacheTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "live"
        self.archive = Path(self.tmp.name) / "archive"
        self.root.mkdir()
        make_pdf_with_content(self.root / "print-book.pdf", 4)
        self.book = import_artifact()
        self.book.print_sha256 = "a" * 64
        self.book.save()
        self.cache = self.root / ".cache"
        self.ed = self.cache / self.book.slug / "_"
        self.now = self.book.print_sha256[:12]
        TwinPdf.objects.create(book=self.book, language="de", pdf="print-book-de.pdf",
                               sha256="b" * 64, english_sha256=self.book.print_sha256)
        self.twin = "b" * 12

    def _prune(self, *args):
        out = io.StringIO()
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root),
                               PARODY_WEB_PRINT_ARCHIVE=str(self.archive)):
            call_command("prune_print_cache", *args, stdout=out)
        return out.getvalue()

    def test_cuts_of_older_builds_and_twins_go_and_current_ones_stay(self):
        old = 2 * DAY
        keep = [_file(self.ed / self.now / "ch-a.pdf", old),
                _file(self.ed / f"twin-de-{self.twin}" / "ch-a-1-2.pdf", old),
                _file(self.ed / f"twin-de-{self.twin}-sbs" / "ch-a-1-2.pdf", old),
                _file(self.ed / f"twin-de-{self.twin}-paired" / "ch-a-1-2-abcd1234.pdf", old)]
        gone = [_file(self.ed / OLD / "ch-a.pdf", old),
                _file(self.ed / f"twin-de-{OLD}-paired" / "ch-a-1-2-abcd1234.pdf", old),
                _file(self.ed / f"twin-zh-{self.twin}" / "ch-a-1-2.pdf", old),
                _file(self.cache / "gone-book" / "_" / OLD / "ch-a.pdf", old)]
        out = self._prune()
        self.assertTrue(all(p.exists() for p in keep), out)
        self.assertFalse(any(p.exists() for p in gone), out)
        self.assertFalse((self.ed / OLD).exists())  # and its emptied directory
        self.assertIn("removed 4 files", out)

    def test_a_key_twins_cuts_go_with_it(self):
        TwinPdf.objects.filter(book=self.book).update(
            key_pdf="print-book-de-key.pdf", key_sha256="e" * 64)
        old, key = 2 * DAY, "e" * 12
        keep = [_file(self.ed / f"twin-de-{key}-key" / "ch-a-1-2.pdf", old),
                _file(self.ed / f"twin-de-{key}-key-sbs" / "ch-a-1-2.pdf", old),
                _file(self.ed / f"twin-de-{key}-key-paired" / "ch-a-1-2-abcd1234.pdf", old)]
        gone = [_file(self.ed / f"twin-de-{OLD}-key-paired" / "ch-a-1-2-abcd1234.pdf", old)]
        out = self._prune()
        self.assertTrue(all(p.exists() for p in keep), out)
        self.assertFalse(any(p.exists() for p in gone), out)
        self.assertNotIn("left alone", out)

    def test_cuts_of_an_archived_version_stay_while_it_is_archived_and_fresh(self):
        BookPrintVersion.objects.create(book=self.book, sha256="c" * 64)
        _file(self.archive / self.book.slug / f"{'c' * 64}.pdf")
        version = self.ed / f"v{'c' * 12}"
        fresh = _file(version / "ch-a-1-2.pdf", 2 * DAY)
        stale = _file(version / "ch-b-3-4.pdf", 40 * DAY)
        orphan = _file(self.ed / f"v{OLD}" / "ch-a-1-2.pdf", 2 * DAY)
        self._prune()
        self.assertTrue(fresh.exists())
        self.assertFalse(stale.exists())  # cut again from the archive if asked for
        self.assertFalse(orphan.exists())  # its version is gone from the archive

    def test_an_annotated_copy_superseded_by_newer_ink_goes(self):
        pages = self.cache / "annotated" / "7" / self.book.slug
        older = _file(pages / "ch-a-abcdef012345-de-111111111111.pdf", 3 * DAY)
        newer = _file(pages / "ch-a-abcdef012345-de-222222222222.pdf", 2 * DAY)
        english = _file(pages / "ch-a-abcdef012345-333333333333.pdf", 3 * DAY)
        ancient = _file(pages / "ch-b-abcdef012345-444444444444.pdf", 40 * DAY)
        book = self.cache / "annotated-book" / "7" / self.book.slug
        whole = _file(book / f"{self.now}-555555555555.pdf", 2 * DAY)
        whole_old_build = _file(book / f"{OLD}-666666666666.pdf", 1 * DAY)
        self._prune()
        self.assertTrue(newer.exists() and english.exists() and whole.exists())
        self.assertFalse(older.exists() or ancient.exists() or whole_old_build.exists())

    def test_a_file_written_just_now_is_never_touched(self):
        # a request that read the book before the import may still be
        # writing into what is now an older build's directory
        writing = _file(self.ed / OLD / "ch-a.pdf", age=5)
        self._prune()
        self.assertTrue(writing.exists())

    def test_interrupted_writes_go_and_what_it_does_not_know_stays(self):
        tmp = _file(self.ed / self.now / "ch-a.pdf.123.tmp", 2 * DAY)
        unknown = _file(self.ed / "something-else" / "x.pdf", 40 * DAY)
        out = self._prune()
        self.assertFalse(tmp.exists())
        self.assertTrue(unknown.exists())
        self.assertIn("something-else", out)

    def test_dry_run_reports_and_deletes_nothing(self):
        stale = _file(self.ed / OLD / "ch-a.pdf", 2 * DAY, size=2048)
        out = self._prune("--dry-run")
        self.assertTrue(stale.exists())
        self.assertIn("would remove 1 files", out)

    def test_refuses_a_cache_that_holds_the_archive(self):
        # the archive is the one copy of the pages under older notes
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root),
                               PARODY_WEB_PRINT_ARCHIVE=str(self.cache / "archive")):
            with self.assertRaises(CommandError):
                call_command("prune_print_cache", stdout=io.StringIO())
