"""Compositing ink into the PDF: geometry, colour, and not touching what it need not."""
import tempfile
from pathlib import Path

from django.test import TestCase

from parody_web_annotate import export


class SvgPathToPdfOpsTests(TestCase):
    def test_a_moveto_and_lineto_flip_y_once(self):
        ops = export.svg_path_to_pdf_ops("M0 10 L0 20", page_height=100)
        self.assertIn("0 90 m", ops)
        self.assertIn("0 80 l", ops)

    def test_a_quadratic_becomes_a_cubic(self):
        """PDF has no quadratic operator."""
        ops = export.svg_path_to_pdf_ops("M0 0 Q10 0 10 10", page_height=100)
        self.assertTrue(ops.endswith("c"))
        self.assertNotIn("Q", ops)

    def test_the_cubic_is_the_exact_equivalent_of_the_quadratic(self):
        # Q with control (30,0) from (0,0) to (30,30) at height 0 for clarity:
        # C1 = P0 + 2/3 (Q - P0) = (20, 0);  C2 = P1 + 2/3 (Q - P1) = (30, 10)
        ops = export.svg_path_to_pdf_ops("M0 0 Q30 0 30 30", page_height=0)
        self.assertIn("20 0 30 -10 30 -30 c", ops)

    def test_close_becomes_h(self):
        self.assertIn("h", export.svg_path_to_pdf_ops("M0 0 L1 1 Z", page_height=10))

    def test_an_empty_path_yields_nothing(self):
        self.assertEqual(export.svg_path_to_pdf_ops("", page_height=10), "")

    def test_extra_pairs_after_a_moveto_are_linetos(self):
        ops = export.svg_path_to_pdf_ops("M0 0 1 1 2 2", page_height=0)
        self.assertEqual(ops.count(" m"), 1)
        self.assertEqual(ops.count(" l"), 2)


class ColourTests(TestCase):
    def test_six_digit_hex(self):
        self.assertEqual(export._rgb("#ff0000"), (1.0, 0.0, 0.0))

    def test_three_digit_hex_expands(self):
        self.assertEqual(export._rgb("#f00"), (1.0, 0.0, 0.0))

    def test_nonsense_draws_black_rather_than_vanishing(self):
        """A visible mark in the wrong colour beats a silently missing one."""
        self.assertEqual(export._rgb("rebeccapurple"), (0.0, 0.0, 0.0))
        self.assertEqual(export._rgb(None), (0.0, 0.0, 0.0))


class PageContentTests(TestCase):
    def test_a_stroke_is_filled_and_isolated(self):
        content = export.page_content(
            [{"d": "M0 0 L1 1 Z", "color": "#ff0000", "opacity": 1}], 100)
        self.assertTrue(content.startswith("q"))
        self.assertTrue(content.endswith("Q"))
        self.assertIn("1 0 0 rg", content)
        self.assertIn(" f", content)

    def test_translucency_selects_a_graphics_state(self):
        content = export.page_content(
            [{"d": "M0 0 L1 1 Z", "color": "#ff0", "opacity": 0.4}], 100)
        self.assertIn("/PdA40 gs", content)

    def test_an_opaque_stroke_sets_no_graphics_state(self):
        content = export.page_content(
            [{"d": "M0 0 L1 1 Z", "color": "#000", "opacity": 1}], 100)
        self.assertNotIn(" gs", content)

    def test_a_stroke_with_no_geometry_is_skipped(self):
        self.assertEqual(export.page_content([{"color": "#000"}], 100), "")


