"""Moving audio a box has already paid for, rather than re-buying it."""
import tempfile
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from parody_web_readaloud import storage
from parody_web_readaloud.models import ReadAlongTrack
from parody_web_readaloud.tests_storage import FakeS3


class SyncCommandTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cache = Path(self.tmp.name)
        self.fake = FakeS3()
        patcher = patch.object(storage, "_s3_client", lambda *a, **k: self.fake)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _settings(self, **extra):
        extra.setdefault("PARODY_WEB_READALOUD_BUCKET", "bkt")
        return override_settings(
            PARODY_WEB_READALOUD_CACHE=str(self.cache), **extra)

    def _track(self, name, n=1):
        return ReadAlongTrack.objects.create(
            book_slug="b", section_key=f"s{n}", slice_key=str(n) * 64,
            voice_id="Matthew", audio_name=name)

    def _run(self, *args):
        out, err = StringIO(), StringIO()
        call_command("sync_readalong_audio", *args, stdout=out, stderr=err)
        return out.getvalue() + err.getvalue()

    def test_a_missing_key_is_uploaded_from_disk(self):
        self._track("a.mp3")
        (self.cache / "a.mp3").write_bytes(b"ID3one")
        self.fake.missing.add("readalong/a.mp3")
        with self._settings():
            output = self._run()
        self.assertEqual(self.fake.puts, [{
            "Bucket": "bkt", "Key": "readalong/a.mp3", "Body": b"ID3one",
            "ContentType": "audio/mpeg"}])
        self.assertIn("uploaded 1", output)

    def test_a_key_already_there_is_left_alone(self):
        self._track("a.mp3")
        (self.cache / "a.mp3").write_bytes(b"ID3one")
        with self._settings():
            output = self._run()
        self.assertEqual(self.fake.puts, [])
        self.assertIn("already there 1", output)

    def test_a_row_whose_file_is_gone_is_counted_and_named(self):
        """That row is a track that 404s for a reader today. The sync is
        where it becomes visible instead of being found by pressing play."""
        self._track("gone.mp3")
        self.fake.missing.add("readalong/gone.mp3")
        with self._settings():
            output = self._run()
        self.assertIn("missing from disk 1", output)
        self.assertIn("gone.mp3", output)
        self.assertEqual(self.fake.puts, [])

    def test_dry_run_uploads_nothing(self):
        self._track("a.mp3")
        (self.cache / "a.mp3").write_bytes(b"ID3one")
        self.fake.missing.add("readalong/a.mp3")
        with self._settings():
            output = self._run("--dry-run")
        self.assertEqual(self.fake.puts, [])
        self.assertIn("would upload 1", output)

    def test_each_file_is_uploaded_once_however_many_rows_share_it(self):
        """A reflow leaves several rows pointing at one mp3 — that is the
        whole point of naming the file from text_key rather than slice_key."""
        self._track("a.mp3", 1)
        self._track("a.mp3", 2)
        (self.cache / "a.mp3").write_bytes(b"ID3one")
        self.fake.missing.add("readalong/a.mp3")
        with self._settings():
            self._run()
        self.assertEqual(len(self.fake.puts), 1)

    def test_a_preview_row_with_no_audio_is_not_a_miss(self):
        self._track("")
        with self._settings():
            output = self._run()
        self.assertIn("nothing to sync", output)

    def test_it_refuses_to_run_without_a_bucket(self):
        self._track("a.mp3")
        with self._settings(PARODY_WEB_READALOUD_BUCKET=""), \
                self.assertRaises(CommandError):
            self._run()

    def test_from_overrides_the_cache_setting(self):
        other = tempfile.TemporaryDirectory()
        self.addCleanup(other.cleanup)
        self._track("a.mp3")
        (Path(other.name) / "a.mp3").write_bytes(b"elsewhere")
        self.fake.missing.add("readalong/a.mp3")
        with self._settings():
            self._run("--from", other.name)
        self.assertEqual(self.fake.puts[0]["Body"], b"elsewhere")
