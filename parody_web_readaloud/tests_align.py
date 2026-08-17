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
