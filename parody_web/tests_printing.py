"""Per-section print PDFs: import, slicing, gating, and chrome."""
import json
import tempfile
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings

from parody_web import printing
from parody_web.models import Book, Section

ARTIFACT = {
    "schema_version": 2,
    "slug": "print-book",
    "title": "Print Book",
    "author": ["A. Author"],
    "print": {"pdf": "print-book.pdf", "pages": 20, "sha256": "c" * 64},
    "chapters": [{
        "title": "One", "slug": "one", "hash": "c1",
        "sections": [
            {"title": "One", "slug": "lead-in", "hash": "li",
             "html": "<p>Intro.</p>", "print": {"pages": [3, 5]}},
            {"title": "Alpha", "slug": "alpha", "hash": "al",
             "html": "<p>Alpha.</p>", "print": {"pages": [5, 9]}},
            {"title": "Beta", "slug": "beta", "hash": "be",
             "html": "<p>Beta.</p>"},
        ],
    }],
}


def import_artifact(data=None, **opts):
    payload = json.loads(json.dumps(data or ARTIFACT))
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(payload, f)
        path = f.name
    call_command("import_artifact", path, **opts)
    Path(path).unlink()
    return Book.objects.get(slug=payload["slug"])


class ImportPrintFieldsTests(TestCase):
    def test_book_carries_the_print_metadata(self):
        book = import_artifact()
        self.assertEqual(book.print_pdf, "print-book.pdf")
        self.assertEqual(book.print_pages, 20)
        self.assertEqual(book.print_sha256, "c" * 64)

    def test_sections_carry_their_page_range(self):
        book = import_artifact()
        alpha = book.sections.get(slug="alpha")
        self.assertEqual(alpha.print_pages, [5, 9])

    def test_a_section_without_a_range_is_null(self):
        book = import_artifact()
        self.assertIsNone(book.sections.get(slug="beta").print_pages)

    def test_page_count_is_inclusive_of_both_ends(self):
        book = import_artifact()
        # [5, 9] shares page 5 with the lead-in and page 9 with what follows
        self.assertEqual(book.sections.get(slug="alpha").print_page_count, 5)
        self.assertIsNone(book.sections.get(slug="beta").print_page_count)

    def test_an_artifact_with_no_print_block_imports_cleanly(self):
        data = json.loads(json.dumps(ARTIFACT))
        del data["print"]
        for sec in data["chapters"][0]["sections"]:
            sec.pop("print", None)
        book = import_artifact(data)
        self.assertEqual(book.print_pdf, "")
        self.assertIsNone(book.print_pages)
        self.assertTrue(all(s.print_pages is None for s in book.sections.all()))


class PrintSettingsTests(SimpleTestCase):
    def test_no_root_configured_means_the_feature_is_off(self):
        with override_settings(PARODY_WEB_PRINT_ROOT=""):
            self.assertIsNone(printing.print_root())

    def test_cache_defaults_inside_the_print_root(self):
        with tempfile.TemporaryDirectory() as td:
            with override_settings(PARODY_WEB_PRINT_ROOT=td,
                                   PARODY_WEB_PRINT_CACHE=""):
                self.assertEqual(printing.print_cache_root(),
                                 Path(td) / ".cache")

    def test_cache_can_be_pointed_elsewhere(self):
        with tempfile.TemporaryDirectory() as td, \
                tempfile.TemporaryDirectory() as cache:
            with override_settings(PARODY_WEB_PRINT_ROOT=td,
                                   PARODY_WEB_PRINT_CACHE=cache):
                self.assertEqual(printing.print_cache_root(), Path(cache))

    def test_a_non_directory_root_is_rejected_at_startup(self):
        with self.assertRaises(ImproperlyConfigured):
            printing.validate_print_settings("/definitely/not/here", "", "")

    def test_xaccel_requires_the_cache_to_live_under_the_root(self):
        # nginx maps ONE internal location at the print root, so a cache
        # outside it could never be streamed.
        with tempfile.TemporaryDirectory() as td, \
                tempfile.TemporaryDirectory() as outside:
            with self.assertRaises(ImproperlyConfigured):
                printing.validate_print_settings(td, outside, "/print-internal/")
            printing.validate_print_settings(td, "", "/print-internal/")

    def test_valid_settings_pass(self):
        with tempfile.TemporaryDirectory() as td:
            printing.validate_print_settings(td, "", "")


