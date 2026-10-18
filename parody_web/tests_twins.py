"""Translated twin PDFs: import, validity, slicing, gating, and chrome."""
import hashlib
import json
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase, override_settings

from parody_web import printing, twins
from parody_web.models import Book, Section, TwinPdf
from parody_web.tests_printing import ARTIFACT

ENGLISH_SHA = ARTIFACT["print"]["sha256"]


def import_artifact(data=None, **opts):
    payload = json.loads(json.dumps(data or ARTIFACT))
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(payload, f)
        path = f.name
    err = StringIO()
    call_command("import_artifact", path, stdout=StringIO(), stderr=err, **opts)
    Path(path).unlink()
    return Book.objects.get(slug=payload["slug"]), err.getvalue()


def pdf_bytes(pages, base):
    """A real PDF whose page i (1-based) is base + i points wide, so a slice
    can be read back page by page."""
    from io import BytesIO

    from pypdf import PdfWriter
    writer = PdfWriter()
    for i in range(1, pages + 1):
        writer.add_blank_page(width=base + i, height=200)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def widths(path):
    from pypdf import PdfReader
    return [int(p.mediabox.width) for p in PdfReader(str(path)).pages]


def write_twin(root, language="de", content=b"%PDF twin", sidecar=None, sbs=True,
               sbs_content=b"%PDF sbs"):
    """A twin PDF (and side-by-side sheets) in `root`, with its sidecar."""
    pdf = root / f"print-book-{language}.pdf"
    pdf.write_bytes(content)
    if sbs:
        (root / f"print-book-{language}-sbs.pdf").write_bytes(sbs_content)
    data = {
        "schema": 1, "language": language, "pdf": pdf.name,
        "sha256": hashlib.sha256(content).hexdigest(),
        "english_sha256": ENGLISH_SHA,
        "side_by_side": f"print-book-{language}-sbs.pdf" if sbs else None,
        "sections": {"one/lead-in": [1, 2], "one/alpha": [2, 4]},
        "abspages": [3, 4, 5, 6], "base_scale": 0.87, "squeezed": [],
        "approximate": [2], "untranslated": 0, "stale": 0,
    }
    data.update(sidecar or {})
    path = root / f"print-book-{language}.twin.json"
    path.write_text(json.dumps(data))
    return path


class TwinImportTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.settings = override_settings(PARODY_WEB_PRINT_ROOT=str(self.root))
        self.settings.enable()

    def tearDown(self):
        self.settings.disable()
        self.tmp.cleanup()

    def test_import_twin_records_it(self):
        book, _ = import_artifact(twin=[str(write_twin(self.root))])
        twin = book.twins.get()
        self.assertEqual(twin.language, "de")
        self.assertEqual(twin.pdf, "print-book-de.pdf")
        self.assertEqual(twin.side_by_side_pdf, "print-book-de-sbs.pdf")
        self.assertEqual(twin.english_sha256, ENGLISH_SHA)
        self.assertEqual(twin.sections["one/alpha"], [2, 4])
        self.assertEqual(twin.approximate, [2])

    def test_bad_twin_is_skipped_english_imported(self):
        cases = {
            "missing pdf": lambda: write_twin(self.root, sidecar={"pdf": "nope.pdf"}),
            "sha mismatch": lambda: write_twin(self.root, sidecar={"sha256": "0" * 64}),
            "bad language": lambda: write_twin(self.root, sidecar={"language": "xx"}),
            "older english": lambda: write_twin(self.root, sidecar={"english_sha256": "d" * 64}),
            "wrong schema": lambda: write_twin(self.root, sidecar={"schema": 2}),
            "path in name": lambda: write_twin(self.root, sidecar={"pdf": "../print-book-de.pdf"}),
        }
        for name, make in cases.items():
            with self.subTest(name):
                book, err = import_artifact(twin=[str(make())])
                self.assertEqual(book.sections.count(), 3)
                self.assertFalse(book.twins.exists())
                self.assertIn("twin skipped", err)

    def test_an_artifact_without_a_print_pdf_says_so(self):
        data = json.loads(json.dumps(ARTIFACT))
        del data["print"]
        book, err = import_artifact(data, twin=[str(write_twin(self.root))])
        self.assertFalse(book.twins.exists())
        self.assertIn("the artifact has no print PDF", err)

    def test_unreadable_sidecar_is_skipped(self):
        book, err = import_artifact(twin=[str(self.root / "absent.twin.json")])
        self.assertFalse(book.twins.exists())
        self.assertIn("twin skipped", err)

    def test_missing_side_by_side_keeps_the_twin(self):
        book, err = import_artifact(twin=[str(write_twin(self.root, sbs=False))])
        self.assertEqual(book.twins.get().side_by_side_pdf, "")
        path = write_twin(self.root)
        (self.root / "print-book-de-sbs.pdf").unlink()
        book, err = import_artifact(twin=[str(path)])
        self.assertEqual(book.twins.get().side_by_side_pdf, "")
        self.assertIn("side-by-side", err)

    def test_reimport_without_twin_removes_it(self):
        import_artifact(twin=[str(write_twin(self.root)),
                              str(write_twin(self.root, "zh", b"%PDF zh"))])
        self.assertEqual(TwinPdf.objects.count(), 2)
        book, _ = import_artifact(twin=[str(write_twin(self.root, "zh", b"%PDF zh"))])
        self.assertEqual([t.language for t in book.twins.all()], ["zh"])
        book, _ = import_artifact()
        self.assertFalse(book.twins.exists())

    def test_validation_hashes_bytes_without_parsing_the_pdf(self):
        # not a PDF at all: validation is the sha of the bytes, nothing more
        data, warnings = twins.load_sidecar(write_twin(self.root, content=b"not a pdf"))
        self.assertEqual(data["language"], "de")

    def test_without_a_print_root_twins_are_skipped(self):
        path = write_twin(self.root)
        with override_settings(PARODY_WEB_PRINT_ROOT=""):
            book, err = import_artifact(twin=[str(path)])
        self.assertFalse(book.twins.exists())
        self.assertIn("twin skipped", err)


class TwinSliceTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.settings = override_settings(PARODY_WEB_PRINT_ROOT=str(self.root))
        self.settings.enable()
        self.book, _ = import_artifact(twin=[str(write_twin(
            self.root, content=pdf_bytes(4, 100), sbs_content=pdf_bytes(4, 300)))])
        self.twin = self.book.twins.get()

    def tearDown(self):
        self.settings.disable()
        self.tmp.cleanup()

    def test_twin_for_requires_matching_english_sha(self):
        self.assertEqual(printing.twin_for(self.book, "de"), self.twin)
        Book.objects.filter(pk=self.book.pk).update(print_sha256="d" * 64)
        self.book.refresh_from_db()
        self.assertIsNone(printing.twin_for(self.book, "de"))
        self.assertEqual(printing.translations_available(self.book), [])

    def test_twin_for_needs_the_file_and_the_language(self):
        self.assertIsNone(printing.twin_for(self.book, "zh"))
        self.assertIsNone(printing.twin_for(self.book, "xx"))
        (self.root / "print-book-de.pdf").unlink()
        self.assertIsNone(printing.twin_for(self.book, "de"))

    def test_twin_section_slice_uses_sidecar_range(self):
        alpha = self.book.sections.get(slug="alpha")  # [2, 4] in the twin
        out = printing.twin_section_pdf_path(self.book, alpha, self.twin)
        self.assertEqual(widths(out), [102, 103, 104])
        self.assertIn(f"twin-de-{self.twin.sha256[:12]}", str(out))

    def test_section_outside_twin_has_no_slice(self):
        beta = self.book.sections.get(slug="beta")
        self.assertIsNone(printing.twin_section_pdf_path(self.book, beta, self.twin))

    def test_side_by_side_slice(self):
        alpha = self.book.sections.get(slug="alpha")
        out = printing.twin_section_pdf_path(self.book, alpha, self.twin, side_by_side=True)
        self.assertEqual(widths(out), [302, 303, 304])
        whole = printing.twin_pdf_path(self.twin, side_by_side=True)
        self.assertEqual(whole, self.root / "print-book-de-sbs.pdf")

    def test_without_side_by_side_there_is_none(self):
        TwinPdf.objects.filter(pk=self.twin.pk).update(side_by_side_pdf="")
        self.twin.refresh_from_db()
        alpha = self.book.sections.get(slug="alpha")
        self.assertIsNone(printing.twin_pdf_path(self.twin, side_by_side=True))
        self.assertIsNone(printing.twin_section_pdf_path(self.book, alpha, self.twin,
                                                         side_by_side=True))

    def test_translations_available_lists_the_valid_twins(self):
        self.assertEqual(printing.translations_available(self.book), [self.twin])

    def test_translations_available_is_one_query(self):
        import_artifact(twin=[str(self.root / "print-book-de.twin.json"),
                              str(write_twin(self.root, "zh", pdf_bytes(4, 200)))])
        with self.assertNumQueries(1):
            self.assertEqual([t.language for t in printing.translations_available(self.book)],
                             ["de", "zh"])

    def test_a_range_past_the_twins_end_has_no_slice(self):
        TwinPdf.objects.filter(pk=self.twin.pk).update(sections={"one/alpha": [5, 6]})
        self.twin.refresh_from_db()
        alpha = self.book.sections.get(slug="alpha")  # the twin has 4 pages
        self.assertIsNone(printing.twin_section_pdf_path(self.book, alpha, self.twin))


