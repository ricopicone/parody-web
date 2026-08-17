"""What gets said, and which script token said it."""
import shutil
import unittest

from django.test import SimpleTestCase

from parody_web_readaloud.script import Token
from parody_web_readaloud.speech import SRE_SCRIPT, SkipMath, SreMath, build_speech


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

    @unittest.skipUnless(shutil.which("node") and SRE_SCRIPT.exists(),
                         "needs node and the SRE script")
    def test_the_real_chain_speaks_an_expression(self):
        said = SreMath().speak_all([("x^2", False), ("\\frac{k}{m}", True)])
        self.assertEqual(said[0], "x squared")
        self.assertIn("Fraction", said[1])
