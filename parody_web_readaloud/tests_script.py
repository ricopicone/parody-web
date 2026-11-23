"""Reading a `--clozes key` artifact into an ordered script."""
from django.test import SimpleTestCase

from parody_web_readaloud.script import parse_script, unspoken_words


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


class InEquationClozeTests(SimpleTestCase):
    """The author clozes PART of an equation, not the whole of it.

    Key mode marks the answer inside the maths, so the blank never becomes a
    cloze token of its own. Before this was read, 171 blanks in the electronics
    primer were spoken but never shown (task #660).
    """

    def test_a_marked_equation_counts_its_blanks(self):
        html = (r'<p><span class="math display">\['
                r'\begin{aligned} Z = \class{cloze-key}{\frac{v} {i}}.'
                r'\end{aligned}\]</span></p>')
        maths = [t for t in parse_script(html) if t.kind == "math"]
        self.assertEqual(len(maths), 1)
        self.assertEqual(maths[0].blanks, 1)

    def test_the_plain_form_is_the_whole_equation(self):
        from parody_web_readaloud.script import strip_cloze_markers
        plain, n = strip_cloze_markers(
            r"\begin{aligned} Z = \class{cloze-key}{\frac{v} {i}}.\end{aligned}")
        self.assertEqual(n, 1)
        self.assertEqual(
            plain, r"\begin{aligned} Z = \frac{v} {i}.\end{aligned}")

    def test_braces_are_matched_not_guessed(self):
        """A non-greedy regex ends at the first brace and keeps half an
        equation; the thing being hidden is maths, so it is full of braces."""
        from parody_web_readaloud.script import strip_cloze_markers
        plain, n = strip_cloze_markers(
            r"a = \class{cloze-key}{\frac{1} {j\omega C}} + b")
        self.assertEqual(n, 1)
        self.assertEqual(plain, r"a = \frac{1} {j\omega C} + b")

    def test_several_blanks_in_one_equation(self):
        from parody_web_readaloud.script import strip_cloze_markers
        plain, n = strip_cloze_markers(
            r"\class{cloze-key}{x} = \class{cloze-key}{y}")
        self.assertEqual((plain, n), ("x = y", 2))

    def test_an_unmarked_equation_is_untouched(self):
        html = (r'<p><span class="math display">\[a = b\]</span></p>')
        maths = [t for t in parse_script(html) if t.kind == "math"]
        self.assertEqual(maths[0].blanks, 0)
        self.assertEqual(maths[0].plain, "")
        self.assertEqual(maths[0].latex, "a = b")

    def test_an_unbalanced_marker_is_left_alone(self):
        from parody_web_readaloud.script import strip_cloze_markers
        raw = r"a = \class{cloze-key}{oops"
        self.assertEqual(strip_cloze_markers(raw), (raw, 0))


class ClozeHidingMathsTests(SimpleTestCase):
    """An inline cloze whose answer is maths — `\\cloze{$V_e$}`.

    Opening a math span used to reset the buffer, so the cloze token came out
    EMPTY: nothing to reveal, and nothing spoken either, because the answer is
    also what is read aloud. The maths meanwhile became a token of its own,
    which the page never prints and so could never align. 25 blanks in the
    electronics primer reached readers that way (reported by a student).
    """

    def _clozes(self, html):
        return [t for t in parse_script(html) if t.kind == "cloze"]

    def test_an_all_maths_answer_survives(self):
        html = ('<p>use <span class="cloze-key">'
                r'<span class="math inline">\(V_e\)</span></span> here</p>')
        clozes = self._clozes(html)
        self.assertEqual(len(clozes), 1)
        self.assertEqual(clozes[0].latex, "V_e")

    def test_the_maths_is_not_also_a_token_of_its_own(self):
        """It is behind the blank; the page never prints it."""
        html = ('<p>use <span class="cloze-key">'
                r'<span class="math inline">\(V_e\)</span></span> here</p>')
        self.assertEqual([t for t in parse_script(html) if t.kind == "math"], [])

    def test_prose_before_the_maths_is_kept(self):
        html = ('<p>the <span class="cloze-key">voltage source '
                r'<span class="math inline">\(V_e\)</span></span> drops</p>')
        cloze = self._clozes(html)[0]
        self.assertIn(r"\text{voltage source}", cloze.latex)
        self.assertIn("V_e", cloze.latex)
        self.assertIn("voltage source", cloze.text)

    def test_prose_after_the_maths_is_kept_too(self):
        html = ('<p>at <span class="cloze-key">'
                r'<span class="math inline">\(10\)</span> volts</span> now</p>')
        cloze = self._clozes(html)[0]
        self.assertIn(r"\text{volts}", cloze.latex)
        self.assertIn("10", cloze.latex)

    def test_a_purely_verbal_answer_is_untouched(self):
        html = ('<p>the <span class="cloze-key">sampling rate</span> sets</p>')
        cloze = self._clozes(html)[0]
        self.assertEqual(cloze.answer, ["sampling", "rate"])
        self.assertEqual(cloze.latex, "")

    def test_tex_specials_in_the_prose_are_escaped(self):
        html = ('<p><span class="cloze-key">50% of '
                r'<span class="math inline">\(x\)</span></span> so</p>')
        cloze = self._clozes(html)[0]
        self.assertIn(r"\%", cloze.latex)