def make_pdf(path, pages):
    """A real multi-page PDF."""
    from pypdf import PdfWriter
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=200)
    with open(path, "wb") as f:
        writer.write(f)
    return path


def make_pdf_with_content(path, pages, seed=0):
    """A PDF whose pages differ from one another.

    `make_pdf` writes blank pages, which are byte-identical to each other — no
    use at all for testing a key that is supposed to distinguish one page range
    from another.

    `seed` shifts every page's drawing, standing in for a rebuild that really
    did change the content. Re-running with the same seed stands in for a
    rebuild that changed something elsewhere in the book: byte-identical pages,
    and so — by design — an unchanged version key.
    """
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, NameObject
    writer = PdfWriter()
    for i in range(pages):
        page = writer.add_blank_page(width=200, height=200)
        stream = DecodedStreamObject()
        stream.set_data(
            f"0 0 1 RG 10 {10 + i * 7 + seed} m 100 100 l S".encode())
        page[NameObject("/Contents")] = writer._add_object(stream)
    with open(path, "wb") as f:
        writer.write(f)
    return path


def _templates_with_shadow():
    """TEMPLATES with a host-style shadow directory ahead of the app loader."""
    from django.conf import settings as _s
    conf = json.loads(json.dumps(_s.TEMPLATES, default=str))
    conf[0]["DIRS"] = [str(Path(__file__).resolve().parent.parent
                           / "tests" / "shadow_templates")]
    return conf


class SliceKeyTests(TestCase):
    """The version key: identity for a section's pages.

    Everything in the annotation feature rests on one property — a rebuild that
    does not touch this section must leave its key alone, or every reader's
    notes look orphaned.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        make_pdf_with_content(self.root / "print-book.pdf", 20)
        self.book = import_artifact()
        self.section = self.book.sections.get(slug="alpha")   # pages [5, 9]

    def test_the_key_is_stable_across_calls(self):
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            first = printing.slice_key_for(self.book, self.section)
            second = printing.slice_key_for(self.book, self.section)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)

    def test_a_different_page_range_gives_a_different_key(self):
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            mine = printing.slice_key_for(self.book, self.section)
            other = printing.slice_key_for(
                self.book, self.book.sections.get(slug="lead-in"))
        self.assertNotEqual(mine, other)

    def test_editing_a_different_section_leaves_this_key_alone(self):
        """The whole point. Page 1 changes; alpha (pages 5-9) must not move."""
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            before = printing.slice_key_for(self.book, self.section)
            self._rewrite_page(0, "0 0 1 RG 10 99 m 100 100 l S")
            after = printing.slice_key_for(self.book, self.section)
        self.assertEqual(before, after)

    def test_editing_this_section_changes_the_key(self):
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            before = printing.slice_key_for(self.book, self.section)
            self._rewrite_page(5, "0 0 1 RG 10 99 m 100 100 l S")
            after = printing.slice_key_for(self.book, self.section)
        self.assertNotEqual(before, after)

    def test_the_key_needs_no_slice_to_exist(self):
        """It is asked for every section on a page; slicing each would be absurd."""
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root),
                               PARODY_WEB_PRINT_CACHE=str(self.root / "cache")):
            printing.slice_key_for(self.book, self.section)
        self.assertFalse((self.root / "cache").exists())

    def test_a_section_with_no_page_range_has_no_key(self):
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            self.assertIsNone(printing.slice_key_for(
                self.book, self.book.sections.get(slug="beta")))

    def test_no_pdf_on_disk_means_no_key(self):
        (self.root / "print-book.pdf").unlink()
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            self.assertIsNone(printing.slice_key_for(self.book, self.section))

    def _rewrite_page(self, index, ops):
        """Rewrite one page's drawing, as a rebuild of the book would."""
        from pypdf import PdfReader, PdfWriter
        from pypdf.generic import DecodedStreamObject, NameObject
        path = self.root / "print-book.pdf"
        reader = PdfReader(str(path))
        writer = PdfWriter()
        for i, page in enumerate(reader.pages):
            writer.add_page(page)
            if i == index:
                stream = DecodedStreamObject()
                stream.set_data(ops.encode())
                writer.pages[i][NameObject("/Contents")] = writer._add_object(stream)
        with open(path, "wb") as f:
            writer.write(f)
        printing._reader.cache_clear()


