"""Joining the clean script to the typeset page."""
from django.test import SimpleTestCase

from parody_web_readaloud.align import align
from parody_web_readaloud.geometry import PageWord
from parody_web_readaloud.script import Token


def _w(text, page=0, x0=0.0):
    return PageWord(text=text, page=page, x0=x0, y0=10.0, x1=x0 + 8, y1=20.0)


class AlignTests(SimpleTestCase):
    def test_matching_words_get_their_boxes(self):
        tokens = [Token("word", "alpha"), Token("word", "beta")]
        words = [_w("alpha", x0=0), _w("beta", x0=10)]
        placed = align(tokens, words, [])
        self.assertEqual([p.page for p in placed], [0, 0])
        self.assertEqual(placed[1].box, (10.0, 10.0, 18.0, 20.0))

    def test_running_heads_are_dropped_not_matched(self):
        tokens = [Token("word", "alpha")]
        words = [_w("Real-Time", x0=0), _w("Computing", x0=20),
                 _w("alpha", x0=40)]
        placed = align(tokens, words, [])
        self.assertEqual(len(placed), 1)
        self.assertEqual(placed[0].box[0], 40.0)

    def test_case_and_punctuation_do_not_block_a_match(self):
        tokens = [Token("word", "Sampled.")]
        placed = align(tokens, [_w("sampled", x0=5)], [])
        self.assertIsNotNone(placed[0].box)

    def test_a_hyphenated_break_still_places_the_word(self):
        """Two page words collapsing onto one token, the classic PDF artifact."""
        tokens = [Token("word", "the"), Token("word", "continuous"),
                  Token("word", "signal")]
        words = [_w("the", x0=0), _w("con-", x0=10), _w("tinuous", x0=0),
                 _w("signal", x0=20)]
        placed = align(tokens, words, [])
        self.assertIsNotNone(placed[1].box)
        self.assertIsNotNone(placed[2].box)

    def test_a_cloze_takes_its_box_from_the_rule_not_the_prose(self):
        tokens = [Token("word", "fixed"),
                  Token("cloze", answer=["sampling", "rate"]),
                  Token("word", "which")]
        words = [_w("fixed", x0=0), _w("which", x0=60)]
        rules = [{"page": 0, "x0": 20.0, "y0": 18.0, "x1": 55.0, "y1": 19.0}]
        placed = align(tokens, words, rules)
        cloze = [p for p in placed if p.token.kind == "cloze"][0]
        self.assertEqual(cloze.page, 0)
        self.assertEqual(cloze.box, (20.0, 18.0, 55.0, 19.0))

    def test_a_cloze_with_no_rule_gets_no_box(self):
        """Better silent than revealing over the wrong part of the page."""
        tokens = [Token("word", "alpha"), Token("cloze", answer=["ghost"])]
        placed = align(tokens, [_w("alpha")], [])
        cloze = [p for p in placed if p.token.kind == "cloze"][0]
        self.assertIsNone(cloze.box)

    def test_math_survives_alignment_despite_its_glyphs(self):
        """Inline math extracts as mathematical-alphanumeric codepoints."""
        tokens = [Token("word", "when"), Token("math", latex="p(t)"),
                  Token("word", "rises")]
        words = [_w("when", x0=0), _w("\U0001d45d(\U0001d461)", x0=20),
                 _w("rises", x0=40)]
        placed = align(tokens, words, [])
        self.assertEqual([p.token.kind for p in placed],
                         ["word", "math", "word"])
        self.assertIsNotNone(placed[1].box)

    def test_an_empty_key_token_never_matches_anything(self):
        """A token that normalises to "" must not match an unrelated word."""
        tokens = [Token("word", "—"), Token("word", "alpha")]
        placed = align(tokens, [_w("alpha", x0=30)], [])
        self.assertIsNone(placed[0].box)
        self.assertEqual(placed[1].box[0], 30.0)

    def test_clozes_take_rules_in_reading_order(self):
        tokens = [Token("cloze", answer=["one"]), Token("word", "mid"),
                  Token("cloze", answer=["two"])]
        rules = [{"page": 0, "x0": 1.0, "y0": 1.0, "x1": 20.0, "y1": 2.0},
                 {"page": 1, "x0": 3.0, "y0": 5.0, "x1": 30.0, "y1": 6.0}]
        placed = align(tokens, [_w("mid")], rules)
        clozes = [p for p in placed if p.token.kind == "cloze"]
        self.assertEqual(clozes[0].page, 0)
        self.assertEqual(clozes[1].page, 1)