class TwinViewTests(TestCase):
    """The reader's side: URLs, gating, and the links in the chrome."""

    def setUp(self):
        from django.test import Client

        from parody_web.tests_printing import make_pdf
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.settings = override_settings(PARODY_WEB_PRINT_ROOT=str(self.root))
        self.settings.enable()
        make_pdf(self.root / "print-book.pdf", 20)
        self.book, _ = import_artifact(twin=[str(write_twin(
            self.root, content=pdf_bytes(4, 100), sbs_content=pdf_bytes(4, 300)))])
        self.client = Client()

    def tearDown(self):
        self.settings.disable()
        self.tmp.cleanup()

    def _body(self, resp):
        return b"".join(resp.streaming_content) if resp.streaming else resp.content

    def _widths(self, resp):
        from io import BytesIO

        from pypdf import PdfReader
        return [int(p.mediabox.width) for p in PdfReader(BytesIO(self._body(resp))).pages]

    def _login(self):
        from django.contrib.auth import get_user_model
        get_user_model().objects.create_user("owner", password="pw")
        self.client.login(username="owner", password="pw")

    def test_section_twin_served_inline_and_download(self):
        resp = self.client.get("/one/alpha/pdf/de/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._widths(resp), [102, 103, 104])
        self.assertIn("attachment", resp["Content-Disposition"])
        self.assertIn("alpha-de.pdf", resp["Content-Disposition"])
        resp = self.client.get("/one/alpha/pdf/de/side-by-side/?inline=1")
        self.assertEqual(self._widths(resp), [302, 303, 304])
        self.assertIn("inline", resp["Content-Disposition"])
        self.assertIn("alpha-de-side-by-side.pdf", resp["Content-Disposition"])

    def test_book_twin_and_side_by_side(self):
        resp = self.client.get("/pdf/de/")
        self.assertEqual(self._widths(resp), [101, 102, 103, 104])
        self.assertIn("print-book-de.pdf", resp["Content-Disposition"])
        resp = self.client.get("/pdf/de/side-by-side/")
        self.assertEqual(self._widths(resp), [301, 302, 303, 304])

    def test_draft_or_policy_refusal_404s(self):
        Section.objects.filter(book=self.book, slug="alpha").update(preview=True)
        self.assertEqual(self.client.get("/one/alpha/pdf/de/").status_code, 404)
        self.assertEqual(self.client.get("/one/alpha/pdf/de/side-by-side/").status_code, 404)
        Section.objects.filter(book=self.book, slug="alpha").update(preview=False, draft=True)
        self.assertEqual(self.client.get("/one/alpha/pdf/de/").status_code, 404)
        with override_settings(PARODY_WEB_PUBLIC_BOOK_PDF=False):
            self.assertEqual(self.client.get("/pdf/de/").status_code, 404)
            self.assertEqual(self.client.get("/pdf/de/side-by-side/").status_code, 404)
            self._login()
            self.assertEqual(self.client.get("/pdf/de/").status_code, 200)

    def test_stale_twin_404s_and_no_link(self):
        Book.objects.filter(pk=self.book.pk).update(print_sha256="d" * 64)
        for url in ("/one/alpha/pdf/de/", "/one/alpha/pdf/de/side-by-side/",
                    "/pdf/de/", "/pdf/de/side-by-side/"):
            self.assertEqual(self.client.get(url).status_code, 404, url)
        self.assertNotIn("/pdf/de/", self.client.get("/one/alpha/").content.decode())
        self.assertNotIn("/pdf/de/", self.client.get("/").content.decode())

    def test_section_the_twin_does_not_cover_404s(self):
        self.assertEqual(self.client.get("/one/beta/pdf/de/").status_code, 404)

    def test_bad_language_404s(self):
        for lang in ("xx", "DE", "..", "%2e%2e", "view%2F.."):
            for url in (f"/one/alpha/pdf/{lang}/", f"/pdf/{lang}/", f"/pdf/{lang}/side-by-side/"):
                self.assertEqual(self.client.get(url).status_code, 404, url)

    def test_a_known_language_with_no_twin_404s(self):
        for url in ("/one/alpha/pdf/zh/", "/pdf/zh/", "/pdf/zh/side-by-side/"):
            self.assertEqual(self.client.get(url).status_code, 404, url)

    def test_links_say_which_is_the_pdf(self):
        # the language's name alone, as a link, did not say it downloads a PDF
        html = self.client.get("/one/alpha/").content.decode()
        self.assertIn('<span lang="de">Deutsch</span>: '
                      '<a href="/one/alpha/pdf/de/" hreflang="de">PDF</a>', html)

    def test_rail_lists_translations_only_when_available(self):
        html = self.client.get("/one/alpha/").content.decode()
        self.assertIn('href="/one/alpha/pdf/de/"', html)
        self.assertIn('href="/one/alpha/pdf/de/side-by-side/"', html)
        self.assertIn("Deutsch", html)
        self.assertIn('lang="de"', html)
        TwinPdf.objects.all().delete()
        html = self.client.get("/one/alpha/").content.decode()
        self.assertNotIn("/pdf/de/", html)
        self.assertNotIn("Deutsch", html)

    def test_rail_hides_translations_from_a_reader_refused_the_section(self):
        self._login()  # the owner sees a preview section, and its translations
        Section.objects.filter(book=self.book, slug="alpha").update(preview=True)
        self.assertIn("/one/alpha/pdf/de/", self.client.get("/one/alpha/").content.decode())
        self.client.logout()
        self.assertNotIn("/one/alpha/pdf/de/", self.client.get("/one/alpha/").content.decode())

    def test_home_lists_the_book_translations(self):
        html = self.client.get("/").content.decode()
        self.assertIn('href="/pdf/de/"', html)
        self.assertIn('href="/pdf/de/side-by-side/"', html)

    def test_pdf_view_bar_lists_translations(self):
        html = self.client.get("/one/alpha/pdf/view/").content.decode()
        self.assertIn('href="/one/alpha/pdf/de/"', html)
        self.assertIn('href="/one/alpha/pdf/de/side-by-side/"', html)
        TwinPdf.objects.all().delete()
        html = self.client.get("/one/alpha/pdf/view/").content.decode()
        self.assertNotIn("/pdf/de/", html)

    def test_side_by_side_link_absent_without_the_file(self):
        TwinPdf.objects.update(side_by_side_pdf="")
        html = self.client.get("/one/alpha/").content.decode()
        self.assertIn('href="/one/alpha/pdf/de/"', html)
        self.assertNotIn("side-by-side", html)
        self.assertEqual(self.client.get("/one/alpha/pdf/de/side-by-side/").status_code, 404)


class TwinPairedTests(TestCase):
    """The twin page beside each English page of a section, one for one: what
    the reader puts next to the English it shows (task #825)."""

    def setUp(self):
        from parody_web.tests_printing import make_pdf
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.settings = override_settings(PARODY_WEB_PRINT_ROOT=str(self.root))
        self.settings.enable()
        make_pdf(self.root / "print-book.pdf", 20)            # 200 x 200 pages
        # twin pages 1..6 are English pages 3..8; alpha is English [5, 9], so
        # its English page 9 has no twin, and the twin's own alpha range is
        # one page shorter than the English one
        self.book, _ = import_artifact(twin=[str(write_twin(
            self.root, content=pdf_bytes(6, 100),
            sidecar={"abspages": [3, 4, 5, 6, 7, 8],
                     "sections": {"one/lead-in": [1, 3], "one/alpha": [3, 5]}}))])
        self.twin = self.book.twins.get()
        self.alpha = self.book.sections.get(slug="alpha")

    def tearDown(self):
        self.settings.disable()
        self.tmp.cleanup()

    def test_import_keeps_the_english_page_of_each_twin_page(self):
        self.assertEqual(self.twin.abspages, [3, 4, 5, 6, 7, 8])

    def test_one_page_per_english_page_blank_where_untranslated(self):
        out = printing.twin_paired_pdf_path(self.book, self.alpha, self.twin)
        # English 5, 6, 7, 8 are twin pages 3..6; English 9 is a blank page
        # the size of the English one
        self.assertEqual(widths(out), [103, 104, 105, 106, 200])

    def test_pairs_by_the_english_page_not_the_twins_own_range(self):
        # the twin ends alpha a page early (it kept a split sentence whole):
        # its own range would put twin page 3 beside English 5 and stop there
        lead_in = self.book.sections.get(slug="lead-in")       # English [3, 5]
        out = printing.twin_paired_pdf_path(self.book, lead_in, self.twin)
        self.assertEqual(widths(out), [101, 102, 103])

    def test_without_abspages_pairs_from_the_twins_first_page(self):
        # twins imported before abspages was kept: the twin's own range says
        # where the section starts, and the pages run on from there
        TwinPdf.objects.filter(pk=self.twin.pk).update(abspages=[])
        self.twin.refresh_from_db()
        out = printing.twin_paired_pdf_path(self.book, self.alpha, self.twin)
        self.assertEqual(widths(out), [103, 104, 105, 106, 200])

    def test_a_section_the_twin_does_not_cover_has_none(self):
        beta = self.book.sections.get(slug="beta")
        self.assertIsNone(printing.twin_paired_pdf_path(self.book, beta, self.twin))
        TwinPdf.objects.filter(pk=self.twin.pk).update(abspages=[15, 16])
        self.twin.refresh_from_db()
        self.assertIsNone(printing.twin_paired_pdf_path(self.book, self.alpha, self.twin))

    def test_served_inline_gated_like_the_english(self):
        from django.test import Client
        client = Client()
        resp = client.get("/one/alpha/pdf/de/paired/?inline=1")
        self.assertEqual(resp.status_code, 200)
        body = b"".join(resp.streaming_content)
        from io import BytesIO

        from pypdf import PdfReader
        self.assertEqual([int(p.mediabox.width) for p in PdfReader(BytesIO(body)).pages],
                         [103, 104, 105, 106, 200])
        self.assertIn("inline", resp["Content-Disposition"])
        Section.objects.filter(book=self.book, slug="alpha").update(preview=True)
        self.assertEqual(client.get("/one/alpha/pdf/de/paired/").status_code, 404)
        self.assertEqual(client.get("/one/beta/pdf/de/paired/").status_code, 404)
        self.assertEqual(client.get("/one/alpha/pdf/xx/paired/").status_code, 404)