class CompositeTests(TestCase):
    def setUp(self):
        from parody_web.tests_printing import make_pdf_with_content
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.src = make_pdf_with_content(self.dir / "src.pdf", 3)
        self.out = self.dir / "out.pdf"
        self.stroke = {"d": "M10 10 L50 50 Z", "color": "#123456", "opacity": 1}

    def _page_bytes(self, path, index):
        from pypdf import PdfReader
        return PdfReader(str(path)).pages[index].get_contents().get_data()

    def test_the_page_count_is_unchanged(self):
        from pypdf import PdfReader
        export.composite(self.src, {"1": [self.stroke]}, self.out)
        self.assertEqual(len(PdfReader(str(self.out)).pages), 3)

    def test_the_ink_lands_on_the_named_page(self):
        export.composite(self.src, {"2": [self.stroke]}, self.out)
        self.assertIn(b" f", self._page_bytes(self.out, 1))
        self.assertIn(b"0.0706 0.2039 0.3373 rg", self._page_bytes(self.out, 1))

    def test_the_original_drawing_survives_underneath(self):
        before = self._page_bytes(self.src, 0)
        export.composite(self.src, {"1": [self.stroke]}, self.out)
        self.assertIn(before.strip(), self._page_bytes(self.out, 0))

    def test_a_page_with_no_ink_is_left_alone(self):
        export.composite(self.src, {"2": [self.stroke]}, self.out)
        self.assertEqual(self._page_bytes(self.src, 0),
                         self._page_bytes(self.out, 0))

    def test_no_ink_at_all_still_produces_a_readable_pdf(self):
        from pypdf import PdfReader
        export.composite(self.src, {}, self.out)
        self.assertEqual(len(PdfReader(str(self.out)).pages), 3)

    def test_a_translucent_stroke_registers_its_graphics_state(self):
        export.composite(
            self.src, {"1": [{**self.stroke, "opacity": 0.4}]}, self.out)
        from pypdf import PdfReader
        page = PdfReader(str(self.out)).pages[0]
        gs = page["/Resources"]["/ExtGState"]
        self.assertIn("/PdA40", gs)
        self.assertAlmostEqual(float(gs["/PdA40"]["/ca"]), 0.4)


class StrokedShapeTests(TestCase):
    """Shape tools are stroked paths with a width, not filled outlines."""

    def test_a_shape_is_stroked_not_filled(self):
        content = export.page_content(
            [{"d": "M0 0 L10 10", "color": "#0000ff", "opacity": 1,
              "mode": "stroke", "width": 2}], 100)
        self.assertIn("0 0 1 RG", content)
        self.assertIn("2 w", content)
        self.assertTrue(content.rstrip("Q ").endswith("S"))
        self.assertNotIn(" rg", content)

    def test_a_shape_gets_round_caps_like_it_had_on_screen(self):
        content = export.page_content(
            [{"d": "M0 0 L10 10", "color": "#000", "mode": "stroke",
              "width": 2}], 100)
        self.assertIn("1 J 1 j", content)

    def test_a_pen_stroke_is_still_filled(self):
        content = export.page_content(
            [{"d": "M0 0 L1 1 Z", "color": "#000", "opacity": 1}], 100)
        self.assertIn(" rg", content)
        self.assertNotIn(" RG", content)
        self.assertIn(" f", content)

    def test_a_missing_width_does_not_produce_an_invisible_hairline(self):
        content = export.page_content(
            [{"d": "M0 0 L1 1", "color": "#000", "mode": "stroke"}], 100)
        self.assertIn("1 w", content)


class DownloadIsAlwaysLightTests(TestCase):
    """Dark mode is a display decision and must never reach a file.

    A reader who studies in dark mode and then prints the section wants black
    ink on white paper, not the inverse — and the ink they stored is what they
    chose, not what it was painted as on screen.
    """

    def setUp(self):
        from parody_web.tests_printing import make_pdf_with_content
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.src = make_pdf_with_content(self.dir / "src.pdf", 2)
        self.out = self.dir / "out.pdf"

    def _content(self, path, index=0):
        from pypdf import PdfReader
        return PdfReader(str(path)).pages[index].get_contents().get_data()

    def test_black_ink_composites_as_black(self):
        """On screen this stroke is drawn light so it is visible on dark
        paper; on paper it must be the black the reader picked."""
        export.composite(self.src, {"1": [{"d": "M0 0 L9 9 Z", "color": "#000000",
                                           "opacity": 1}]}, self.out)
        self.assertIn(b"0 0 0 rg", self._content(self.out))

    def test_the_source_page_is_not_inverted(self):
        """The book's own drawing goes through untouched — no filter, no
        remapped colours."""
        before = self._content(self.src)
        export.composite(self.src, {"1": [{"d": "M0 0 L9 9 Z", "color": "#000000"}]},
                         self.out)
        self.assertIn(before.strip(), self._content(self.out))

    def test_a_chosen_colour_survives_exactly(self):
        export.composite(self.src, {"1": [{"d": "M0 0 L9 9 Z", "color": "#2563eb",
                                           "opacity": 1}]}, self.out)
        # 0x25/255, 0x63/255, 0xeb/255
        self.assertIn(b"0.1451 0.3882 0.9216 rg", self._content(self.out))

    def test_the_exporter_takes_no_theme_argument(self):
        """The guarantee is structural: there is no way to ask for a dark
        export, so no caller can accidentally produce one."""
        import inspect
        for fn in (export.composite, export.page_content, export.svg_path_to_pdf_ops):
            names = set(inspect.signature(fn).parameters)
            self.assertFalse({"dark", "theme", "invert"} & names,
                             f"{fn.__name__} grew a theme parameter")