class WindowedRuleMatchingTests(SimpleTestCase):
    """A blank is the rule between the words either side of its cloze."""

    def test_a_stray_rule_outside_the_window_is_not_taken(self):
        """Fraction bars are flat strokes too — position is what rejects them."""
        tokens = [Token("word", "alpha"), Token("cloze", answer=["x"]),
                  Token("word", "beta")]
        words = [_w("alpha", x0=0), _w("beta", x0=40)]
        stray = {"page": 5, "x0": 0.0, "y0": 900.0, "x1": 40.0, "y1": 901.0}
        placed = align(tokens, words, [stray])
        cloze = [p for p in placed if p.token.kind == "cloze"][0]
        self.assertIsNone(cloze.box)

    def test_two_clozes_take_two_different_rules_in_order(self):
        tokens = [Token("word", "a"), Token("cloze", answer=["x"]),
                  Token("word", "b"), Token("cloze", answer=["y"]),
                  Token("word", "c")]
        words = [PageWord("a", 0, 0, 10, 8, 20), PageWord("b", 0, 0, 40, 8, 50),
                 PageWord("c", 0, 0, 70, 8, 80)]
        rules = [{"page": 0, "x0": 0.0, "y0": 25.0, "x1": 60.0, "y1": 26.0},
                 {"page": 0, "x0": 0.0, "y0": 55.0, "x1": 60.0, "y1": 56.0}]
        placed = align(tokens, words, rules)
        got = [p.box[1] for p in placed if p.token.kind == "cloze"]
        self.assertEqual(got, [25.0, 55.0])

    def test_a_big_divergence_leaves_tokens_unplaced_not_mispositioned(self):
        """397 tokens once took one box spanning half a page, and counted as
        placed while pointing at nothing."""
        tokens = [Token("word", f"t{i}") for i in range(40)]
        words = [_w("unrelated", x0=0)]
        placed = align(tokens, words, [])
        self.assertEqual(sum(1 for p in placed if p.box), 0)


class PatienceAnchorTests(SimpleTestCase):
    """Rare words anchor the match where plain LCS wanders."""

    def test_a_passage_after_an_interpolation_still_matches(self):
        common = ["the", "of", "the", "of"] * 3
        tokens = ([Token("word", w) for w in common]
                  + [Token("word", "quadrature"), Token("word", "phasor")]
                  + [Token("word", w) for w in common])
        page = ([_w(w, x0=i) for i, w in enumerate(common)]
                + [_w("FOOTNOTE", x0=99), _w("MARKER", x0=98)]
                + [_w("quadrature", x0=50), _w("phasor", x0=60)]
                + [_w(w, x0=i) for i, w in enumerate(common)])
        placed = align(tokens, page, [])
        rare = [p for p in placed if p.token.text in ("quadrature", "phasor")]
        self.assertTrue(all(p.box for p in rare),
                        "unique words must anchor across the interpolation")


class DisplayMathExtentTests(SimpleTestCase):
    """A display equation is ONE token that typesets as many extracted chunks.

    Its LaTeX can never match the page glyph by glyph, so the only route to a
    box is the local-replace escape hatch — which was sized for a hyphenated
    line break (one token, a few page words). A multi-line derivation exceeds
    that easily, and an equation with no box freezes the karaoke mark for the
    whole minute SRE spends narrating it.
    """

    def test_a_multiline_equation_takes_the_extent_it_typeset_to(self):
        tokens = [Token("word", "so"),
                  Token("math", latex=r"\begin{aligned} v_o &= A (v_+ - v_-)"
                                      r"\\ &= A (v_i - v_o) \end{aligned}",
                        display=True),
                  Token("word", "rearranged")]
        glyphs = ["\U0001d463\U0001d45c=", "\U0001d434(\U0001d463+",
                  "−\U0001d463−)", "=", "⇒",
                  "\U0001d463\U0001d45c=", "\U0001d434(\U0001d463\U0001d456",
                  "−\U0001d463\U0001d45c)"]
        words = ([_w("so", x0=0)]
                 + [_w(g, x0=10 + 5 * i) for i, g in enumerate(glyphs)]
                 + [_w("rearranged", x0=90)])
        placed = align(tokens, words, [])
        self.assertIsNotNone(placed[1].box,
                             "a display equation must carry its own extent")
        self.assertEqual(placed[1].box, (10.0, 10.0, 53.0, 20.0))

    def test_a_long_run_of_prose_is_still_left_unplaced(self):
        """Only maths absorbs a long run. A word token doing so would take a
        box spanning the page while counting as placed."""
        tokens = [Token("word", "alpha"), Token("word", "ghost"),
                  Token("word", "omega")]
        words = ([_w("alpha", x0=0)]
                 + [_w(f"x{i}", x0=10 + i) for i in range(20)]
                 + [_w("omega", x0=90)])
        placed = align(tokens, words, [])
        self.assertIsNone(placed[1].box)

    def test_an_equation_broken_over_a_page_stays_on_one_page(self):
        """A box joined across a page break describes nowhere at all."""
        tokens = [Token("word", "so"),
                  Token("math", latex=r"\begin{aligned} a &= b \\ &= c"
                                      r"\end{aligned}", display=True),
                  Token("word", "then")]
        words = [_w("so", x0=0),
                 _w("\U0001d44e=", page=0, x0=10),
                 _w("\U0001d44f=", page=0, x0=20),
                 _w("\U0001d450", page=1, x0=5),
                 _w("then", page=1, x0=30)]
        placed = align(tokens, words, [])
        self.assertEqual(placed[1].page, 0)
        self.assertEqual(placed[1].box, (10.0, 10.0, 28.0, 20.0))


