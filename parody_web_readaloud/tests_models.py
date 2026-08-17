"""Track identity: one synthesis per version per voice, shared by all readers."""
from django.db.utils import IntegrityError
from django.test import TestCase

from parody_web_readaloud.models import ReadAlongTrack


class ReadAlongTrackTests(TestCase):
    def _make(self, **over):
        kwargs = dict(book_slug="rtc", edition_id="", section_key="ch1/s2",
                      slice_key="a" * 64, voice_id="Matthew", engine="neural",
                      audio_name="a-Matthew.mp3", duration_ms=1000,
                      words=[], clozes=[])
        kwargs.update(over)
        return ReadAlongTrack.objects.create(**kwargs)

    def test_one_track_per_version_and_voice(self):
        self._make()
        with self.assertRaises(IntegrityError):
            self._make()

    def test_a_second_voice_is_a_second_track(self):
        self._make()
        self._make(voice_id="Joanna", audio_name="a-Joanna.mp3")
        self.assertEqual(ReadAlongTrack.objects.count(), 2)

    def test_a_new_version_of_the_section_is_a_new_track(self):
        self._make()
        self._make(slice_key="b" * 64, audio_name="b-Matthew.mp3")
        self.assertEqual(ReadAlongTrack.objects.count(), 2)

    def test_another_edition_is_a_separate_track(self):
        self._make()
        self._make(edition_id="ed2")
        self.assertEqual(ReadAlongTrack.objects.count(), 2)

    def test_cloze_count_reports_what_the_student_will_fill(self):
        track = self._make(clozes=[{"token": 3}, {"token": 9}])
        self.assertEqual(track.cloze_count, 2)

    def test_cloze_count_copes_with_an_empty_track(self):
        self.assertEqual(self._make().cloze_count, 0)