class CodeTests(SimpleTestCase):
    """A program, or what it printed, read out symbol by symbol helps nobody
    listening; the prose around a listing says what it does. A listing is
    skipped, and the sentence before it ends there, so the voice pauses where
    the code sits instead of running on into the next paragraph."""

    PROGRAM = ('<div class="sourceCode"><pre class="sourceCode python">'
               '<code class="sourceCode python">'
               '<span class="kw">def</span> f(x):\n    <span class="cf">return</span> x'
               '</code></pre></div>')

    def test_a_code_block_is_not_read(self):
        tokens = parse_script("<p>In code:</p>" + self.PROGRAM + "<p>It returns x.</p>")
        self.assertEqual([t.text for t in tokens], ["In", "code:", "It", "returns", "x."])

    def test_printed_output_is_not_read_either(self):
        tokens = parse_script("<p>It prints</p><pre><code>8 distinct solutions\n"
                              "(12.5, -56.3)</code></pre><p>and stops.</p>")
        self.assertEqual([t.text for t in tokens], ["It", "prints", "and", "stops."])

    def test_the_sentence_before_a_listing_ends_there(self):
        tokens = parse_script("<p>In code:</p>" + self.PROGRAM + "<p>Next.</p>")
        self.assertEqual(tokens[1].trail, ".")

    def test_a_sentence_already_ended_is_left_alone(self):
        tokens = parse_script("<p>The program runs.</p>" + self.PROGRAM)
        self.assertEqual(tokens[-1].text, "runs.")
        self.assertEqual(tokens[-1].trail, "")

    def test_inline_code_in_a_sentence_is_still_read(self):
        tokens = parse_script("<p>call <code>robot.ik</code> once</p>")
        self.assertEqual([t.text for t in tokens], ["call", "robot.ik", "once"])


class FootnoteTests(SimpleTestCase):
    """Footnotes are not read. Pandoc gathers every footnote's body at the END
    of the section, so the voice read them all out after the last paragraph,
    where the page shows none of them to highlight — print sets each one at the
    foot of its own page. The mark in the sentence went too: it was read as a
    bare number, "the self-driving car one and of the latter".

    The markup is pandoc's, exactly as it is in the robotics key artifact."""

    @staticmethod
    def _mark(n):
        return (f'<a href="#fn{n}" class="footnote-ref" id="fnref{n}" '
                f'role="doc-noteref"><sup>{n}</sup></a>')

    @staticmethod
    def _notes(*bodies):
        items = "".join(
            f'<li id="fn{n}"><p>{body}<a href="#fnref{n}" class="footnote-back" '
            f'role="doc-backlink">↩︎</a></p></li>\n'
            for n, body in enumerate(bodies, start=1))
        return ('<section id="footnotes" class="footnotes '
                'footnotes-end-of-document" role="doc-endnotes">\n<hr />\n'
                f'<ol>\n{items}</ol>\n</section>\n')

    def _words(self, html):
        return [t.text + t.trail for t in parse_script(html)]

    def test_the_footnotes_at_the_end_are_not_read(self):
        html = (f"<p>A robot is designed by humans.{self._mark(1)}</p>\n"
                + self._notes("Or, at least, if it was designed by a robot."))
        self.assertEqual(self._words(html),
                         ["A", "robot", "is", "designed", "by", "humans."])

    def test_the_mark_in_the_sentence_is_not_read(self):
        html = f"<p>the self-driving car{self._mark(1)} and the arm.</p>"
        self.assertEqual(self._words(html),
                         ["the", "self-driving", "car", "and", "the", "arm."])

    def test_punctuation_after_a_mark_stays_with_the_word_before_it(self):
        html = f"<p>most motors{self._mark(1)}, of quality</p>"
        self.assertEqual(self._words(html), ["most", "motors,", "of", "quality"])

    def test_nothing_inside_a_footnote_is_read(self):
        # Maths, a figure and a nested section: none of it is a token, not
        # even the figure cloze or the equation, because none of it is spoken.
        body = ('a rover <span class="math inline">\\(v\\)</span> '
                '<img src="rover.svg" data-cloze-of="rover.svg">'
                '<section><p>nested</p></section> and more')
        html = f"<p>a rover.{self._mark(1)}</p>" + self._notes(body)
        self.assertEqual(self._words(html), ["a", "rover."])

    def test_reading_resumes_after_the_footnotes(self):
        html = (f"<p>One.{self._mark(1)}</p>" + self._notes("a note")
                + "<p>Two.</p>")
        self.assertEqual(self._words(html), ["One.", "Two."])

    def test_the_footnotes_words_are_kept_for_the_aligner(self):
        # The page still prints them, at the foot of the page, and a word the
        # prose shares with a footnote must not look unique to the aligner.
        html = (f"<p>loops we exclude.{self._mark(1)}</p>"
                + self._notes("we exclude them here."))
        words = unspoken_words(html)
        self.assertEqual([w for w in words if w.isalpha()],
                         ["we", "exclude", "them"])
        self.assertIn("here.", words)
        self.assertNotIn("loops", words)

    def test_a_tables_words_are_not_on_that_list(self):
        # A table has never been in the script, and the aligner has always
        # been fitted around it; sections without footnotes align as before.
        html = "<p>see</p><table><tr><td>gain</td></tr></table>"
        self.assertEqual(unspoken_words(html), [])
