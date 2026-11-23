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

    def test_the_engine_is_given_the_pages_macros_by_default(self):
        # The default IS the page's list, not a copy of it: a macro added for
        # the page is spoken without anyone remembering read-along.
        from parody_web.mathjax import MACROS

        sent = []

        class Recording(SreMath):
            def _invoke(self, payload):
                sent.append(payload)
                return {"texts": ["x"]}

        Recording().speak_all([("\\bm{x}", False)])
        self.assertIs(sent[0]["macros"], MACROS)
        sent.clear()
        Recording(macros={}).speak_all([("\\bm{x}", False)])
        self.assertEqual(sent[0]["macros"], {})

    @unittest.skipUnless(shutil.which("node") and _sre_script().exists(),
                         "needs node and the SRE script")
    def test_a_bold_vector_is_not_read_as_its_macro_name(self):
        """The reported bug: read-along said "backslash B M".

        MathJax keeps an undefined macro's name as text and SRE reads it out,
        so this failed with no error anywhere — only by listening.
        """
        said = SreMath().speak_all([("\\bm{x} = \\abs{y}", False)])
        self.assertEqual(said[0], "bold italic x equals the absolute value of y")

    @unittest.skipUnless(shutil.which("node") and _sre_script().exists(),
                         "needs node and the SRE script")
    def test_a_revealed_bold_vector_is_drawn_not_spelled(self):
        # The same gap, seen: a blank's reveal is an SVG drawn by the same
        # MathJax, and an unknown macro draws as its own name in red — an
        # `mtext` node. A reader saw "\bm" under a revealed blank.
        svg = SreMath().render_all([("\\bm{x}", False)])[0]
        self.assertIsNotNone(svg)
        self.assertNotIn('data-mml-node="mtext"', svg)
        self.assertNotIn('fill="red"', svg)

    @unittest.skipUnless(shutil.which("node") and _sre_script().exists(),
                         "needs node and the SRE script")
    def test_no_macro_the_page_knows_is_spoken_as_its_name(self):
        # Every macro, with letters for its arguments. "backslash" in the
        # speech means MathJax did not know the macro; nothing said at all
        # means the expansion itself failed to parse.
        from parody_web.mathjax import MACROS

        items = []
        for name, value in MACROS.items():
            arity = value[1] if isinstance(value, list) else 0
            args = "".join("{%s}" % letter for letter in "ab"[:arity])
            items.append((f"x \\{name}{args}", False))
        said = SreMath().speak_all(items)
        for (latex, _), words in zip(items, said):
            self.assertIsNotNone(words, f"{latex} was not spoken at all")
            self.assertNotIn("backslash", words, f"{latex} -> {words!r}")


@unittest.skipUnless(shutil.which("node") and _sre_script().exists(),
                     "needs node and the SRE script")
class UprightLettersTests(SimpleTestCase):
    """SRE takes an upright letter for a UNIT, or announces its font.

    speak.mjs decides by position: a unit follows a number (or a unit, or a
    unit and a / or a dot); anything else upright is a variable. Each phrase
    below is what the engine said before, measured over every expression in
    the three voiced books (13,657).
    """

    def say(self, *latex):
        return SreMath().speak_all([(each, False) for each in latex])

    def test_omega_is_a_variable_unless_it_follows_a_number(self):
        # Was "ohms sub J": System Dynamics' angular velocity, 307 expressions.
        self.assertEqual(self.say("\\Omega_J", "\\Omega = 3"),
                         ["Omega sub J", "Omega equals 3"])
        self.assertEqual(
            self.say("R = 0.8\\ \\Omega", "100\\,\\Omega", "2\\ \\mathrm{k}\\Omega"),
            ["R equals 0.8 ohms", "100 ohms", "2 kilohms"])

    def test_greek_capitals_are_not_announced_by_font(self):
        # Was "normal Phi of t" and "normal triangle t".
        self.assertEqual(self.say("\\Phi(t)", "\\Delta t", "20\\,\\Delta t"),
                         ["Phi of t", "Delta t", "20 Delta t"])

    def test_an_upright_letter_that_is_not_after_a_number_is_a_letter(self):
        # Was "R to the tons power" (795 times in robotics) and "watts hat".
        self.assertEqual(self.say("R_2^{\\mathrm{T}}", "\\hat{\\mathrm{w}}"),
                         ["R sub 2 to the T power", "w hat"])

    def test_compound_units_stay_units(self):
        self.assertEqual(
            self.say("9.81\\ \\mathrm{m/s^2}", "0.05\\ \\mathrm{N\\,m/A}",
                     "90^\\circ/\\mathrm{s}", "r = (1, 0, 1)\\ \\mathrm{m}"),
            ["9.81 meters divided by seconds squared",
             "0.05 Newtons meters divided by amperes",
             "90 degrees divided by seconds",
             "r equals open paren 1 comma 0 comma 1 close paren times meters"])

    def test_a_tex_space_is_not_read_as_empty_but_a_thin_space_keeps_its_times(self):
        # Was "1 empty milliseconds". The thin space is SRE's cue for a
        # product, so dropping it too would lose "times".
        self.assertEqual(self.say("1\\ \\mathrm{ms}", "C\\, dv/dt"),
                         ["1 millisecond", "C times d v divided by d t"])

    def test_sans_serif_and_fraktur_are_not_announced(self):
        # Was "sans serif v sub 1" (463 times in System Dynamics) and
        # "German m sub 2" (robotics' mass). Script and bold still are: they
        # tell apart symbols that sit side by side.
        self.assertEqual(
            self.say("\\mathsf{v}_1 = \\mathsf{f}(t)", "\\mathfrak{m}_2",
                     "\\mathcal{V}_s", "\\bm{x}"),
            ["v sub 1 equals f of t", "m sub 2", "script V sub s",
             "bold italic x"])

    def test_a_degree_is_a_degree(self):
        # Was "360 raised to the composed with power".
        self.assertEqual(self.say("360^\\circ"), ["360 degrees"])
        self.assertEqual(self.say("f \\circ g"), ["f composed with g"])


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


