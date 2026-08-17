"""The boot check that stops read-along from loading invisibly."""
from django.test import SimpleTestCase, override_settings

from parody_web_readaloud.checks import readaloud_app_order


class AppOrderCheckTests(SimpleTestCase):
    @override_settings(INSTALLED_APPS=["parody_web", "parody_web_readaloud"])
    def test_listed_after_core_is_an_error(self):
        errors = readaloud_app_order(None)
        self.assertEqual([e.id for e in errors], ["parody_web_readaloud.E001"])

    @override_settings(INSTALLED_APPS=["parody_web_annotate",
                                       "parody_web_readaloud", "parody_web"])
    def test_listed_after_the_annotator_is_an_error(self):
        """Both define _pdf_view_head.html and first match wins.

        This exact order shipped to production: read-along installed, its
        endpoints serving tracks, and not one line of its client code on any
        page.
        """
        errors = readaloud_app_order(None)
        self.assertEqual([e.id for e in errors], ["parody_web_readaloud.E002"])

    @override_settings(INSTALLED_APPS=["parody_web_readaloud",
                                       "parody_web_annotate", "parody_web"])
    def test_first_of_the_three_is_fine(self):
        self.assertEqual(readaloud_app_order(None), [])

    @override_settings(INSTALLED_APPS=["parody_web", "parody_web_annotate",
                                       "parody_web_readaloud"])
    def test_last_of_the_three_reports_both(self):
        errors = readaloud_app_order(None)
        self.assertEqual(sorted(e.id for e in errors),
                         ["parody_web_readaloud.E001",
                          "parody_web_readaloud.E002"])

    @override_settings(INSTALLED_APPS=["parody_web_readaloud", "parody_web"])
    def test_listed_before_core_is_fine(self):
        self.assertEqual(readaloud_app_order(None), [])

    @override_settings(INSTALLED_APPS=["parody_web"])
    def test_absent_is_not_our_problem(self):
        self.assertEqual(readaloud_app_order(None), [])
