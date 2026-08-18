"""Cross-references are spoken as printed, not as their keys."""
from django.test import SimpleTestCase

from parody_web_readaloud.refs import resolve_refs

LABELS = {"eq:foo": "Equation (4.1)", "eq:bar": "Equation (4.2)",
          "fig:baz": "Figure 4.12a"}


class ResolveRefsTests(SimpleTestCase):
    def test_a_citation_span_becomes_the_printed_label(self):
        html = ('<p>such that <span class="citation" data-cites="eq:foo">'
                '[@eq:foo]</span> is true</p>')
        self.assertIn("such that Equation (4.1) is true",
                      resolve_refs(html, LABELS))

    def test_a_hashref_span_becomes_the_printed_label(self):
        html = '<p>see <span class="hashref">fig:baz</span> here</p>'
        self.assertIn("see Figure 4.12a here", resolve_refs(html, LABELS))

    def test_several_cited_keys_are_joined_the_way_they_are_read(self):
        html = ('<span class="citation" data-cites="eq:foo eq:bar">'
                '[@eq:foo; @eq:bar]</span>')
        self.assertEqual(resolve_refs(html, LABELS),
                         "Equation (4.1) and Equation (4.2)")

    def test_an_unknown_key_is_left_exactly_as_authored(self):
        """A missing target costs that reference and nothing around it."""
        html = ('<p>a <span class="citation" data-cites="eq:missing">'
                '[@eq:missing]</span> b</p>')
        self.assertEqual(resolve_refs(html, LABELS), html)

    def test_nothing_else_in_the_html_is_touched(self):
        html = ('<p>keep <em>this</em> and <span class="math inline">'
                '\\(x\\)</span></p>')
        self.assertEqual(resolve_refs(html, LABELS), html)

    def test_no_labels_means_no_rewriting(self):
        html = '<span class="citation" data-cites="eq:foo">[@eq:foo]</span>'
        self.assertEqual(resolve_refs(html, {}), html)
