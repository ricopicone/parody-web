"""The two serve-only endpoints, gated exactly as the PDF is."""
import tempfile
from pathlib import Path

from django.test import Client, TestCase, override_settings

from parody_web import printing
from parody_web_readaloud.models import ReadAlongTrack


class ReadAlongEndpointTests(TestCase):
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

        self.client = Client()
        self.url = "/one/alpha/readalong/"
        self.audio_url = "/one/alpha/readalong/audio/"

    def _settings(self, **extra):
        return override_settings(
            PARODY_WEB_PRINT_ROOT=str(self.root),
            PARODY_WEB_READALOUD_CACHE=self.cache.name, **extra)

    def _make_track(self, **over):
        with self._settings():
            section = self.book.sections.get(slug="alpha")
            key = printing.slice_key_for(self.book, section)
        kwargs = dict(
            book_slug=self.book.slug, edition_id=self.book.edition_id or "",
            section_key=section.key, slice_key=key, voice_id="Matthew",
            engine="neural", audio_name="track.mp3", duration_ms=4200,
            words=[{"word": "at", "start_ms": 0, "end_ms": 100, "page": 0,
                    "x0": 1, "y0": 2, "x1": 3, "y1": 4, "token": 0}],
            clozes=[])
        kwargs.update(over)
        return ReadAlongTrack.objects.create(**kwargs)

    def test_a_missing_track_is_a_404_and_never_synthesises(self):
        with self._settings():
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(ReadAlongTrack.objects.count(), 0)

    def test_a_present_track_comes_back_as_json(self):
        self._make_track()
        with self._settings():
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["duration_ms"], 4200)
        self.assertEqual(len(body["words"]), 1)
        self.assertIn("readalong/audio/", body["audio_url"])

    def test_a_track_for_another_version_is_not_served(self):
        """Boxes from an older cut of the section would land in the wrong place."""
        self._make_track(slice_key="f" * 64)
        with self._settings():
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, 404)

    def test_missing_audio_is_a_404_not_a_500(self):
        self._make_track()
        with self._settings():
            response = self.client.get(self.audio_url)
        self.assertEqual(response.status_code, 404)

    def test_present_audio_is_served_as_mpeg(self):
        self._make_track()
        Path(self.cache.name, "track.mp3").write_bytes(b"ID3fake")
        with self._settings():
            response = self.client.get(self.audio_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "audio/mpeg")

    def test_an_unconfigured_cache_is_a_404_not_a_crash(self):
        self._make_track()
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root),
                               PARODY_WEB_READALOUD_CACHE=""):
            response = self.client.get(self.audio_url)
        self.assertEqual(response.status_code, 404)

    def test_an_unknown_section_is_a_404(self):
        with self._settings():
            response = self.client.get("/one/nosuch/readalong/")
        self.assertEqual(response.status_code, 404)

    def test_post_is_rejected(self):
        self._make_track()
        with self._settings():
            response = self.client.post(self.url)
        self.assertEqual(response.status_code, 405)


class AudioRangeTests(ReadAlongEndpointTests):
    """The browser cannot seek without byte ranges.

    Served as one 200, a jump to four minutes into a 4 MB track snaps back to
    the start — which is what made "read from here", resume and skip-ahead all
    appear to begin at the beginning, whatever was clicked.
    """

    def _serve(self, **headers):
        self._make_track()
        Path(self.cache.name, "track.mp3").write_bytes(bytes(range(256)) * 40)
        with self._settings():
            return self.client.get(self.audio_url, **headers)

    def test_a_plain_request_advertises_range_support(self):
        response = self._serve()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Accept-Ranges"], "bytes")
        self.assertEqual(int(response["Content-Length"]), 10240)

    def test_a_range_request_returns_exactly_that_range(self):
        response = self._serve(HTTP_RANGE="bytes=100-199")
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response["Content-Range"], "bytes 100-199/10240")
        self.assertEqual(int(response["Content-Length"]), 100)
        self.assertEqual(len(b"".join(response.streaming_content)), 100)

    def test_an_open_ended_range_runs_to_the_end(self):
        response = self._serve(HTTP_RANGE="bytes=10140-")
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response["Content-Range"], "bytes 10140-10239/10240")
        self.assertEqual(len(b"".join(response.streaming_content)), 100)

    def test_a_suffix_range_returns_the_last_bytes(self):
        """`bytes=-N` is how some players probe the tail of a file."""
        response = self._serve(HTTP_RANGE="bytes=-50")
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response["Content-Range"], "bytes 10190-10239/10240")

    def test_a_range_past_the_end_is_refused_properly(self):
        response = self._serve(HTTP_RANGE="bytes=99999-")
        self.assertEqual(response.status_code, 416)
        self.assertEqual(response["Content-Range"], "bytes */10240")

    def test_head_is_allowed(self):
        """Players HEAD a media URL before fetching it; 405 looks like a dead
        endpoint."""
        self._make_track()
        Path(self.cache.name, "track.mp3").write_bytes(b"x" * 10)
        with self._settings():
            response = self.client.head(self.audio_url)
        self.assertEqual(response.status_code, 200)