class ArchiveTests(TestCase):
    """Retention: the live PDF is overwritten by every deploy, so a reader
    whose notes are on last month's version would otherwise have notes on a
    document that exists nowhere."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "live"
        self.archive = Path(self.tmp.name) / "archive"
        self.root.mkdir()
        make_pdf_with_content(self.root / "print-book.pdf", 20)
        self.book = import_artifact()

    def _settings(self):
        return override_settings(PARODY_WEB_PRINT_ROOT=str(self.root),
                                 PARODY_WEB_PRINT_ARCHIVE=str(self.archive))

    def test_archiving_copies_the_pdf_and_records_it(self):
        with self._settings():
            version = printing.archive_book_pdf(self.book)
            path = printing.archived_pdf_path(self.book.slug, self.book.print_sha256)
        self.assertEqual(version.sha256, self.book.print_sha256)
        self.assertEqual(version.page_count, 20)
        self.assertTrue(path.is_file())

    def test_archiving_twice_writes_one_row_and_one_file(self):
        from parody_web.models import BookPrintVersion
        with self._settings():
            first = printing.archive_book_pdf(self.book)
            again = printing.archive_book_pdf(self.book)
        self.assertEqual(first.pk, again.pk)
        self.assertEqual(BookPrintVersion.objects.count(), 1)

    def test_an_unconfigured_archive_is_a_no_op(self):
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root),
                               PARODY_WEB_PRINT_ARCHIVE=""):
            self.assertIsNone(printing.archive_book_pdf(self.book))

    def test_the_old_version_survives_the_book_being_replaced(self):
        with self._settings():
            old_sha = self.book.print_sha256
            printing.archive_book_pdf(self.book)
            # a new release lands: the live file is overwritten in place
            make_pdf_with_content(self.root / "print-book.pdf", 24)
            printing._reader.cache_clear()
            self.book.print_sha256 = "d" * 64
            self.book.save()
            printing.archive_book_pdf(self.book)
            old = printing.archived_pdf_path(self.book.slug, old_sha)
        self.assertTrue(old.is_file())
        from pypdf import PdfReader
        self.assertEqual(len(PdfReader(str(old)).pages), 20)

    def test_import_archives_without_being_asked(self):
        from parody_web.models import BookPrintVersion
        with self._settings():
            import_artifact()
        self.assertEqual(
            BookPrintVersion.objects.filter(sha256="c" * 64).count(), 1)

    def test_an_archive_failure_does_not_fail_the_import(self):
        """A book that imports is worth more than a version that is kept."""
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root),
                               PARODY_WEB_PRINT_ARCHIVE="/proc/nope/denied"):
            book = import_artifact()
        self.assertEqual(book.slug, "print-book")


class VersionedSliceTests(TestCase):
    """Cutting a section out of an ARCHIVED book, after the live one moved on."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.root, self.archive, self.cache = base / "live", base / "arc", base / "cache"
        self.root.mkdir()
        make_pdf_with_content(self.root / "print-book.pdf", 20)
        self.book = import_artifact()

    def _settings(self):
        return override_settings(PARODY_WEB_PRINT_ROOT=str(self.root),
                                 PARODY_WEB_PRINT_ARCHIVE=str(self.archive),
                                 PARODY_WEB_PRINT_CACHE=str(self.cache))

    def test_slices_an_old_version_after_the_live_book_was_replaced(self):
        with self._settings():
            old_sha = self.book.print_sha256
            printing.archive_book_pdf(self.book)
            make_pdf_with_content(self.root / "print-book.pdf", 24)
            printing._reader.cache_clear()
            path = printing.versioned_section_pdf(self.book, old_sha, [5, 9], "alpha")
        self.assertIsNotNone(path)
        from pypdf import PdfReader
        self.assertEqual(len(PdfReader(str(path)).pages), 5)

    def test_a_version_that_was_never_archived_is_none(self):
        """It must 404 rather than quietly serve different pages under a key
        the reader believes is theirs."""
        with self._settings():
            self.assertIsNone(
                printing.versioned_section_pdf(self.book, "f" * 64, [5, 9], "alpha"))

    def test_no_archive_configured_is_none(self):
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root),
                               PARODY_WEB_PRINT_ARCHIVE="",
                               PARODY_WEB_PRINT_CACHE=str(self.cache)):
            self.assertIsNone(printing.versioned_section_pdf(
                self.book, self.book.print_sha256, [5, 9], "alpha"))

    def test_two_versions_cache_separately(self):
        with self._settings():
            printing.archive_book_pdf(self.book)
            first = printing.versioned_section_pdf(
                self.book, self.book.print_sha256, [5, 9], "alpha")
            make_pdf_with_content(self.root / "print-book.pdf", 24)
            printing._reader.cache_clear()
            self.book.print_sha256 = "e" * 64
            self.book.save()
            printing.archive_book_pdf(self.book)
            second = printing.versioned_section_pdf(self.book, "e" * 64, [5, 9], "alpha")
        self.assertNotEqual(first, second)
        self.assertTrue(first.is_file() and second.is_file())


class PruneArchiveTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.root, self.archive = base / "live", base / "arc"
        self.root.mkdir()
        make_pdf_with_content(self.root / "print-book.pdf", 20)
        self.book = import_artifact()

    def _archive_an_extra_version(self, sha):
        from parody_web.models import BookPrintVersion
        path = printing.archived_pdf_path(self.book.slug, sha)
        path.parent.mkdir(parents=True, exist_ok=True)
        make_pdf_with_content(path, 4)
        BookPrintVersion.objects.create(book=self.book, sha256=sha,
                                        filename=path.name, page_count=4)
        return path

    def _settings(self):
        return override_settings(PARODY_WEB_PRINT_ROOT=str(self.root),
                                 PARODY_WEB_PRINT_ARCHIVE=str(self.archive))

    def test_a_dry_run_is_the_default(self):
        from io import StringIO
        with self._settings():
            printing.archive_book_pdf(self.book)
            orphan = self._archive_an_extra_version("1" * 64)
            out = StringIO()
            call_command("prune_print_archive", stdout=out)
        self.assertTrue(orphan.is_file())
        self.assertIn("would remove", out.getvalue())

    def test_it_keeps_the_current_version(self):
        from io import StringIO
        with self._settings():
            printing.archive_book_pdf(self.book)
            current = printing.archived_pdf_path(self.book.slug, self.book.print_sha256)
            call_command("prune_print_archive", "--yes", stdout=StringIO())
        self.assertTrue(current.is_file())

    def test_it_removes_a_version_nothing_references(self):
        from io import StringIO
        with self._settings():
            printing.archive_book_pdf(self.book)
            orphan = self._archive_an_extra_version("1" * 64)
            call_command("prune_print_archive", "--yes", stdout=StringIO())
        self.assertFalse(orphan.is_file())

    def test_it_keeps_a_version_a_reader_annotated(self):
        """The whole reason this command is not automatic."""
        from io import StringIO
        from parody_web_annotate.models import InkLayer
        from django.contrib.auth import get_user_model
        reader = get_user_model().objects.create_user("r", password="x")
        with self._settings():
            printing.archive_book_pdf(self.book)
            annotated = self._archive_an_extra_version("1" * 64)
            InkLayer.objects.create(
                user=reader, book_slug=self.book.slug, edition_id="",
                section_key="al", slice_key="9" * 64, book_sha256="1" * 64,
                pages=[5, 9], strokes={})
            call_command("prune_print_archive", "--yes", stdout=StringIO())
        self.assertTrue(annotated.is_file())


class SlicingTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        make_pdf(self.root / "print-book.pdf", 20)

    def _book(self):
        return import_artifact()

    def test_book_pdf_path_finds_the_file(self):
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            self.assertEqual(printing.book_pdf_path(self._book()),
                             self.root / "print-book.pdf")

    def test_book_pdf_path_is_none_when_the_file_is_absent(self):
        (self.root / "print-book.pdf").unlink()
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            self.assertIsNone(printing.book_pdf_path(self._book()))

    def test_slice_has_exactly_the_inclusive_page_count(self):
        from pypdf import PdfReader
        book = self._book()
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            out = printing.section_pdf_path(book, book.sections.get(slug="alpha"))
        # [5, 9] inclusive = 5 pages
        self.assertEqual(len(PdfReader(str(out)).pages), 5)

    def test_the_cache_path_carries_the_source_hash(self):
        book = self._book()
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            out = printing.section_pdf_path(book, book.sections.get(slug="alpha"))
        self.assertIn(book.print_sha256[:12], str(out))

    def test_a_repaginated_book_gets_a_fresh_cache_path(self):
        book = self._book()
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            first = printing.section_pdf_path(
                book, book.sections.get(slug="alpha"))
            Book.objects.filter(pk=book.pk).update(print_sha256="d" * 64)
            book.refresh_from_db()
            second = printing.section_pdf_path(
                book, book.sections.get(slug="alpha"))
        self.assertNotEqual(first, second)

    def test_a_second_request_reuses_the_cached_slice(self):
        book = self._book()
        section = book.sections.get(slug="alpha")
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            first = printing.section_pdf_path(book, section)
            stamp = first.stat().st_mtime_ns
            second = printing.section_pdf_path(book, section)
        self.assertEqual(first, second)
        self.assertEqual(stamp, second.stat().st_mtime_ns)

    def test_a_section_with_no_range_has_no_slice(self):
        book = self._book()
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            self.assertIsNone(printing.section_pdf_path(
                book, book.sections.get(slug="beta")))

    def test_a_range_past_the_end_of_the_pdf_is_clamped(self):
        from pypdf import PdfReader
        book = self._book()
        section = book.sections.get(slug="alpha")
        Section.objects.filter(pk=section.pk).update(print_pages=[19, 40])
        section.refresh_from_db()
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            out = printing.section_pdf_path(book, section)
        self.assertEqual(len(PdfReader(str(out)).pages), 2)  # pages 19-20

    def test_no_print_root_means_no_slice(self):
        book = self._book()
        with override_settings(PARODY_WEB_PRINT_ROOT=""):
            self.assertIsNone(printing.section_pdf_path(
                book, book.sections.get(slug="alpha")))


