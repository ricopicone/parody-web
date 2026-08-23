"""The two audio backends, and the name check that guards both."""
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from parody_web_readaloud import storage


class SafeNameTests(SimpleTestCase):
    def test_a_plain_name_passes(self):
        self.assertEqual(storage.safe_name("abc-Matthew.mp3"),
                         "abc-Matthew.mp3")

    def test_an_empty_name_is_refused(self):
        with self.assertRaises(ValueError):
            storage.safe_name("")

    def test_a_separator_is_refused(self):
        for name in ("a/b.mp3", "a\\b.mp3", "../secret.mp3", "/etc/passwd"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                storage.safe_name(name)

    def test_a_name_that_is_the_root_itself_is_refused(self):
        """Both pass a containment check and are then opened as a file."""
        for name in (".", ".."):
            with self.subTest(name=name), self.assertRaises(ValueError):
                storage.safe_name(name)


class BackendChoiceTests(SimpleTestCase):
    def test_no_bucket_and_a_cache_gives_disk(self):
        with override_settings(PARODY_WEB_READALOUD_CACHE="/tmp/x",
                               PARODY_WEB_READALOUD_BUCKET=""):
            self.assertIsInstance(storage.backend(), storage.DiskAudio)

    def test_neither_bucket_nor_cache_raises(self):
        with override_settings(PARODY_WEB_READALOUD_CACHE="",
                               PARODY_WEB_READALOUD_BUCKET=""):
            with self.assertRaises(RuntimeError):
                storage.backend()

    def test_a_bucket_wins_and_needs_no_cache(self):
        """S3 makes the cache setting irrelevant, not merely optional."""
        with override_settings(PARODY_WEB_READALOUD_CACHE="",
                               PARODY_WEB_READALOUD_BUCKET="b"):
            store = storage.backend()
        self.assertIsInstance(store, storage.S3Audio)
        self.assertEqual(store.bucket, "b")
        self.assertEqual(store.prefix, "readalong/")

    def test_encryption_is_inherited_but_the_bucket_is_not(self):
        """A host's media bucket is not read-along's to write into.

        Encryption is the opposite case: a bucket policy demanding SSE would
        reject every put with no obvious cause, so that setting is inherited.
        """
        with override_settings(PARODY_WEB_READALOUD_CACHE="/tmp/x",
                               AWS_STORAGE_BUCKET_NAME="media-bucket",
                               AWS_S3_SSE="AES256"):
            self.assertIsInstance(storage.backend(), storage.DiskAudio)
        with override_settings(PARODY_WEB_READALOUD_BUCKET="b",
                               AWS_S3_SSE="AES256"):
            self.assertEqual(storage.backend().sse, "AES256")

    def test_region_falls_back_through_the_host_setting(self):
        with override_settings(PARODY_WEB_READALOUD_BUCKET="b",
                               AWS_S3_REGION_NAME="eu-west-1"):
            self.assertEqual(storage.backend().region, "eu-west-1")
        with override_settings(PARODY_WEB_READALOUD_BUCKET="b"):
            self.assertEqual(storage.backend().region, "us-west-2")


class DiskAudioTests(SimpleTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def _settings(self):
        return override_settings(PARODY_WEB_READALOUD_CACHE=self.tmp.name,
                                 PARODY_WEB_READALOUD_BUCKET="")

    def test_write_then_read_back(self):
        with self._settings():
            store = storage.backend()
            self.assertFalse(store.exists("a.mp3"))
            store.write("a.mp3", b"ID3")
            self.assertTrue(store.exists("a.mp3"))
            self.assertEqual(store.path("a.mp3"),
                             self.root.resolve() / "a.mp3")
            self.assertIsNone(store.url("a.mp3"))
        self.assertEqual((self.root / "a.mp3").read_bytes(), b"ID3")

    def test_write_audio_still_goes_to_disk(self):
        with self._settings():
            storage.write_audio("b.mp3", b"ID3")
        self.assertTrue((self.root / "b.mp3").exists())

    def test_a_symlink_out_of_the_cache_is_still_refused(self):
        """safe_name cannot see this one; the resolve check can."""
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: None)
        (self.root / "away").symlink_to(outside)
        with self._settings(), self.assertRaises(ValueError):
            storage.audio_path("away")


class FakeS3:
    """Stands in for a boto3 S3 client, raising the real ClientError.

    The mapping from an S3 error CODE to an absence is the thing under test,
    so the exception has to be the one botocore actually raises.
    """

    def __init__(self, missing=(), broken=None):
        self.missing = set(missing)
        self.broken = broken
        self.puts = []
        self.presigned = []

    def _fail(self, code):
        from botocore.exceptions import ClientError
        raise ClientError({"Error": {"Code": code, "Message": code}},
                          "HeadObject")

    def put_object(self, **kwargs):
        self.puts.append(kwargs)

    def head_object(self, Bucket, Key):
        if self.broken:
            self._fail(self.broken)
        if Key in self.missing:
            self._fail("404")
        return {"ContentLength": 3}

    def generate_presigned_url(self, op, Params, ExpiresIn):
        self.presigned.append((op, Params, ExpiresIn))
        return f"https://s3.example/{Params['Key']}?sig=1&exp={ExpiresIn}"


class S3AudioTests(SimpleTestCase):
    """No AWS and no network: the boto3 client factory is the seam."""

    def _store(self, fake, **over):
        patcher = patch.object(storage, "_s3_client",
                               lambda *a, **k: fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        return storage.S3Audio(bucket="bkt", prefix="readalong/",
                               region="us-west-2", expire=900, **over)

    def test_write_puts_under_the_prefix_as_mpeg(self):
        fake = FakeS3()
        self._store(fake).write("a.mp3", b"ID3")
        self.assertEqual(fake.puts, [{
            "Bucket": "bkt", "Key": "readalong/a.mp3", "Body": b"ID3",
            "ContentType": "audio/mpeg"}])

    def test_write_carries_encryption_when_configured(self):
        fake = FakeS3()
        self._store(fake, sse="AES256").write("a.mp3", b"ID3")
        self.assertEqual(fake.puts[0]["ServerSideEncryption"], "AES256")

    def test_exists_is_true_for_a_present_key(self):
        self.assertTrue(self._store(FakeS3()).exists("a.mp3"))

    def test_a_missing_key_is_false_not_an_error(self):
        fake = FakeS3(missing={"readalong/a.mp3"})
        self.assertFalse(self._store(fake).exists("a.mp3"))

    def test_access_denied_is_not_reported_as_an_absence(self):
        """Otherwise a misconfigured bucket looks exactly like an
        ungenerated track, and nothing ever says which."""
        from botocore.exceptions import ClientError

        fake = FakeS3(broken="AccessDenied")
        with self.assertRaises(ClientError):
            self._store(fake).exists("a.mp3")

    def test_url_presigns_the_prefixed_key_with_the_configured_expiry(self):
        fake = FakeS3()
        url = self._store(fake).url("a.mp3")
        self.assertEqual(fake.presigned, [
            ("get_object", {"Bucket": "bkt", "Key": "readalong/a.mp3"}, 900)])
        self.assertIn("readalong/a.mp3", url)

    def test_a_name_with_a_separator_never_reaches_the_bucket(self):
        fake = FakeS3()
        with self.assertRaises(ValueError):
            self._store(fake).write("../../etc/passwd", b"x")
        self.assertEqual(fake.puts, [])

    def test_there_is_no_local_path(self):
        self.assertIsNone(self._store(FakeS3()).path("a.mp3"))
