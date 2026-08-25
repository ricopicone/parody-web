"""The ink layer: identity, isolation, and surviving a re-import."""
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase

from parody_web_annotate.models import InkLayer


class InkLayerModelTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.reader = User.objects.create_user("reader", password="x")
        self.other = User.objects.create_user("other", password="x")
        self.kw = dict(book_slug="print-book", edition_id="", section_key="al",
                       slice_key="a" * 64, book_sha256="b" * 64, pages=[5, 9],
                       strokes={})

    def test_one_layer_per_reader_section_and_version(self):
        InkLayer.objects.create(user=self.reader, **self.kw)
        with self.assertRaises(IntegrityError):
            InkLayer.objects.create(user=self.reader, **self.kw)

    def test_two_versions_of_one_section_coexist(self):
        InkLayer.objects.create(user=self.reader, **self.kw)
        InkLayer.objects.create(user=self.reader, **{**self.kw, "slice_key": "c" * 64})
        self.assertEqual(InkLayer.objects.filter(user=self.reader).count(), 2)

    def test_two_readers_annotate_the_same_version_independently(self):
        InkLayer.objects.create(user=self.reader, **self.kw)
        InkLayer.objects.create(user=self.other, **self.kw)
        self.assertEqual(InkLayer.objects.count(), 2)

    def test_it_carries_everything_needed_to_cut_its_own_pdf(self):
        """Section.print_pages is overwritten every import; this row must not
        depend on it."""
        layer = InkLayer.objects.create(user=self.reader, **self.kw)
        self.assertEqual(layer.book_sha256, "b" * 64)
        self.assertEqual(layer.pages, [5, 9])

    def test_stroke_count_sums_the_pages(self):
        layer = InkLayer.objects.create(
            user=self.reader, **{**self.kw,
                                 "strokes": {"1": [{}, {}], "2": [{}]}})
        self.assertEqual(layer.stroke_count, 3)


class DenyAll:
    """An access policy that refuses every PDF."""

    def __getattr__(self, name):
        def hook(*args, **kwargs):
            return False
        return hook


