"""Removing audio nothing refers to — and, mostly, NOT removing anything else.

Re-synthesising costs money, so every test here that asserts something survives
is worth more than the one that asserts something goes.
"""
import os
import tempfile
from datetime import timedelta
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from parody_web_readaloud import storage
from parody_web_readaloud.models import ReadAlongTrack
from parody_web_readaloud.tests_storage import FakeS3

KEY_A = "a" * 64
KEY_B = "b" * 64
KEY_C = "c" * 64
OLD = timezone.now() - timedelta(days=30)


def name(key, voice="Matthew"):
    return f"{key}-{voice}.mp3"


class PruneOnDiskTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def _settings(self, **extra):
        return override_settings(PARODY_WEB_READALOUD_CACHE=str(self.root),
                                 PARODY_WEB_READALOUD_BUCKET="", **extra)

    def _file(self, filename, age_days=30):
        path = self.root / filename
        path.write_bytes(b"ID3" * 100)
        when = (timezone.now() - timedelta(days=age_days)).timestamp()
        os.utime(path, (when, when))
        return path

    def _track(self, audio_name, n=1):
        return ReadAlongTrack.objects.create(
            book_slug="b", section_key=f"s{n}", slice_key=str(n) * 64,
            voice_id="Matthew", audio_name=audio_name)

    def _run(self, *args):
        out, err = StringIO(), StringIO()
        call_command("prune_readalong_audio", *args, stdout=out, stderr=err)
        return out.getvalue() + err.getvalue()

    def test_an_unreferenced_file_is_reported_but_not_removed_by_default(self):
        """Reporting is the default because deleting is not undoable."""
        self._file(name(KEY_A))
        self._track(name(KEY_B))
        self._file(name(KEY_B))
        with self._settings():
            output = self._run()
        self.assertIn("would delete 1", output)
        self.assertTrue((self.root / name(KEY_A)).exists())

    def test_delete_removes_only_the_unreferenced_one(self):
        self._file(name(KEY_A))
        self._file(name(KEY_B))
        self._track(name(KEY_B))
        with self._settings():
            output = self._run("--delete")
        self.assertFalse((self.root / name(KEY_A)).exists())
        self.assertTrue((self.root / name(KEY_B)).exists())
        self.assertIn("deleted 1", output)
        self.assertIn("in use 1", output)

    def test_a_file_shared_by_several_rows_survives(self):
        """Audio is named from the TEXT, so two paginations — and two editions
        whose words match — point at one file. Counting references per row and
        deleting on the first miss would take it."""
        self._file(name(KEY_A))
        self._track(name(KEY_A), 1)
        self._track(name(KEY_A), 2)
        with self._settings():
            self._run("--delete")
        self.assertTrue((self.root / name(KEY_A)).exists())

    def test_another_books_audio_is_not_stale(self):
        """The live set is the WHOLE table. Scoped per book, this file would
        be deleted while the other book is still serving it."""
        self._file(name(KEY_A))
        ReadAlongTrack.objects.create(
            book_slug="other-book", section_key="s9", slice_key="9" * 64,
            voice_id="Matthew", audio_name=name(KEY_A))
        with self._settings():
            self._run("--delete")
        self.assertTrue((self.root / name(KEY_A)).exists())

    def test_a_recent_file_is_held_back(self):
        """generate_readalong writes the FILE before it writes the ROW, so a
        file with no row may be a run that is still going."""
        self._file(name(KEY_A), age_days=1)
        self._track(name(KEY_B))
        with self._settings():
            output = self._run("--delete")
        self.assertTrue((self.root / name(KEY_A)).exists())
        self.assertIn("too new to touch 1", output)

    def test_older_than_zero_disables_the_hold_back_entirely(self):
        """Not "written before this instant" — OFF.

        The timestamp compared is the store's, and S3's runs ahead of ours: it
        rounds up to the second and the clocks differ, so a just-written object
        reads as ~0.6 s in the FUTURE (measured against the real bucket). Read
        as a cutoff, zero holds back everything and prunes nothing.
        """
        self._file(name(KEY_A), age_days=-1)     # timestamped in the future
        self._file(name(KEY_C), age_days=1)
        self._track(name(KEY_B))
        with self._settings():
            output = self._run("--delete", "--older-than", "0")
        self.assertFalse((self.root / name(KEY_A)).exists())
        self.assertFalse((self.root / name(KEY_C)).exists())
        self.assertIn("too new to touch 0", output)

    def test_a_future_timestamp_is_held_back_at_a_normal_cutoff(self):
        """Skew must not become a way to delete something early."""
        self._file(name(KEY_A), age_days=-1)
        self._track(name(KEY_B))
        with self._settings():
            self._run("--delete")
        self.assertTrue((self.root / name(KEY_A)).exists())

    def test_a_file_we_did_not_write_is_never_touched(self):
        """A prefix is not necessarily this app's private property."""
        self._file("notes.txt")
        self._file("something-else.mp3")
        self._track(name(KEY_B))
        with self._settings():
            output = self._run("--delete")
        self.assertTrue((self.root / "notes.txt").exists())
        self.assertTrue((self.root / "something-else.mp3").exists())
        self.assertIn("not ours 2", output)

    def test_an_empty_table_refuses_to_prune(self):
        """A fresh database and the wrong database look identical from here,
        and both would delete everything."""
        self._file(name(KEY_A))
        with self._settings(), self.assertRaises(CommandError) as caught:
            self._run("--delete")
        self.assertIn("--force", str(caught.exception))
        self.assertTrue((self.root / name(KEY_A)).exists())

    def test_force_prunes_an_empty_table(self):
        self._file(name(KEY_A))
        with self._settings():
            self._run("--delete", "--force")
        self.assertFalse((self.root / name(KEY_A)).exists())

    def test_a_preview_row_naming_no_audio_does_not_make_things_live(self):
        self._file(name(KEY_A))
        self._track("")
        with self._settings(), self.assertRaises(CommandError):
            self._run("--delete")

    def test_an_empty_store_is_not_an_error(self):
        self._track(name(KEY_A))
        with self._settings():
            output = self._run("--delete")
        self.assertIn("nothing to prune", output)


