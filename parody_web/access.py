"""Pluggable access control.

parody-web's own gating is commercial publishing: an owner (the authenticated
account) sees everything, the public sees the full text of the freely-licensed
sections and a teaser for the in-print ones. A host project serving the same
book to a class needs a different question answered — "may *this* student see
the solution to *this* exercise *yet*" — which depends on enrollment,
assignments, and due dates that parody-web has no business knowing about.

So the rules live behind one object, and a deployment names a replacement:

    PARODY_WEB_ACCESS_POLICY = "courses.policy.CoursePolicy"

Subclass `DefaultPolicy` and override only the hooks you care about; anything
you leave alone keeps parody-web's own behaviour. The setting is validated at
startup (see apps.py) so a typo'd path fails on boot rather than at first
render — the same posture as PARODY_WEB_THEME.

Every hook takes the *request*, not the user: `request.user` is always
reachable from a request and the reverse is not. `request` may be None on
helper paths that have none, so every hook tolerates it.

See docs/host-integration.md for the full contract.
"""

from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string


class DefaultPolicy:
    """parody-web's own rules — the gating that used to be inlined in views."""

    def is_owner(self, request):
        """The book's owner: the only account a public book site has."""
        return bool(request and request.user.is_authenticated)

    def can_view_section(self, request, section):
        """Hard gate: may this reader have the section page at all?

        parody-web never refuses one — the table of contents and the prose are
        public, and restricted sections are *teased* rather than hidden (see
        `section_is_preview`). A host with genuinely restricted material (a
        notebook only enrolled students may open) overrides this.
        """
        return True

    def section_is_preview(self, request, section):
        """Soft gate: show a truncated excerpt and a sign-in call to action.

        This is `Section.preview` — in print, but not fully online.
        """
        return bool(section.preview) and not self.is_owner(request)

    def can_view_solution(self, request, section, exercise_id):
        """May this reader read the worked solution to one exercise?"""
        return self.is_owner(request)

    def solution_denied_context(self, request, section, exercise_id):
        """Extra template context for the refusal page.

        `available_after` is what a course site fills in with the assignment's
        due date, so the page can say when the solution opens; None means
        "no date to offer", which is all parody-web itself can say.
        """
        return {
            "available_after": None,
            "message": "Solutions are available to the book's owner.",
        }

    def can_download_section_pdf(self, request, section):
        """May this reader download this section's print PDF?

        Defaults to exactly what the page itself shows: a preview section's PDF
        is owner-only, because the page is. This matters more than it looks —
        the print PDF holds the FULL text of a section the online-only artifact
        deliberately withholds, so a laxer default here would quietly undo the
        gating the artifact was built to enforce.
        """
        if not self.can_view_section(request, section):
            return False
        return not self.section_is_preview(request, section)

    def can_download_book_pdf(self, request, book):
        """May this reader download the whole book as one PDF?

        Public by default. A site whose book is not wholly public sets
        PARODY_WEB_PUBLIC_BOOK_PDF = False, leaving it to the owner. Note the
        direction of that default: a gated book that forgets the setting serves
        its full text, so printing.public_book_pdf_warnings() calls it out at
        startup.
        """
        from django.conf import settings

        if self.is_owner(request):
            return True
        return bool(getattr(settings, "PARODY_WEB_PUBLIC_BOOK_PDF", True))


def validate_policy(path):
    """Raise ImproperlyConfigured unless `path` names an importable class."""
    if not path:
        return
    if not isinstance(path, str):
        raise ImproperlyConfigured(
            f"PARODY_WEB_ACCESS_POLICY must be a dotted path string, "
            f"got {type(path).__name__}")
    try:
        policy = import_string(path)
    except ImportError as e:
        raise ImproperlyConfigured(
            f"PARODY_WEB_ACCESS_POLICY: could not import {path!r}: {e}")
    if not isinstance(policy, type):
        raise ImproperlyConfigured(
            f"PARODY_WEB_ACCESS_POLICY: {path!r} is not a class")


def get_policy():
    """The configured access policy instance (DefaultPolicy when unset).

    Resolved per call rather than cached at import: override_settings has to
    take effect in tests, and instantiating a policy is cheap.
    """
    from django.conf import settings

    path = getattr(settings, "PARODY_WEB_ACCESS_POLICY", "")
    if not path:
        return DefaultPolicy()
    validate_policy(path)
    return import_string(path)()