class PdfPolicyTests(TestCase):
    def setUp(self):
        from django.test import RequestFactory
        self.rf = RequestFactory()
        self.book = import_artifact()

    def _policy(self):
        from parody_web.access import DefaultPolicy
        return DefaultPolicy()

    def _anon(self):
        from django.contrib.auth.models import AnonymousUser
        req = self.rf.get("/")
        req.user = AnonymousUser()
        return req

    def _owner(self):
        from django.contrib.auth import get_user_model
        req = self.rf.get("/")
        req.user = get_user_model()(username="owner")
        return req

    def test_a_full_sections_pdf_is_public(self):
        section = self.book.sections.get(slug="alpha")
        self.assertTrue(
            self._policy().can_download_section_pdf(self._anon(), section))

    def test_a_preview_sections_pdf_is_owner_only(self):
        section = self.book.sections.get(slug="alpha")
        Section.objects.filter(pk=section.pk).update(preview=True)
        section.refresh_from_db()
        self.assertFalse(
            self._policy().can_download_section_pdf(self._anon(), section))
        self.assertTrue(
            self._policy().can_download_section_pdf(self._owner(), section))

    def test_the_full_book_pdf_is_public_by_default(self):
        self.assertTrue(
            self._policy().can_download_book_pdf(self._anon(), self.book))

    def test_the_full_book_pdf_can_be_turned_off_for_a_site(self):
        with override_settings(PARODY_WEB_PUBLIC_BOOK_PDF=False):
            self.assertFalse(
                self._policy().can_download_book_pdf(self._anon(), self.book))
            # the owner always keeps it
            self.assertTrue(
                self._policy().can_download_book_pdf(self._owner(), self.book))


