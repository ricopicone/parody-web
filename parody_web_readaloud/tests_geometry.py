"""Word boxes and blank rules, measured off the served PDF."""
import fitz
from django.test import SimpleTestCase

from parody_web_readaloud.geometry import (extract_rules, extract_words,
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
