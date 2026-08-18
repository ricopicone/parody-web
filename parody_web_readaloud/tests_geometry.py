"""Word boxes and blank rules, measured off the served PDF."""
import fitz
from django.test import SimpleTestCase

from parody_web_readaloud.geometry import (extract_blanks, extract_rules,
                                           extract_words,
                                           page_sizes)


def _pdf(draw_rule=False, pages=1):
    doc = fitz.open()
    for _ in range(pages):
        page = doc.new_page(width=200, height=100)
        page.insert_text((10, 20), "alpha beta", fontsize=10)
        if draw_rule:
            page.draw_line(fitz.Point(10, 50), fitz.Point(60, 50), width=0.6)
    out = doc.tobytes()
    doc.close()
    return out


class ExtractWordsTests(SimpleTestCase):
    def test_words_come_back_in_order_with_boxes_and_pages(self):
        words = extract_words(_pdf())
        self.assertEqual([w.text for w in words], ["alpha", "beta"])
        self.assertTrue(all(w.page == 0 for w in words))
        self.assertLess(words[0].x0, words[1].x0)
        self.assertGreater(words[0].y1, words[0].y0)

    def test_pages_are_numbered_from_zero_and_in_order(self):
        words = extract_words(_pdf(pages=2))
        self.assertEqual([w.page for w in words], [0, 0, 1, 1])


class ExtractRulesTests(SimpleTestCase):
    def test_horizontal_rules_are_reported_as_blanks(self):
        rules = extract_rules(_pdf(draw_rule=True))
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]["page"], 0)
        self.assertEqual(round(rules[0]["x1"] - rules[0]["x0"]), 50)

    def test_a_page_with_no_rule_reports_none(self):
        self.assertEqual(extract_rules(_pdf()), [])

    def test_a_tall_box_is_not_a_blank(self):
        """Environment frames and table borders must not read as blanks."""
        doc = fitz.open()
        page = doc.new_page(width=200, height=100)
        page.draw_rect(fitz.Rect(10, 10, 190, 90), width=0.6)
        data = doc.tobytes()
        doc.close()
        self.assertEqual(extract_rules(data), [])

    def test_a_very_short_mark_is_not_a_blank(self):
        doc = fitz.open()
        page = doc.new_page(width=200, height=100)
        page.draw_line(fitz.Point(10, 50), fitz.Point(13, 50), width=0.6)
        data = doc.tobytes()
        doc.close()
        self.assertEqual(extract_rules(data), [])


class PageSizesTests(SimpleTestCase):
    def test_page_sizes_are_reported(self):
        self.assertEqual(page_sizes(_pdf()), [(200.0, 100.0)])


class BlankGroupingTests(SimpleTestCase):
    """A cloze block is blanked to its own height: one blank, several rules."""

    def _blanks(self, lines, width=180.0, gap=18):
        doc = fitz.open()
        page = doc.new_page(width=220, height=600)
        # Text defines the measure a full-width rule is judged against.
        page.insert_text((20, 30), "a b c d e f g h i j k l m n o p q r s t",
                         fontsize=9)
        for n in range(lines):
            y = 60 + n * gap
            page.draw_line(fitz.Point(20, y), fitz.Point(20 + width, y),
                           width=0.4)
        data = doc.tobytes()
        doc.close()
        return extract_blanks(data)

    def test_a_pair_of_full_measure_rules_is_one_blank(self):
        """A framed blank reaches us as its top and bottom rule."""
        blanks = self._blanks(2)
        self.assertEqual(len(blanks), 1)
        self.assertEqual(blanks[0]["lines"], 2)

    def test_two_adjacent_boxes_stay_two_blanks(self):
        """Four rules are two boxes, not one. Grouping them by distance
        swallowed both into a single blank and lost a cloze."""
        blanks = self._blanks(4)
        self.assertEqual(len(blanks), 2)
        self.assertTrue(all(b["lines"] == 2 for b in blanks))

    def test_a_tall_box_is_still_one_blank(self):
        """The rules of one box can be far apart — it is as tall as the passage
        it hides — so distance cannot be what groups them."""
        blanks = self._blanks(2, gap=160)
        self.assertEqual(len(blanks), 1)

    def test_one_rule_is_one_blank(self):
        self.assertEqual(len(self._blanks(1)), 1)

    def test_short_rules_are_never_grouped(self):
        """Two fraction bars on consecutive lines are not one blank."""
        blanks = self._blanks(2, width=20.0)
        self.assertEqual(len(blanks), 2)

    def test_a_short_rule_is_still_offered_as_a_candidate(self):
        """Inline \\clozeblank is measured to its answer, not the full measure."""
        blanks = self._blanks(1, width=20.0)
        self.assertEqual(len(blanks), 1)
        self.assertFalse(blanks[0]["full"])
