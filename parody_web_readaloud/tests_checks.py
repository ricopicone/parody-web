"""The boot checks: one stops read-along loading invisibly, one stops it
serving audio it cannot sign for."""
import builtins
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from parody_web_readaloud.checks import readaloud_app_order, readaloud_s3_usable


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


class S3UsableCheckTests(SimpleTestCase):
    """Serving from S3 mints a presigned URL per request, so boto3 stops being
    a generation-time dependency and becomes a serving one. Without this the
    site boots, the reader presses play, and the endpoint 500s."""

    APPS = ["parody_web_readaloud", "parody_web"]

    def _without_boto3(self):
        real = builtins.__import__

        def fake(name, *args, **kwargs):
            if name == "boto3":
                raise ImportError("no boto3")
            return real(name, *args, **kwargs)

        return patch.object(builtins, "__import__", fake)

    @override_settings(INSTALLED_APPS=APPS, PARODY_WEB_READALOUD_BUCKET="b")
    def test_a_bucket_without_boto3_is_an_error(self):
        with self._without_boto3():
            errors = readaloud_s3_usable(None)
        self.assertEqual([e.id for e in errors], ["parody_web_readaloud.E003"])

    @override_settings(INSTALLED_APPS=APPS, PARODY_WEB_READALOUD_BUCKET="b")
    def test_a_bucket_with_boto3_is_fine(self):
        self.assertEqual(readaloud_s3_usable(None), [])

    @override_settings(INSTALLED_APPS=APPS, PARODY_WEB_READALOUD_BUCKET="")
    def test_no_bucket_needs_no_boto3(self):
        """Disk is still a supported deployment, and it needs nothing."""
        with self._without_boto3():
            self.assertEqual(readaloud_s3_usable(None), [])

    @override_settings(INSTALLED_APPS=["parody_web"],
                       PARODY_WEB_READALOUD_BUCKET="b")
    def test_absent_is_not_our_problem(self):
        with self._without_boto3():
            self.assertEqual(readaloud_s3_usable(None), [])
