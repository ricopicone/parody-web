"""Boot-time checks.

parody-web's posture throughout: a misconfiguration should fail on boot, not at
the first reader's request.
"""

from django.core.checks import Error, register


@register()
def readaloud_app_order(app_configs, **kwargs):
    """Read-along's templates must win over parody_web's.

    Same failure as parody_web_annotate.E001, and just as silent: listed after
    core, the mode loads but never appears and nothing anywhere says why.
    """
    from django.conf import settings

    apps = list(getattr(settings, "INSTALLED_APPS", []))
    try:
        mine = apps.index("parody_web_readaloud")
        core = apps.index("parody_web")
    except ValueError:
        return []
    if mine > core:
        return [Error(
            "parody_web_readaloud must come before parody_web in INSTALLED_APPS.",
            hint="It shadows parody_web's PDF-view templates, and Django "
                 "resolves app templates in INSTALLED_APPS order. Listed "
                 "after, read-along loads but never appears.",
            id="parody_web_readaloud.E001",
        )]
    return []
