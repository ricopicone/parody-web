"""Boot-time checks.

parody-web's posture throughout: a misconfiguration should fail on boot, not
at the first reader's request.
"""

from django.core.checks import Error, register


@register()
def annotate_app_order(app_configs, **kwargs):
    """The annotator's templates must win over parody_web's.

    Template shadowing between apps is decided by INSTALLED_APPS order, and
    getting it wrong fails *silently*: the PDF view keeps rendering the plain
    iframe and nothing anywhere says why. Cheaper to refuse to boot.
    """
    from django.conf import settings

    apps = list(getattr(settings, "INSTALLED_APPS", []))
    try:
        mine = apps.index("parody_web_annotate")
        core = apps.index("parody_web")
    except ValueError:
        return []
    if mine > core:
        return [Error(
            "parody_web_annotate must come before parody_web in INSTALLED_APPS.",
            hint="It shadows parody_web's PDF-view templates, and Django "
                 "resolves app templates in INSTALLED_APPS order. Listed "
                 "after, the annotator loads but never appears.",
            id="parody_web_annotate.E001",
        )]
    return []
