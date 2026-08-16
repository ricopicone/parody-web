"""The ink layer: identity, isolation, and surviving a re-import."""
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase

from parody_web_annotate.models import InkLayer


class InkLayerModelTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.reader = User.objects.create_user("reader", password="x")
        self.other = User.objects.create_user("other", password="x")
        self.kw = dict(book_slug="print-book", edition_id="", section_key="al",
                       slice_key="a" * 64, book_sha256="b" * 64, pages=[5, 9],
                       strokes={})

    def test_one_layer_per_reader_section_and_version(self):
        InkLayer.objects.create(user=self.reader, **self.kw)
        with self.assertRaises(IntegrityError):
            InkLayer.objects.create(user=self.reader, **self.kw)

    def test_two_versions_of_one_section_coexist(self):
        InkLayer.objects.create(user=self.reader, **self.kw)
        InkLayer.objects.create(user=self.reader, **{**self.kw, "slice_key": "c" * 64})
        self.assertEqual(InkLayer.objects.filter(user=self.reader).count(), 2)

    def test_two_readers_annotate_the_same_version_independently(self):
        InkLayer.objects.create(user=self.reader, **self.kw)
        InkLayer.objects.create(user=self.other, **self.kw)
        self.assertEqual(InkLayer.objects.count(), 2)

    def test_it_carries_everything_needed_to_cut_its_own_pdf(self):
        """Section.print_pages is overwritten every import; this row must not
        depend on it."""
        layer = InkLayer.objects.create(user=self.reader, **self.kw)
        self.assertEqual(layer.book_sha256, "b" * 64)
        self.assertEqual(layer.pages, [5, 9])

    def test_stroke_count_sums_the_pages(self):
        layer = InkLayer.objects.create(
            user=self.reader, **{**self.kw,
                                 "strokes": {"1": [{}, {}], "2": [{}]}})
        self.assertEqual(layer.stroke_count, 3)
