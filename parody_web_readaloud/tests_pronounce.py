"""The Kokoro correction table: what is said, and the fingerprint that knows."""
import re
from unittest import mock

from django.test import SimpleTestCase, override_settings

from parody_web_readaloud import pronounce, speech
from parody_web_readaloud.pronounce import (KOKORO_VOCAB, engine_family,
                                            engine_id, load_table, spoken_form)

TEXT = "see (e.g. Laplace, 10 mH."
ANNOTATION = re.compile(r"\[([^\]]+)\]\(/[^)]*/\)")


class SpokenFormTests(SimpleTestCase):
    def test_neural_text_is_untouched(self):
        self.assertIs(spoken_form(TEXT, "neural"), TEXT)
        self.assertIs(spoken_form(TEXT, "standard"), TEXT)

    def test_kokoro_wraps_whole_words_with_punctuation(self):
        self.assertEqual(
            spoken_form(TEXT, "kokoro"),
            "see ([e.g.](/fɔɹ ɪɡzˈæmpəl/) [Laplace](/ləplˈɑs/),"
            " 10 [mH](/mˈɪlɪhˌɛnɹiz/).")

    def test_annotations_strip_back_to_text(self):
        spoken = spoken_form(TEXT + " Kirchhoff's “Thévenin” n-th", "kokoro")
        self.assertNotEqual(spoken, TEXT)
        self.assertEqual(ANNOTATION.sub(r"\1", spoken),
                         TEXT + " Kirchhoff's “Thévenin” n-th")

    def test_non_table_words_untouched(self):
        self.assertEqual(spoken_form("the Laplacian mHz", "kokoro"),
                         "the Laplacian mHz")


class EngineIdTests(SimpleTestCase):
    def test_engine_id_neural_unchanged(self):
        self.assertEqual(engine_id("neural"), "neural")
        self.assertEqual(engine_id("standard"), "standard")

    def test_engine_id_kokoro_shape(self):
        eid = engine_id("kokoro")
        self.assertRegex(eid, r"^kokoro@[0-9a-f]{12}$")
        self.assertLessEqual(len(eid), 20)       # ReadAlongTrack.engine
        self.assertEqual(engine_family(eid), "kokoro")
        self.assertEqual(engine_family("neural"), "neural")

    def test_engine_id_moves_with_table_and_speech_version(self):
        base = engine_id("kokoro")
        bigger = dict(load_table(), Bode="bˈOdi")
        self.assertNotEqual(engine_id("kokoro", bigger), base)
        with mock.patch.object(speech, "SPEECH_VERSION", "999"):
            self.assertNotEqual(engine_id("kokoro"), base)

    @override_settings(PARODY_WEB_READALOUD_PRONUNCIATIONS={"Bode": "bˈOdi"})
    def test_host_setting_extends_table(self):
        table = load_table()
        self.assertEqual(table["Bode"], "bˈOdi")
        self.assertIn("Laplace", table)


class TableTests(SimpleTestCase):
    def test_phonemes_use_kokoro_vocab(self):
        for word, phonemes in load_table().items():
            stray = {c for c in phonemes if c not in KOKORO_VOCAB and c != " "}
            self.assertFalse(stray, f"{word}: {sorted(stray)}")

    def test_vocab_is_kokoros(self):
        self.assertEqual(len(KOKORO_VOCAB), 114)
        self.assertIn("ˈ", KOKORO_VOCAB)

    def test_family_is_a_module_constant(self):
        self.assertEqual(pronounce.KOKORO, "kokoro")