class InkEndpointTests(TestCase):
    """Reading and writing ink, gated exactly as the PDF is."""

    def setUp(self):
        import tempfile
        from pathlib import Path
        from django.test import Client
        from parody_web.tests_printing import import_artifact, make_pdf_with_content

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        make_pdf_with_content(self.root / "print-book.pdf", 20)
        self.book = import_artifact()

        User = get_user_model()
        self.reader = User.objects.create_user("reader", password="x")
        self.other = User.objects.create_user("other", password="x")
        self.client = Client()
        self.url = "/one/alpha/ink/"
        self.body = {"strokes": {"1": [{"tool": "pen", "color": "#000",
                                        "size": 2, "opacity": 1,
                                        "points": [[1, 2, 0.5]], "d": "M1 2"}]}}

    def _settings(self, **extra):
        from django.test import override_settings
        return override_settings(PARODY_WEB_PRINT_ROOT=str(self.root), **extra)

    def _put(self, body=None):
        return self.client.put(self.url, body or self.body,
                               content_type="application/json")

    def _big_body(self, strokes=400):
        """A section carrying more ink than a form post is allowed to be.

        Real handwriting reaches this: one pen stroke of 150 samples
        serialises to ~11 KB of outline path, so a densely marked section
        passes Django's 2.5 MB DATA_UPLOAD_MAX_MEMORY_SIZE default in a few
        hundred strokes.
        """
        stroke = {"tool": "pen", "color": "#000", "size": 2, "opacity": 1,
                  "d": "M 1 2 " + "Q 3.14 4.15 5.16 6.17 " * 300 + "Z"}
        return {"strokes": {"1": [dict(stroke) for _ in range(strokes)]}}

    def test_a_heavily_annotated_section_still_saves(self):
        """The whole section is re-sent on every save, so the body grows with
        the reader's notes. Exceeding the form-post default must not cost them
        the work."""
        self.client.force_login(self.reader)
        body = self._big_body()
        with self._settings(DATA_UPLOAD_MAX_MEMORY_SIZE=2621440):
            self.assertEqual(self._put(body).status_code, 200)
        layer = InkLayer.objects.get(user=self.reader)
        self.assertEqual(len(layer.strokes["1"]), 400)

    def test_a_body_past_the_ink_ceiling_is_refused_in_json(self):
        """Beyond our own ceiling the answer is a plain 413 the reader's
        browser can act on — not a SuspiciousOperation that pages the admins
        and tells the reader nothing."""
        self.client.force_login(self.reader)
        with self._settings(PARODY_WEB_INK_MAX_BODY_BYTES=4096):
            resp = self._put(self._big_body())
        self.assertEqual(resp.status_code, 413)
        self.assertIn("error", resp.json())
        self.assertFalse(InkLayer.objects.filter(user=self.reader).exists())

    # ---- compressed uploads ------------------------------------------

    def _gzip(self, obj):
        import gzip, json as _json
        return gzip.compress(_json.dumps(obj).encode())

    def _put_gz(self, raw, encoding="gzip"):
        return self.client.generic(
            "PUT", self.url, raw, content_type="application/json",
            HTTP_CONTENT_ENCODING=encoding)

    def test_a_gzipped_body_is_understood(self):
        """A save carries the whole section, so it is worth compressing: a
        dense one measured 2.89x smaller gzipped."""
        self.client.force_login(self.reader)
        with self._settings():
            resp = self._put_gz(self._gzip(self.body))
        self.assertEqual(resp.status_code, 200)
        layer = InkLayer.objects.get(user=self.reader)
        self.assertEqual(layer.strokes["1"][0]["tool"], "pen")

    def test_an_uncompressed_body_still_works(self):
        """The client compresses only above a size threshold, and falls back to
        plain bytes if compression ever fails — both must land."""
        self.client.force_login(self.reader)
        with self._settings():
            self.assertEqual(self._put().status_code, 200)

    def test_a_body_that_lies_about_being_gzipped_is_a_400(self):
        """A mangling proxy must produce a clear answer, not a 500 and an
        admin email."""
        self.client.force_login(self.reader)
        with self._settings():
            resp = self._put_gz(b"this is not gzip at all")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("error", resp.json())

    def test_a_truncated_gzip_body_is_a_400(self):
        self.client.force_login(self.reader)
        raw = self._gzip(self.body)
        with self._settings():
            resp = self._put_gz(raw[:len(raw) // 2])
        self.assertEqual(resp.status_code, 400)

    def test_the_ceiling_applies_to_what_it_decompresses_to(self):
        """THE point of care here. 25 MB of gzip inflates to far more, so a
        ceiling measured on the compressed bytes would be no ceiling at all."""
        self.client.force_login(self.reader)
        # ~4 MB of compressible payload; a 4 KB ceiling must refuse it even
        # though the compressed body sails under the limit.
        bomb = {"strokes": {"1": [{"tool": "pen", "d": "M 1 2 " + "L 3 4 " * 20000}]}}
        raw = self._gzip(bomb)
        self.assertLess(len(raw), 4096)
        with self._settings(PARODY_WEB_INK_MAX_BODY_BYTES=4096):
            resp = self._put_gz(raw)
        self.assertEqual(resp.status_code, 413)
        self.assertFalse(InkLayer.objects.filter(user=self.reader).exists())

    def test_it_does_not_inflate_the_bomb_before_measuring_it(self):
        """Refusing after building a 400 MB string in memory would be its own
        outage. Decompression must stop at the ceiling, not past it."""
        from parody_web_annotate import views
        raw = self._gzip({"strokes": {"1": [{"d": "L 3 4 " * 200000}]}})
        produced = views._gunzip_capped(raw, 4096)
        self.assertIsNone(produced)

    def test_an_unknown_content_encoding_is_refused_clearly(self):
        self.client.force_login(self.reader)
        with self._settings():
            resp = self._put_gz(self._gzip(self.body), encoding="br")
        self.assertEqual(resp.status_code, 415)
        self.assertIn("error", resp.json())

    def test_put_then_get_round_trips(self):
        self.client.force_login(self.reader)
        with self._settings():
            self.assertEqual(self._put().status_code, 200)
            got = self.client.get(self.url).json()
        self.assertEqual(got["strokes"]["1"][0]["tool"], "pen")

    def test_a_write_records_the_version_it_belongs_to(self):
        """Recorded on write, while Section.print_pages is still true."""
        self.client.force_login(self.reader)
        with self._settings():
            self._put()
        layer = InkLayer.objects.get(user=self.reader)
        self.assertEqual(layer.pages, [5, 9])
        self.assertEqual(layer.book_sha256, "c" * 64)
        self.assertEqual(len(layer.slice_key), 64)

    def test_a_reader_never_sees_another_readers_ink(self):
        with self._settings():
            self.client.force_login(self.other)
            self._put()
            self.client.force_login(self.reader)
            got = self.client.get(self.url).json()
        self.assertEqual(got["strokes"], {})

    def test_a_reader_cannot_overwrite_another_readers_ink(self):
        with self._settings():
            self.client.force_login(self.other)
            self._put()
            self.client.force_login(self.reader)
            self._put({"strokes": {}})
        theirs = InkLayer.objects.get(user=self.other)
        self.assertEqual(len(theirs.strokes["1"]), 1)
        self.assertEqual(InkLayer.objects.count(), 2)

    def test_anonymous_cannot_write(self):
        with self._settings():
            self.assertEqual(self._put().status_code, 403)
        self.assertEqual(InkLayer.objects.count(), 0)

    def test_a_refused_section_yields_no_ink(self):
        self.client.force_login(self.reader)
        with self._settings(
                PARODY_WEB_ACCESS_POLICY="parody_web_annotate.tests.DenyAll"):
            self.assertEqual(self.client.get(self.url).status_code, 404)
            self.assertEqual(self._put().status_code, 404)

    def test_the_response_lists_the_versions_worth_showing(self):
        self.client.force_login(self.reader)
        with self._settings():
            self._put()
            versions = self.client.get(self.url).json()["versions"]
        self.assertEqual(len(versions), 1)
        self.assertTrue(versions[0]["current"])


class VersionedPdfAndCarryForwardTests(TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        from django.test import Client
        from parody_web import printing
        from parody_web.tests_printing import import_artifact, make_pdf_with_content

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.root, self.archive, self.cache = base / "live", base / "arc", base / "c"
        self.root.mkdir()
        make_pdf_with_content(self.root / "print-book.pdf", 20)
        self.book = import_artifact()
        self.printing = printing

        User = get_user_model()
        self.reader = User.objects.create_user("reader", password="x")
        self.client = Client()
        self.client.force_login(self.reader)

    def _settings(self):
        from django.test import override_settings
        return override_settings(PARODY_WEB_PRINT_ROOT=str(self.root),
                                 PARODY_WEB_PRINT_ARCHIVE=str(self.archive),
                                 PARODY_WEB_PRINT_CACHE=str(self.cache))

    def _annotate_then_release_a_new_book(self):
        """Annotate the current version, then push a new book PDF over it."""
        from parody_web.tests_printing import make_pdf_with_content
        self.printing.archive_book_pdf(self.book)
        old_key = self.printing.slice_key_for(self.book, self.book.sections.get(slug="alpha"))
        self.client.put("/one/alpha/ink/",
                        {"strokes": {"1": [{"tool": "pen", "d": "M1 2"}]}},
                        content_type="application/json")
        # seed=1 so alpha's own pages really changed — without it the key is
        # (correctly) unchanged and there is nothing to carry forward.
        make_pdf_with_content(self.root / "print-book.pdf", 24, seed=1)
        self.printing._reader.cache_clear()
        self.book.print_sha256 = "e" * 64
        self.book.save()
        self.printing.archive_book_pdf(self.book)
        return old_key

    def test_the_current_version_needs_no_v(self):
        with self._settings():
            self.assertEqual(self.client.get("/one/alpha/pdf/at/").status_code, 200)

    def test_an_old_version_still_resolves_after_a_new_release(self):
        with self._settings():
            old_key = self._annotate_then_release_a_new_book()
            resp = self.client.get("/one/alpha/pdf/at/", {"v": old_key})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")

    def test_a_version_the_reader_has_no_ink_for_is_absent(self):
        with self._settings():
            self.assertEqual(
                self.client.get("/one/alpha/pdf/at/", {"v": "f" * 64}).status_code, 404)

    def test_carry_forward_copies_and_keeps_the_old_layer(self):
        with self._settings():
            old_key = self._annotate_then_release_a_new_book()
            new_key = self.printing.slice_key_for(
                self.book, self.book.sections.get(slug="alpha"))
            resp = self.client.post("/one/alpha/ink/carry-forward/",
                                    {"from": old_key, "to": new_key},
                                    content_type="application/json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(InkLayer.objects.count(), 2)
        self.assertEqual(InkLayer.objects.get(slice_key=old_key).strokes,
                         InkLayer.objects.get(slice_key=new_key).strokes)

    def test_carry_forward_refuses_rather_than_clobbering(self):
        with self._settings():
            old_key = self._annotate_then_release_a_new_book()
            new_key = self.printing.slice_key_for(
                self.book, self.book.sections.get(slug="alpha"))
            InkLayer.objects.create(
                user=self.reader, book_slug=self.book.slug, edition_id="",
                section_key="al", slice_key=new_key, book_sha256="e" * 64,
                pages=[5, 9], strokes={"1": [{"tool": "pen", "d": "M9 9"}]})
            resp = self.client.post("/one/alpha/ink/carry-forward/",
                                    {"from": old_key, "to": new_key},
                                    content_type="application/json")
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(
            InkLayer.objects.get(slice_key=new_key).strokes["1"][0]["d"], "M9 9")

    def test_a_rebuild_that_misses_this_section_keeps_the_notes_attached(self):
        """The promise of the whole feature.

        Found by accident: an early fixture rebuilt the book with identical
        page content and carry-forward refused, because there was nothing to
        carry — the notes were already on the current version.
        """
        from parody_web.tests_printing import make_pdf_with_content
        with self._settings():
            self.printing.archive_book_pdf(self.book)
            self.client.put("/one/alpha/ink/",
                            {"strokes": {"1": [{"tool": "pen", "d": "M1 2"}]}},
                            content_type="application/json")
            before = self.client.get("/one/alpha/ink/").json()

            # a new release: more pages, but alpha's own pages are untouched
            make_pdf_with_content(self.root / "print-book.pdf", 24)
            self.printing._reader.cache_clear()
            after = self.client.get("/one/alpha/ink/").json()

        self.assertEqual(after["slice_key"], before["slice_key"])
        self.assertEqual(after["strokes"], before["strokes"])
        self.assertEqual(len(after["versions"]), 1,
                         "an untouched section must not sprout a second version")


class AnnotatedDownloadTests(TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        from django.test import Client
        from parody_web.tests_printing import import_artifact, make_pdf_with_content

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.root, self.cache = base / "live", base / "cache"
        self.root.mkdir()
        make_pdf_with_content(self.root / "print-book.pdf", 20)
        self.book = import_artifact()
        self.reader = get_user_model().objects.create_user("reader", password="x")
        self.client = Client()
        self.client.force_login(self.reader)

    def _settings(self):
        from django.test import override_settings
        return override_settings(PARODY_WEB_PRINT_ROOT=str(self.root),
                                 PARODY_WEB_PRINT_CACHE=str(self.cache))

    def _ink(self):
        self.client.put("/one/alpha/ink/",
                        {"strokes": {"1": [{"tool": "pen", "color": "#ff0000",
                                            "opacity": 1, "d": "M10 10 L50 50 Z"}]}},
                        content_type="application/json")

    def test_it_returns_a_pdf_with_the_ink_in_it(self):
        from pypdf import PdfReader
        import io
        with self._settings():
            self._ink()
            resp = self.client.get("/one/alpha/pdf/annotated/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        pdf = PdfReader(io.BytesIO(b"".join(resp.streaming_content)
                                   if resp.streaming else resp.content))
        self.assertEqual(len(pdf.pages), 5)          # alpha is pages 5..9
        self.assertIn(b"1 0 0 rg", pdf.pages[0].get_contents().get_data())

    def test_it_is_named_so_the_reader_can_tell_it_apart(self):
        with self._settings():
            self._ink()
            resp = self.client.get("/one/alpha/pdf/annotated/")
        self.assertIn("-annotated.pdf", resp["Content-Disposition"])

    def test_a_section_with_no_ink_has_nothing_to_download(self):
        with self._settings():
            self.assertEqual(
                self.client.get("/one/alpha/pdf/annotated/").status_code, 404)

    def test_editing_the_ink_produces_a_fresh_file(self):
        with self._settings():
            self._ink()
            self.client.get("/one/alpha/pdf/annotated/")
            self.client.put("/one/alpha/ink/",
                            {"strokes": {"1": [{"tool": "pen", "color": "#00ff00",
                                                "opacity": 1, "d": "M1 1 L9 9 Z"}]}},
                            content_type="application/json")
            resp = self.client.get("/one/alpha/pdf/annotated/")
        from pypdf import PdfReader
        import io
        pdf = PdfReader(io.BytesIO(b"".join(resp.streaming_content)
                                   if resp.streaming else resp.content))
        self.assertIn(b"0 1 0 rg", pdf.pages[0].get_contents().get_data())

    def test_anonymous_gets_nothing(self):
        with self._settings():
            self._ink()
            self.client.logout()
            self.assertEqual(
                self.client.get("/one/alpha/pdf/annotated/").status_code, 403)


class ViewerTemplateTests(TestCase):
    """The stage swap, and who is offered it."""

    def setUp(self):
        import tempfile
        from pathlib import Path
        from django.test import Client
        from parody_web.tests_printing import import_artifact, make_pdf_with_content

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        make_pdf_with_content(self.root / "print-book.pdf", 20)
        self.book = import_artifact()
        self.reader = get_user_model().objects.create_user("reader", password="x")
        self.client = Client()

    def _settings(self):
        from django.test import override_settings
        return override_settings(PARODY_WEB_PRINT_ROOT=str(self.root))

    def _html(self):
        return self.client.get("/one/alpha/pdf/view/").content.decode()

    def test_a_signed_in_reader_gets_the_drawing_stage(self):
        self.client.force_login(self.reader)
        with self._settings():
            html = self._html()
        self.assertIn("data-ink-root", html)
        self.assertIn("annotate.js", html)
        self.assertNotIn("<iframe", html)

    def test_an_anonymous_reader_gets_the_plain_iframe(self):
        """Not a disabled toolbar — nothing is offered to someone who cannot
        use it."""
        with self._settings():
            html = self._html()
        self.assertIn("<iframe", html)
        self.assertNotIn("data-ink-root", html)
        self.assertNotIn("annotate.js", html)

    def test_the_stage_is_handed_the_version_it_must_load(self):
        self.client.force_login(self.reader)
        with self._settings():
            html = self._html()
        self.assertIn('data-slice-key="', html)
        self.assertIn('data-pages="[5, 9]"', html)

    def test_the_toolbar_appears_for_a_reader_who_may_draw(self):
        self.client.force_login(self.reader)
        with self._settings():
            html = self._html()
        self.assertIn("data-ink-toolbar", html)

    def test_no_version_switcher_when_there_is_only_one_version(self):
        self.client.force_login(self.reader)
        with self._settings():
            html = self._html()
        self.assertNotIn("data-ink-versions", html)

    def test_a_section_with_no_pdf_offers_no_stage(self):
        with self._settings():
            self.client.force_login(self.reader)
            self.assertEqual(
                self.client.get("/one/beta/pdf/view/").status_code, 404)

    def test_the_context_is_computed_once_per_request(self):
        """Three partials ask for it; it reads the PDF to make a version key."""
        self.client.force_login(self.reader)
        with self._settings():
            from unittest.mock import patch
            with patch("parody_web.printing.slice_key_for",
                       wraps=__import__("parody_web.printing",
                                        fromlist=["x"]).slice_key_for) as spy:
                self._html()
        self.assertEqual(spy.call_count, 1)


class AppOrderCheckTests(TestCase):
    def test_it_objects_when_the_annotator_cannot_shadow(self):
        """Getting this wrong fails silently: the PDF view keeps rendering the
        plain iframe and nothing says why."""
        from django.test import override_settings
        from parody_web_annotate.checks import annotate_app_order
        with override_settings(INSTALLED_APPS=["parody_web", "parody_web_annotate"]):
            errors = annotate_app_order(None)
        self.assertEqual([e.id for e in errors], ["parody_web_annotate.E001"])

    def test_it_is_quiet_when_the_order_is_right(self):
        from django.test import override_settings
        from parody_web_annotate.checks import annotate_app_order
        with override_settings(INSTALLED_APPS=["parody_web_annotate", "parody_web"]):
            self.assertEqual(annotate_app_order(None), [])


class ShippedAssetTests(TestCase):
    """The bundle is built ahead of time and shipped; these guard the packaging.

    Both failures here are silent in production — the app installs, the page
    renders, and the viewer is simply blank.
    """

    def _js_dir(self):
        from pathlib import Path
        import parody_web_annotate
        return (Path(parody_web_annotate.__file__).parent
                / "static" / "parody_web_annotate" / "js")

    def test_the_bundle_and_worker_are_present(self):
        self.assertTrue((self._js_dir() / "annotate.js").is_file())
        self.assertTrue((self._js_dir() / "pdf.worker.js").is_file())

    def test_the_worker_is_not_shipped_as_mjs(self):
        """Python's mimetypes does not know .mjs, so Django and whitenoise
        serve it as application/octet-stream — and a module import is strictly
        MIME-checked, so the browser refuses it and the viewer renders nothing.
        Found in production; this is the guard."""
        import mimetypes
        self.assertEqual(list(self._js_dir().glob("*.mjs")), [])
        guessed, _ = mimetypes.guess_type("pdf.worker.js")
        self.assertIn("javascript", guessed or "")

    def test_the_template_points_at_the_worker_that_exists(self):
        from django.template.loader import render_to_string
        from pathlib import Path
        import parody_web_annotate
        source = (Path(parody_web_annotate.__file__).parent / "templates"
                  / "parody_web" / "_pdf_view_stage.html").read_text()
        self.assertIn("pdf.worker.js", source)
        self.assertNotIn("pdf.worker.mjs", source)


class DownloadLinkTests(TestCase):
    """A reader who has written on a section and then downloads it must get
    the copy with their marks on it. The link used to always point at the
    clean slice, so the notes were simply missing."""

    def setUp(self):
        import tempfile
        from pathlib import Path
        from django.test import Client
        from parody_web.tests_printing import import_artifact, make_pdf_with_content

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        make_pdf_with_content(self.root / "print-book.pdf", 20)
        self.book = import_artifact()
        self.reader = get_user_model().objects.create_user("reader", password="x")
        self.client = Client()

    def _settings(self):
        from django.test import override_settings
        return override_settings(PARODY_WEB_PRINT_ROOT=str(self.root))

    def _ink(self):
        self.client.put("/one/alpha/ink/",
                        {"strokes": {"1": [{"tool": "pen", "color": "#000",
                                            "opacity": 1, "d": "M1 1 L9 9 Z"}]}},
                        content_type="application/json")

    def test_with_notes_the_viewer_offers_the_annotated_copy(self):
        self.client.force_login(self.reader)
        with self._settings():
            self._ink()
            html = self.client.get("/one/alpha/pdf/view/").content.decode()
        self.assertIn("/one/alpha/pdf/annotated/", html)
        # The visible label is just "Download" — the bar drops it entirely
        # below 70rem, so a qualifier shown only on a wide screen would be a
        # distinction the tablet reader who made the notes never sees. The
        # accessible name carries it at every width.
        self.assertIn(
            'aria-label="Download this section with your notes"', html)

    def test_without_notes_it_offers_the_plain_pdf(self):
        self.client.force_login(self.reader)
        with self._settings():
            html = self.client.get("/one/alpha/pdf/view/").content.decode()
        self.assertNotIn("pdf/annotated/", html)
        # The exits are icon buttons now; the accessible name is what says
        # which copy this is. The closing quote matters — without it this also
        # matches "Download this section with your notes".
        self.assertIn('aria-label="Download this section"', html)

    def test_the_section_rail_offers_it_too(self):
        """The rail is where a reader actually reaches for the download."""
        self.client.force_login(self.reader)
        with self._settings():
            self._ink()
            html = self.client.get("/one/alpha/").content.decode()
        self.assertIn("/one/alpha/pdf/annotated/", html)
        self.assertIn("with your notes", html)

    def test_an_empty_layer_does_not_promise_notes(self):
        """Erasing everything leaves a row behind; the link must not claim
        marks that are no longer there."""
        self.client.force_login(self.reader)
        with self._settings():
            self._ink()
            self.client.put("/one/alpha/ink/", {"strokes": {}},
                            content_type="application/json")
            html = self.client.get("/one/alpha/pdf/view/").content.decode()
        self.assertNotIn("pdf/annotated/", html)

    def test_anonymous_readers_see_the_plain_link(self):
        with self._settings():
            html = self.client.get("/one/alpha/pdf/view/").content.decode()
        self.assertNotIn("pdf/annotated/", html)
        # The exits are icon buttons now; the accessible name is what says
        # which copy this is. The closing quote matters — without it this also
        # matches "Download this section with your notes".
        self.assertIn('aria-label="Download this section"', html)