class PdfViewTests(TestCase):
    def setUp(self):
        from django.test import Client
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        make_pdf(self.root / "print-book.pdf", 20)
        self.book = import_artifact()
        self.client = Client()

    def _login(self):
        from django.contrib.auth import get_user_model
        get_user_model().objects.create_user("owner", password="pw")
        self.client.login(username="owner", password="pw")

    def _body(self, resp):
        return b"".join(resp.streaming_content) if resp.streaming else resp.content

    def test_section_pdf_downloads_with_the_right_page_count(self):
        import io

        from pypdf import PdfReader
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            resp = self.client.get("/one/alpha/pdf/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        self.assertEqual(len(PdfReader(io.BytesIO(self._body(resp))).pages), 5)

    def test_the_pdf_may_be_framed_by_its_own_viewer(self):
        # The default stage in _pdf_view_stage.html is an <iframe> around this
        # very URL, and a host inherits Django's X_FRAME_OPTIONS = "DENY",
        # which forbids framing even same-origin. Without an explicit
        # same-origin exemption the shipped viewer renders its chrome around a
        # frame the browser refuses. SAMEORIGIN still blocks cross-origin
        # framing, which is the clickjacking that matters.
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            resp = self.client.get("/one/alpha/pdf/?inline=1")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("X-Frame-Options"), "SAMEORIGIN")

    def test_the_filename_names_the_section(self):
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            resp = self.client.get("/one/alpha/pdf/")
        self.assertIn("alpha", resp["Content-Disposition"].lower())
        self.assertIn(".pdf", resp["Content-Disposition"])

    def test_a_preview_sections_pdf_is_refused_to_the_public(self):
        # THE leak this whole design exists to prevent: the print PDF holds the
        # full text of a section the online artifact deliberately withholds.
        Section.objects.filter(book=self.book, slug="alpha").update(preview=True)
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            resp = self.client.get("/one/alpha/pdf/")
        self.assertEqual(resp.status_code, 404)

    def test_the_owner_still_gets_a_preview_sections_pdf(self):
        Section.objects.filter(book=self.book, slug="alpha").update(preview=True)
        self._login()
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            resp = self.client.get("/one/alpha/pdf/")
        self.assertEqual(resp.status_code, 200)

    def test_a_section_with_no_range_has_no_pdf(self):
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            self.assertEqual(self.client.get("/one/beta/pdf/").status_code, 404)

    def test_full_book_pdf_is_served_by_default(self):
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            resp = self.client.get("/pdf/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")

    def test_full_book_pdf_can_be_withheld_from_the_public(self):
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root),
                               PARODY_WEB_PUBLIC_BOOK_PDF=False):
            self.assertEqual(self.client.get("/pdf/").status_code, 404)
            self._login()
            self.assertEqual(self.client.get("/pdf/").status_code, 200)

    def test_a_missing_file_on_disk_is_a_404_not_a_500(self):
        (self.root / "print-book.pdf").unlink()
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            self.assertEqual(self.client.get("/one/alpha/pdf/").status_code, 404)
            self.assertEqual(self.client.get("/pdf/").status_code, 404)

    def test_no_print_root_is_a_404_not_a_500(self):
        with override_settings(PARODY_WEB_PRINT_ROOT=""):
            self.assertEqual(self.client.get("/one/alpha/pdf/").status_code, 404)

    def test_xaccel_delegates_streaming_to_nginx(self):
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root),
                               PARODY_WEB_PRINT_XACCEL="/print-internal/"):
            resp = self.client.get("/one/alpha/pdf/")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp["X-Accel-Redirect"].startswith("/print-internal/"))
        self.assertEqual(resp.content, b"")


class PdfViewerTests(TestCase):
    def setUp(self):
        from django.test import Client
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        make_pdf(self.root / "print-book.pdf", 20)
        self.book = import_artifact()
        self.client = Client()

    def test_the_viewer_renders_and_points_at_the_section_pdf(self):
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            resp = self.client.get("/one/alpha/pdf/view/")
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn("/one/alpha/pdf/", html)
        self.assertIn("Alpha", html)

    def test_the_default_stage_is_still_the_iframe(self):
        """A host that installs nothing must see no change."""
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            html = self.client.get("/one/alpha/pdf/view/").content.decode()
        self.assertIn("<iframe", html)
        self.assertIn("/one/alpha/pdf/?inline=1", html)

    def test_the_stage_carries_the_join_key(self):
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            html = self.client.get("/one/alpha/pdf/view/").content.decode()
        self.assertIn('data-section-key="al"', html)

    def test_the_undrawable_overlay_is_gone(self):
        """It was a transparent div over an iframe. A page cannot draw onto
        the browser's PDF plugin, so keeping it only misled the next reader."""
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            html = self.client.get("/one/alpha/pdf/view/").content.decode()
        self.assertNotIn("pdf-annotation-layer", html)

    def test_a_host_can_replace_the_stage_outright(self):
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root),
                               TEMPLATES=_templates_with_shadow()):
            html = self.client.get("/one/alpha/pdf/view/").content.decode()
        self.assertIn("REPLACED-STAGE", html)
        self.assertNotIn("<iframe", html)
        # and it is handed the URL, so it need not know parody-web's url names
        self.assertIn('data-pdf="/one/alpha/pdf/"', html)

    def test_the_head_and_toolbar_seams_are_included(self):
        from django.template.loader import get_template
        for name in ("_pdf_view_head", "_pdf_view_toolbar", "_pdf_view_stage"):
            get_template(f"parody_web/{name}.html")   # raises if missing

    def test_the_viewer_offers_a_way_back_to_the_section(self):
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            html = self.client.get("/one/alpha/pdf/view/").content.decode()
        self.assertIn('href="/one/alpha/"', html)

    def test_a_refused_section_has_no_viewer(self):
        Section.objects.filter(book=self.book, slug="alpha").update(preview=True)
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            resp = self.client.get("/one/alpha/pdf/view/")
        self.assertEqual(resp.status_code, 404)

    def test_a_section_with_no_pdf_has_no_viewer(self):
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            self.assertEqual(
                self.client.get("/one/beta/pdf/view/").status_code, 404)