class LoneEquationInABlockTests(SimpleTestCase):
    """An equation grouped with a neighbour still gets its extent.

    0.73.0 widened the local-replace hatch for a block that is ONE display-math
    token. But an equation is often grouped with a stray neighbour — a word the
    page renders differently, an inline symbol — and 13 clozed equations in the
    electronics primer fell outside by exactly that margin. Each showed a blank
    with no prompt under it, which is what a reader reported.
    """

    def _run(self, tokens, page_words):
        return align(tokens, page_words, [])

    def test_an_equation_beside_a_stray_token_is_still_placed(self):
        tokens = [Token("word", "so"),
                  Token("word", "ghost"),            # the stray neighbour
                  Token("math", latex=r"\begin{aligned} R &= b \\ &= c"
                                      r"\end{aligned}", display=True),
                  Token("word", "then")]
        words = ([_w("so", x0=0)]
                 + [_w(f"\U0001d445{i}=", x0=10 + i) for i in range(8)]
                 + [_w("then", x0=90)])
        placed = self._run(tokens, words)
        self.assertIsNotNone(placed[2].box, "the equation must carry its extent")

    def test_only_the_equation_takes_the_box(self):
        """Not every token in the block: that is what the cap exists to stop."""
        tokens = [Token("word", "so"), Token("word", "ghost"),
                  Token("math", latex=r"\begin{aligned} a &= b \end{aligned}",
                        display=True),
                  Token("word", "then")]
        words = ([_w("so", x0=0)]
                 + [_w(f"\U0001d44e{i}=", x0=10 + i) for i in range(8)]
                 + [_w("then", x0=90)])
        placed = self._run(tokens, words)
        self.assertIsNone(placed[1].box, "the stray must stay unplaced")

    def test_two_equations_in_one_block_are_left_alone(self):
        """Which of them the run belongs to is not knowable, and a box on the
        wrong equation is worse than none."""
        tokens = [Token("word", "so"),
                  Token("math", latex=r"\begin{aligned} a &= b\end{aligned}",
                        display=True),
                  Token("math", latex=r"\begin{aligned} c &= d\end{aligned}",
                        display=True),
                  Token("word", "then")]
        words = ([_w("so", x0=0)]
                 + [_w(f"\U0001d44e{i}=", x0=10 + i) for i in range(20)]
                 + [_w("then", x0=90)])
        placed = self._run(tokens, words)
        self.assertIsNone(placed[1].box)
        self.assertIsNone(placed[2].box)

    def test_prose_alone_is_still_left_unplaced(self):
        tokens = [Token("word", "alpha"), Token("word", "ghost"),
                  Token("word", "omega")]
        words = ([_w("alpha", x0=0)]
                 + [_w(f"x{i}", x0=10 + i) for i in range(20)]
                 + [_w("omega", x0=90)])
        placed = self._run(tokens, words)
        self.assertIsNone(placed[1].box)

    def test_an_equation_is_not_placed_over_plain_prose(self):
        """The run has to look like typeset maths. Otherwise an equation whose
        glyphs are not on this page takes a box over whatever lies between its
        neighbours — placed, and pointing at nothing."""
        tokens = [Token("word", "so"),
                  Token("math", latex=r"\begin{aligned} a &= b\end{aligned}",
                        display=True),
                  Token("word", "then")]
        words = ([_w("so", x0=0)]
                 + [_w(w, x0=10 + i * 9) for i, w in
                    enumerate("nothing resembling that text at all".split())]
                 + [_w("then", x0=90)])
        placed = self._run(tokens, words)
        self.assertIsNone(placed[1].box)

    def test_maths_glyphs_are_what_make_it_maths(self):
        tokens = [Token("word", "so"),
                  Token("math", latex=r"\begin{aligned} a &= b\end{aligned}",
                        display=True),
                  Token("word", "then")]
        words = [_w("so", x0=0),
                 _w("\U0001d44e=", x0=10), _w("\U0001d44f", x0=20),
                 _w("−\U0001d450", x0=30), _w("=", x0=40),
                 _w("⇒", x0=50), _w("\U0001d451", x0=60),
                 _w("then", x0=90)]
        placed = self._run(tokens, words)
        self.assertIsNotNone(placed[1].box)
