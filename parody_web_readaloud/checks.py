"""Boot-time checks.

parody-web's posture throughout: a misconfiguration should fail on boot, not at
the first reader's request.
"""

from django.core.checks import Error, register


@register()
def readaloud_app_order(app_configs, **kwargs):
    """Read-along must win the PDF-view head template — over BOTH other apps.

    It shadows `parody_web/_pdf_view_head.html`, which parody_web_annotate also
    defines, and Django resolves app templates in INSTALLED_APPS order: first
    match wins. Listed after either app, read-along's stylesheet and script are
    simply never emitted, the mode never appears, and nothing says why.

    Checking only against parody_web is not enough, and that gap shipped: on
    electronics.ricopic.one read-along was installed, its endpoints served
    tracks, and no client code loaded on any page, because the annotator was
    listed first.
    """
    from django.conf import settings

    apps = list(getattr(settings, "INSTALLED_APPS", []))
    if "parody_web_readaloud" not in apps:
        return []
    mine = apps.index("parody_web_readaloud")

    errors = []
    for other, code in (("parody_web", "E001"),
                        ("parody_web_annotate", "E002")):
        if other not in apps:
            continue
        if mine > apps.index(other):
            errors.append(Error(
                f"parody_web_readaloud must come before {other} in "
                "INSTALLED_APPS.",
                hint="Both define parody_web/_pdf_view_head.html, and Django "
                     "resolves app templates in INSTALLED_APPS order. Listed "
                     "after, read-along loads but never appears — its "
                     "stylesheet and script are never emitted.",
                id=f"parody_web_readaloud.{code}",
            ))
    return errors


@register()
def readaloud_s3_usable(app_configs, **kwargs):
    """A configured bucket that cannot be reached is a boot failure.

    Serving from S3 needs boto3 — to mint the presigned URL the audio endpoint
    redirects to. That is a real change of footing: until now boto3 was a
    GENERATION-time dependency (Polly), and a host that only served tracks
    needed neither it nor PyMuPDF. Without this check the deployment boots, the
    reader presses play, and the endpoint 500s.
    """
    from django.conf import settings

    apps = list(getattr(settings, "INSTALLED_APPS", []))
    if "parody_web_readaloud" not in apps:
        return []
    if not (getattr(settings, "PARODY_WEB_READALOUD_BUCKET", "") or ""):
        return []
    try:
        import boto3  # noqa: F401
    except ImportError:
        return [Error(
            "PARODY_WEB_READALOUD_BUCKET is set but boto3 is not installed.",
            hint="Serving read-along audio from S3 mints a presigned URL per "
                 "request, which needs boto3. Install parody-web with the "
                 "readalong extra: pip install 'parody-web[readalong]'.",
            id="parody_web_readaloud.E003",
        )]
    return []