class SectionRailTests(TestCase):
    def setUp(self):
        from django.test import Client
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        make_pdf(self.root / "print-book.pdf", 20)
        self.book = import_artifact()
        self.client = Client()

    def test_the_rail_offers_the_section_pdf(self):
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            html = self.client.get("/one/alpha/").content.decode()
        self.assertIn('class="util-rail"', html)
        self.assertIn('data-util="pdf"', html)
        self.assertIn("/one/alpha/pdf/", html)
        self.assertIn("/one/alpha/pdf/view/", html)

    def test_the_rail_states_the_page_count(self):
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            html = self.client.get("/one/alpha/").content.decode()
        self.assertIn("5 pages", html)

    def test_the_rail_is_absent_when_the_section_has_no_pdf(self):
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            html = self.client.get("/one/beta/").content.decode()
        self.assertNotIn('class="util-rail"', html)

    def test_the_rail_is_absent_without_a_print_root(self):
        with override_settings(PARODY_WEB_PRINT_ROOT=""):
            html = self.client.get("/one/alpha/").content.decode()
        self.assertNotIn('class="util-rail"', html)

    def test_a_preview_section_offers_the_public_no_pdf(self):
        Section.objects.filter(book=self.book, slug="alpha").update(preview=True)
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            html = self.client.get("/one/alpha/").content.decode()
        self.assertNotIn("/one/alpha/pdf/", html)

    def test_the_rail_works_without_javascript(self):
        # the trigger is a real link to the viewer, progressively enhanced
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            html = self.client.get("/one/alpha/").content.decode()
        self.assertIn('<a class="util-rail-trigger"', html)

    def test_the_chapter_page_offers_the_lead_in_pdf(self):
        # The lead-in is the chapter title + intro prose unit. It is rendered
        # on the chapter landing page, not at /one/lead-in/, so this is the
        # only place its PDF can be offered.
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            html = self.client.get("/one/").content.decode()
        self.assertIn('class="util-rail"', html)
        self.assertIn("/one/lead-in/pdf/", html)
        self.assertIn("3 pages", html)  # [3, 5] inclusive

    def test_a_chapter_with_no_lead_in_has_no_rail(self):
        Section.objects.filter(book=self.book, slug="lead-in").delete()
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            html = self.client.get("/one/").content.decode()
        self.assertNotIn('class="util-rail"', html)

    def test_the_home_page_offers_the_full_book(self):
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            html = self.client.get("/").content.decode()
        self.assertIn('href="/pdf/"', html)

    def test_the_home_page_hides_a_withheld_full_book(self):
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root),
                               PARODY_WEB_PUBLIC_BOOK_PDF=False):
            html = self.client.get("/").content.decode()
        self.assertNotIn('href="/pdf/"', html)


class PublicBookPdfWarningTests(TestCase):
    def test_a_gated_book_with_a_public_full_pdf_warns(self):
        book = import_artifact()
        Section.objects.filter(book=book, slug="alpha").update(preview=True)
        with override_settings(PARODY_WEB_PUBLIC_BOOK_PDF=True):
            warnings = printing.public_book_pdf_warnings()
        self.assertEqual(len(warnings), 1)
        self.assertIn("print-book", warnings[0])
        self.assertIn("PARODY_WEB_PUBLIC_BOOK_PDF", warnings[0])

    def test_a_fully_public_book_does_not_warn(self):
        import_artifact()
        with override_settings(PARODY_WEB_PUBLIC_BOOK_PDF=True):
            self.assertEqual(printing.public_book_pdf_warnings(), [])

    def test_no_warning_once_the_setting_is_off(self):
        book = import_artifact()
        Section.objects.filter(book=book, slug="alpha").update(preview=True)
        with override_settings(PARODY_WEB_PUBLIC_BOOK_PDF=False):
            self.assertEqual(printing.public_book_pdf_warnings(), [])

    def test_a_book_with_no_print_pdf_never_warns(self):
        data = json.loads(json.dumps(ARTIFACT))
        del data["print"]
        book = import_artifact(data)
        Section.objects.filter(book=book, slug="alpha").update(preview=True)
        with override_settings(PARODY_WEB_PUBLIC_BOOK_PDF=True):
            self.assertEqual(printing.public_book_pdf_warnings(), [])

    def test_the_system_check_reports_it(self):
        # Registered as a system check, not run from AppConfig.ready(): a query
        # in ready() trips Django's "Accessing the database during app
        # initialization is discouraged" warning on every manage.py call.
        from parody_web.checks import public_book_pdf_check
        book = import_artifact()
        Section.objects.filter(book=book, slug="alpha").update(preview=True)
        with override_settings(PARODY_WEB_PUBLIC_BOOK_PDF=True):
            issues = public_book_pdf_check(None)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].id, "parody_web.W001")
        self.assertIn("PARODY_WEB_PUBLIC_BOOK_PDF", issues[0].msg)

    def test_the_system_check_is_quiet_when_correctly_configured(self):
        from parody_web.checks import public_book_pdf_check
        book = import_artifact()
        Section.objects.filter(book=book, slug="alpha").update(preview=True)
        with override_settings(PARODY_WEB_PUBLIC_BOOK_PDF=False):
            self.assertEqual(public_book_pdf_check(None), [])


