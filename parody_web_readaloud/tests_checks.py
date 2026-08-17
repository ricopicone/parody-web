"""The boot check that stops read-along from loading invisibly."""
from django.test import SimpleTestCase, override_settings

from parody_web_readaloud.checks import readaloud_app_order


class AppOrderCheckTests(SimpleTestCase):
    @override_settings(INSTALLED_APPS=["parody_web", "parody_web_readaloud"])
    def test_listed_after_core_is_an_error(self):
        errors = readaloud_app_order(None)
        self.assertEqual([e.id for e in errors], ["parody_web_readaloud.E001"])

    @override_settings(INSTALLED_APPS=["parody_web_readaloud", "parody_web"])
    def test_listed_before_core_is_fine(self):
        self.assertEqual(readaloud_app_order(None), [])

    @override_settings(INSTALLED_APPS=["parody_web"])
    def test_absent_is_not_our_problem(self):
        self.assertEqual(readaloud_app_order(None), [])
