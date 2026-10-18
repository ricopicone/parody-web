"""Translated twin PDFs: import, validity, slicing, gating, and chrome."""
import hashlib
import json
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase, override_settings

from parody_web import printing, twins
from parody_web.models import Book, TwinPdf
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