class PdfInlineDispositionTests(TestCase):
    """The viewer embeds the section PDF, so that URL must render inline.

    An attachment disposition makes the browser DOWNLOAD the file even inside
    an <iframe>, so 'Read as PDF' just re-downloaded it instead of opening.
    """

    def setUp(self):
        from django.test import Client
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        make_pdf(self.root / "print-book.pdf", 20)
        self.book = import_artifact()
        self.client = Client()

    def test_the_download_link_still_attaches(self):
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            resp = self.client.get("/one/alpha/pdf/")
        self.assertTrue(resp["Content-Disposition"].startswith("attachment"))

    def test_inline_renders_in_place(self):
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            resp = self.client.get("/one/alpha/pdf/?inline=1")
        self.assertTrue(resp["Content-Disposition"].startswith("inline"),
                        resp["Content-Disposition"])
        self.assertEqual(resp["Content-Type"], "application/pdf")

    def test_the_viewer_embeds_the_inline_url(self):
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            html = self.client.get("/one/alpha/pdf/view/").content.decode()
        self.assertIn("/one/alpha/pdf/?inline=1", html)

    def test_inline_is_still_gated(self):
        # the query string must not be a way around the access policy
        Section.objects.filter(book=self.book, slug="alpha").update(preview=True)
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            self.assertEqual(
                self.client.get("/one/alpha/pdf/?inline=1").status_code, 404)


class UtilRailHoverTests(TestCase):
    def test_the_card_bridges_the_gap_to_the_trigger(self):
        css = (Path(__file__).parent / "static" / "parody_web" / "css"
               / "book.css").read_text()
        # the cursor has to cross dead space to reach the card; without a
        # bridge and a close delay the menu vanishes on the way
        self.assertIn(".util-rail-item::after", css)
        self.assertIn(".util-rail-card::before", css)
        self.assertIn("visibility: hidden", css)


class StaticHashingTests(SimpleTestCase):
    """Stylesheet URLs must carry a content hash where the storage provides one.

    Without it a CDN keeps serving the previous deploy's css (measured on a
    Cloudflare-fronted site: cf-cache-status HIT, max-age=14400), so a correct
    deploy shows readers a page missing its newest rules.
    """

    def test_the_tag_defers_to_the_configured_storage(self):
        from unittest.mock import patch

        from parody_web.templatetags.parody_web import static
        with patch("django.contrib.staticfiles.storage.staticfiles_storage.url",
                   return_value="/static/parody_web/css/book.abc123.css") as m:
            self.assertEqual(static("parody_web/css/book.css"),
                             "/static/parody_web/css/book.abc123.css")
        m.assert_called_once_with("parody_web/css/book.css")

    def test_a_file_missing_from_the_manifest_falls_back(self):
        # ManifestStaticFilesStorage raises for unknown files; a missing hash
        # is a cache nuisance, an exception is a 500.
        from unittest.mock import patch

        from parody_web.templatetags.parody_web import static
        with patch("django.contrib.staticfiles.storage.staticfiles_storage.url",
                   side_effect=ValueError("not in manifest")):
            self.assertEqual(static("parody_web/css/book.css"),
                             "/static/parody_web/css/book.css")
