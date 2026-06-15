"""Template tags that render parody's Django-template-flavored section html.

The artifact's ``html`` embeds ``{% media %}``, ``{% static %}``, ``{% cite %}``
etc. — the same tags ricopic.one resolves at view time. We resolve them here so
the book-host renders the stored html natively (no lossy regex re-resolution).

The ``render_book`` filter compiles a stored html blob as a Django template
with this library loaded and renders it; ``{% csrf_token %}`` is stripped first
(server-form-only, and it collides with the builtin), and a malformed tag
degrades to escaped output rather than 500-ing the page.
"""
import re

from django import template
from django.conf import settings
from django.template import Context, Template, TemplateSyntaxError
from django.utils.html import conditional_escape
from django.utils.safestring import mark_safe

register = template.Library()


@register.simple_tag
def media(path):
    return settings.MEDIA_URL + str(path).lstrip("/")


@register.simple_tag
def static(path):
    return settings.STATIC_URL + str(path).lstrip("/")


def _cite(key):
    return mark_safe(f'<span class="citation">[{conditional_escape(key)}]</span>')


@register.simple_tag
def cite(key, *args, **kwargs):
    return _cite(key)


@register.simple_tag
def cite_many(*keys, **kwargs):
    return mark_safe("; ".join(_cite(k) for k in keys))


@register.simple_tag
def url(*args, **kwargs):
    # server-side routes don't exist on the standalone book site
    return "#"


@register.simple_tag
def get_cell(*args, **kwargs):
    return mark_safe(
        '<span class="get-cell-placeholder" '
        'title="interactive table cell (site-only feature)">—</span>'
    )


@register.simple_tag
def auth_button(*args, href="", label="Download", **kwargs):
    return mark_safe(
        f'<a class="download-button" href="{media(href)}">'
        f"{conditional_escape(label)}</a>"
    )


_CSRF_RE = re.compile(r"\{%\s*csrf_token\s*%\}")


@register.filter(is_safe=True)
def render_book(html):
    """Render stored Django-flavored html (defaults to '' for empty fields)."""
    if not html:
        return ""
    source = "{% load parody_web %}" + _CSRF_RE.sub("", html)
    try:
        return mark_safe(Template(source).render(Context({})))
    except TemplateSyntaxError as exc:
        # Don't take the page down over one unexpected tag; surface in a comment.
        return mark_safe(
            f"<!-- book-host: unresolved template content: "
            f"{conditional_escape(str(exc))} -->" + html
        )