class PruneInS3Tests(TestCase):
    def setUp(self):
        self.fake = FakeS3()
        patcher = patch.object(storage, "_s3_client", lambda *a, **k: self.fake)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _settings(self, **extra):
        return override_settings(PARODY_WEB_READALOUD_BUCKET="bkt",
                                 PARODY_WEB_READALOUD_PREFIX="readalong/",
                                 PARODY_WEB_READALOUD_CACHE="", **extra)

    def _track(self, audio_name, n=1):
        return ReadAlongTrack.objects.create(
            book_slug="b", section_key=f"s{n}", slice_key=str(n) * 64,
            voice_id="Matthew", audio_name=audio_name)

    def _run(self, *args):
        out, err = StringIO(), StringIO()
        call_command("prune_readalong_audio", *args, stdout=out, stderr=err)
        return out.getvalue() + err.getvalue()

    def test_a_stale_object_is_deleted_under_the_prefix(self):
        self.fake.objects = {
            "readalong/" + name(KEY_A): (1000, OLD),
            "readalong/" + name(KEY_B): (2000, OLD),
        }
        self._track(name(KEY_B))
        with self._settings():
            self._run("--delete")
        self.assertEqual(self.fake.deleted,
                         [("bkt", "readalong/" + name(KEY_A))])

    def test_the_listing_is_paginated(self):
        """A truncated listing reads as 'nothing else is there', which to a
        prune means 'delete the rest' — but it also hides live files from the
        keep count, so the bug is silent both ways."""
        self.fake.objects = {
            f"readalong/{i:064x}-Matthew.mp3": (10, OLD) for i in range(2500)}
        self._track(name(KEY_A))
        with self._settings():
            output = self._run()
        self.assertGreater(self.fake.list_pages, 1)
        self.assertIn("would delete 2500", output)

    def test_objects_outside_the_prefix_are_invisible(self):
        self.fake.objects = {"readalong/" + name(KEY_A): (10, OLD)}
        self.fake.other = {"media/photo.jpg": (10, OLD)}
        self._track(name(KEY_B))
        with self._settings():
            output = self._run("--delete")
        self.assertNotIn("photo.jpg", output)
        self.assertEqual(len(self.fake.deleted), 1)

    def test_a_nested_key_is_not_a_candidate(self):
        self.fake.objects = {"readalong/archive/" + name(KEY_A): (10, OLD)}
        self._track(name(KEY_B))
        with self._settings():
            output = self._run("--delete")
        self.assertEqual(self.fake.deleted, [])
        self.assertIn("nothing to prune", output)