class _SubMath:
    """Speaks each item as the reply mapped from its latex."""

    def __init__(self, replies):
        self.replies = replies

    def speak_all(self, items):
        return [self.replies[latex] for latex, _display in items]


class TerseSubscriptTests(SimpleTestCase):
    """Rico, task 981: v_1 is "vee one", not "v sub 1" — when it is safe."""

    def test_simple_subscripts_drop_sub(self):
        from parody_web_readaloud.speech import terse_subscripts
        self.assertEqual(
            terse_subscripts(
                "v sub 1 i sub 1 equals negative v sub 2 i sub 2",
                r"v_{1} i_{1} = -v_2 i_2"),
            "v 1 i 1 equals negative v 2 i 2")

    def test_compound_subscript_keeps_every_sub(self):
        from parody_web_readaloud.speech import terse_subscripts
        said = "x sub k plus 1 equals x sub k plus 1"
        self.assertEqual(terse_subscripts(said, r"x_{k+1} = x_k + 1"), said)

    def test_word_subscripts_are_simple(self):
        from parody_web_readaloud.speech import subscripts_are_simple
        self.assertTrue(subscripts_are_simple(
            r"q_{\text{in}} + \tau_{\mathrm{max}} + V_{CC}"
            r" + \mathbf{T}_{sb} + \theta_1"))

    def test_compound_forms(self):
        from parody_web_readaloud.speech import subscripts_are_simple
        for latex in (r"a_{n-1}", r"x_{i,j}", r"x_{(k)}",
                      r"y_{\frac{1}{2}}", r"z_{a_b}"):
            with self.subTest(latex=latex):
                self.assertFalse(subscripts_are_simple(latex))

    def test_big_operator_limits_are_not_subscripts(self):
        from parody_web_readaloud.speech import terse_subscripts
        self.assertEqual(
            terse_subscripts("the sum from k equals 0 to n of a sub k",
                             r"\sum_{k=0}^{n} a_k"),
            "the sum from k equals 0 to n of a k")
        for op in (r"\prod", r"\int", r"\lim", r"\max", r"\min",
                   r"\sum\limits", r"\int\nolimits"):
            with self.subTest(op=op):
                self.assertEqual(
                    terse_subscripts("op of a sub k", op + r"_{k=0} a_k"),
                    "op of a k")

    def test_escaped_underscore_is_not_a_subscript(self):
        from parody_web_readaloud.speech import subscripts_are_simple
        self.assertTrue(subscripts_are_simple(r"\text{max\_speed}"))

    def test_only_whole_word_sub(self):
        from parody_web_readaloud.speech import terse_subscripts
        self.assertEqual(terse_subscripts("x sub 1 subtract", "x_1"),
                         "x 1 subtract")

    def test_build_speech_applies_rule(self):
        tokens = [Token("word", "where"), Token("math", latex="v_1")]
        text, owners = build_speech(tokens, math=_SubMath({"v_1": "v sub 1"}))
        self.assertEqual(text, "where v 1")
        self.assertEqual(len(owners), len(text.split()))

    def test_build_speech_keeps_sub_for_compound(self):
        tokens = [Token("math", latex="a_{n-1}")]
        text, _ = build_speech(
            tokens, math=_SubMath({"a_{n-1}": "a sub n minus 1"}))
        self.assertEqual(text, "a sub n minus 1")

    def test_build_speech_applies_rule_to_a_maths_cloze(self):
        tokens = [Token("cloze", latex="R_L", answer=["R_L"])]
        text, _ = build_speech(tokens, math=_SubMath({"R_L": "R sub L"}))
        self.assertEqual(text, "R L")


class TerseSubscriptRobustnessTests(SimpleTestCase):
    """A cosmetic rule must never be able to stop generation (final review)."""

    def test_backslash_at_end_does_not_crash(self):
        from parody_web_readaloud.speech import subscripts_are_simple
        for latex in ("x_\\", "x_\\\n", "x_", "x_{", "x_{a", "_", "\\"):
            with self.subTest(latex=latex):
                self.assertIn(subscripts_are_simple(latex), (True, False))

    def test_build_speech_survives_a_failing_rule(self):
        from unittest import mock

        from parody_web_readaloud import speech
        tokens = [Token("math", latex="v_1")]
        with mock.patch.object(speech, "terse_subscripts",
                               side_effect=RuntimeError("boom")):
            text, _ = build_speech(tokens,
                                   math=_SubMath({"v_1": "v sub 1"}))
        self.assertEqual(text, "v sub 1")
