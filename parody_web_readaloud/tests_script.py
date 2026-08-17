"""Reading a `--clozes key` artifact into an ordered script."""
from django.test import SimpleTestCase

from parody_web_readaloud.script import parse_script


class ParseScriptTests(SimpleTestCase):
    def test_plain_prose_becomes_word_tokens(self):
        tokens = parse_script("<p>The plant is sampled.</p>")
        self.assertEqual([t.kind for t in tokens], ["word"] * 4)
        self.assertEqual([t.text for t in tokens],
                         ["The", "plant", "is", "sampled."])

    def test_inline_math_is_one_token_carrying_its_latex(self):
        html = '<p>the function <span class="math inline">\\(p(t)\\)</span> is</p>'
        tokens = parse_script(html)
        self.assertEqual([t.kind for t in tokens],
                         ["word", "word", "math", "word"])
        self.assertEqual(tokens[2].latex, "p(t)")
        self.assertFalse(tokens[2].display)

    def test_display_math_is_flagged(self):
        html = '<p><span class="math display">\\[X(f) = 1\\]</span></p>'
        tokens = parse_script(html)
        self.assertEqual(tokens[0].kind, "math")
        self.assertTrue(tokens[0].display)
        self.assertEqual(tokens[0].latex, "X(f) = 1")

    def test_cloze_key_span_becomes_a_cloze_token_with_its_words(self):
        html = ('<p>at a fixed <span class="cloze-key">sampling rate</span>'
                ', which</p>')
        tokens = parse_script(html)
        self.assertEqual([t.kind for t in tokens],
                         ["word", "word", "word", "cloze", "word"])
        self.assertEqual(tokens[3].answer, ["sampling", "rate"])

    def test_figure_with_a_cloze_sibling_becomes_a_figure_cloze(self):
        html = '<figure><img src="media/bode.svg" data-cloze-of="1"></figure>'
        tokens = parse_script(html)
        self.assertEqual([t.kind for t in tokens], ["figure_cloze"])
        self.assertEqual(tokens[0].src, "media/bode.svg")

    def test_an_ordinary_figure_is_not_a_cloze(self):
        html = '<figure><img src="media/plain.svg"></figure>'
        self.assertEqual(parse_script(html), [])

    def test_script_ignores_captions_and_scripts(self):
        html = ('<p>read this</p><figcaption>Figure 1: not read</figcaption>'
                '<script>var x = 1;</script>')
        self.assertEqual([t.text for t in parse_script(html)],
                         ["read", "this"])

    def test_punctuation_hugging_a_cloze_attaches_to_it(self):
        """The PDF glues punctuation to the word before it, so the script must.

        A standalone "," would have no counterpart on the page to align
        against, and its alignment key is the empty string, which matches
        anything.
        """
        html = '<p>a <span class="cloze-key">rate</span>, which</p>'
        tokens = parse_script(html)
        self.assertEqual([t.kind for t in tokens], ["word", "cloze", "word"])
        self.assertEqual(tokens[1].trail, ",")

    def test_a_spaced_symbol_stays_its_own_word(self):
        tokens = parse_script("<p>rate &amp; aliasing</p>")
        self.assertEqual([t.text for t in tokens], ["rate", "&", "aliasing"])
        self.assertEqual(tokens[0].trail, "")

    def test_entities_are_resolved_before_splitting(self):
        tokens = parse_script("<p>Nyquist&nbsp;rate &amp; aliasing</p>")
        self.assertEqual([t.text for t in tokens],
                         ["Nyquist", "rate", "&", "aliasing"])


class BlockClozeTests(SimpleTestCase):
    """`::: {.cloze}` blocks — the only kind the electronics primer uses."""

    def test_a_block_of_display_maths_is_one_cloze_carrying_its_latex(self):
        html = ('<p>we get</p><div class="cloze-key-block"><p>'
                '<span class="math display">\\[Z_C = 1/(j\\omega C)\\]</span>'
                '</p></div><p>after</p>')
        tokens = parse_script(html)
        self.assertEqual([t.kind for t in tokens],
                         ["word", "word", "cloze", "word"])
        self.assertEqual(tokens[2].latex, "Z_C = 1/(j\\omega C)")
        self.assertTrue(tokens[2].display)
        self.assertEqual(tokens[2].answer, [])

    def test_a_block_of_prose_yields_words_not_latex(self):
        html = ('<div class="cloze-key-block"><p>the sampling rate</p></div>')
        tokens = parse_script(html)
        self.assertEqual([t.kind for t in tokens], ["cloze"])
        self.assertEqual(tokens[0].answer, ["the", "sampling", "rate"])
        self.assertEqual(tokens[0].latex, "")

    def test_nested_divs_inside_a_block_do_not_end_it_early(self):
        html = ('<div class="cloze-key-block"><div><p>'
                '<span class="math display">\\[x\\]</span></p></div></div>'
                '<p>after</p>')
        tokens = parse_script(html)
        self.assertEqual([t.kind for t in tokens], ["cloze", "word"])
        self.assertEqual(tokens[0].latex, "x")

    def test_the_maths_inside_a_block_is_not_also_its_own_token(self):
        html = ('<div class="cloze-key-block"><p>'
                '<span class="math display">\\[x\\]</span></p></div>')
        self.assertEqual([t.kind for t in parse_script(html)], ["cloze"])
