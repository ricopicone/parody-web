"""What gets said, and which script token said it."""
import shutil
import unittest

from django.test import SimpleTestCase

from parody_web_readaloud.script import Token
from parody_web_readaloud.speech import (SkipMath, SreMath, _sre_script,
                                         build_speech, sre_available)


class _SpokenMath:
    def speak_all(self, items):
        return ["p of t" for _ in items]


class _ShortReplyMath:
    """An engine that returns fewer answers than it was asked for."""

    def speak_all(self, items):
        return ["only one"]


class BuildSpeechTests(SimpleTestCase):
    def test_prose_is_joined_and_mapped_one_to_one(self):
        tokens = [Token("word", "the"), Token("word", "plant")]
        text, owners = build_speech(tokens, math=SkipMath())
        self.assertEqual(text, "the plant")
        self.assertEqual(owners, [0, 1])

    def test_a_cloze_answer_is_spoken_and_owned_by_the_cloze(self):
        tokens = [Token("word", "fixed"),
                  Token("cloze", answer=["sampling", "rate"]),
                  Token("word", "which")]
        text, owners = build_speech(tokens, math=SkipMath())
        self.assertEqual(text, "fixed sampling rate which")
        self.assertEqual(owners, [0, 1, 1, 2])

    def test_trailing_punctuation_is_spoken_with_its_token(self):
        tokens = [Token("word", "rate", trail=","), Token("word", "which")]
        text, owners = build_speech(tokens, math=SkipMath())
        self.assertEqual(text, "rate, which")
        self.assertEqual(owners, [0, 1])

    def test_skipped_math_contributes_no_words(self):
        tokens = [Token("word", "when"), Token("math", latex="p(t)"),
                  Token("word", "rises")]
        text, owners = build_speech(tokens, math=SkipMath())
        self.assertEqual(text, "when rises")
        self.assertEqual(owners, [0, 2])

    def test_spoken_math_is_owned_entirely_by_its_token(self):
        tokens = [Token("word", "when"), Token("math", latex="p(t)")]
        text, owners = build_speech(tokens, math=_SpokenMath())
        self.assertEqual(text, "when p of t")
        self.assertEqual(owners, [0, 1, 1, 1])

    def test_a_figure_cloze_says_nothing(self):
        tokens = [Token("word", "see"), Token("figure_cloze", src="a.svg")]
        text, owners = build_speech(tokens, math=SkipMath())
        self.assertEqual(text, "see")
        self.assertEqual(owners, [0])

    def test_owners_index_the_words_of_the_text_actually_sent(self):
        """The contract Polly's char offsets are resolved against."""
        tokens = [Token("word", "a"), Token("math", latex="x"),
                  Token("cloze", answer=["b", "c"])]
        text, owners = build_speech(tokens, math=SkipMath())
        self.assertEqual(len(text.split()), len(owners))


    def test_math_is_asked_for_in_one_batch(self):
        """Engine setup dominates; one call per expression would not scale."""
        calls = []

        class Counting:
            def speak_all(self, items):
                calls.append(len(items))
                return [None] * len(items)

        tokens = [Token("math", latex="a"), Token("word", "x"),
                  Token("math", latex="b"), Token("math", latex="c")]
        build_speech(tokens, math=Counting())
        self.assertEqual(calls, [3])


class SkipMathTests(SimpleTestCase):
    def test_skip_math_says_nothing(self):
        self.assertEqual(SkipMath().speak_all([("x^2", False)]), [None])

    def test_no_math_asks_the_engine_for_nothing(self):
        self.assertEqual(SkipMath().speak_all([]), [])


class SreMathTests(SimpleTestCase):
    def test_a_short_reply_silences_everything_rather_than_shifting_it(self):
        """A misaligned reply would narrate every later equation wrongly."""
        class ShortReply(SreMath):
            def _invoke(self, payload):
                return {"texts": ["only one"]}

        self.assertEqual(ShortReply().speak_all([("a", False), ("b", False)]),
                         [None, None])

    def test_a_matching_reply_is_used(self):
        class Good(SreMath):
            def _invoke(self, payload):
                return {"texts": ["one", "  "]}

        self.assertEqual(Good().speak_all([("a", False), ("b", False)]),
                         ["one", None])

    def test_a_missing_node_falls_back_to_silence_not_an_exception(self):
        engine = SreMath(node="definitely-not-a-real-binary")
        self.assertEqual(engine.speak_all([("x^2", False)]), [None])

    @unittest.skipUnless(shutil.which("node") and _sre_script().exists(),
                         "needs node and the SRE script")
    def test_the_real_chain_speaks_an_expression(self):
        said = SreMath().speak_all([("x^2", False), ("\\frac{k}{m}", True)])
        self.assertEqual(said[0], "x squared")
        self.assertEqual(said[1], "k over m")

    @unittest.skipUnless(shutil.which("node") and _sre_script().exists(),
                         "needs node and the SRE script")
    def test_subscripts_are_spoken_the_way_a_lecturer_says_them(self):
        """clearspeak, not mathspeak.

        Mathspeak is built for unambiguous dictation and says "upper Z
        Subscript upper C Baseline"; a reader listening to prose wants "Z sub
        C".
        """
        said = SreMath().speak_all([("Z_C", False), ("v_+", False)])
        self.assertEqual(said[0], "Z sub C")
        self.assertEqual(said[1], "v sub plus")


class SreAvailableTests(SimpleTestCase):
    """The preflight that stops a whole book being generated mute.

    SreMath treats every failure as silence, so without this a misconfigured
    host produces tracks with every equation missing and says nothing.
    """

    def test_a_missing_node_is_reported_not_swallowed(self):
        ok, why = sre_available(node="definitely-not-a-real-binary")
        self.assertFalse(ok)
        self.assertIn("node", why)

    @unittest.skipUnless(shutil.which("node") and _sre_script().exists(),
                         "needs node and the SRE script")
    def test_a_working_setup_reports_ok(self):
        ok, why = sre_available()
        self.assertTrue(ok, why)
        self.assertEqual(why, "")


class TidyMathSpeechTests(SimpleTestCase):
    """SRE's line scaffolding, spoken aloud, is noise (task #615).

    A multi-line equation comes back as "3 lines Line 1: … Line 2: blank
    equals …" — the counts and markers are structure read out, and the "blank"
    is SRE naming the empty left cell of an aligned continuation.
    """

    def test_the_line_count_prefix_goes(self):
        from parody_web_readaloud.speech import tidy_math_speech
        self.assertEqual(tidy_math_speech("3 lines a equals b"), "a equals b")

    def test_a_line_marker_becomes_a_full_stop(self):
        """Not simply deleted: a derivation read as one unbroken sentence is
        worse than one read with the scaffolding in it."""
        from parody_web_readaloud.speech import tidy_math_speech
        self.assertEqual(
            tidy_math_speech("2 lines Line 1: a equals b Line 2: blank "
                             "equals c"),
            "a equals b. equals c")

    def test_a_blank_only_goes_when_it_is_the_empty_cell(self):
        from parody_web_readaloud.speech import tidy_math_speech
        self.assertEqual(tidy_math_speech("x equals blank plus y"),
                         "x equals blank plus y")

    def test_an_ordinary_expression_is_untouched(self):
        from parody_web_readaloud.speech import tidy_math_speech
        for said in ("Z equals v over i", "x squared", "Z sub C", ""):
            self.assertEqual(tidy_math_speech(said), said)

    def test_it_does_not_leave_leading_punctuation(self):
        from parody_web_readaloud.speech import tidy_math_speech
        self.assertEqual(tidy_math_speech("Line 1: a equals b"), "a equals b")
