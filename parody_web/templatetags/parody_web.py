"""Template tags that render parody's Django-template-flavored section html.

The artifact's ``html`` embeds ``{% media %}``, ``{% static %}``, ``{% cite %}``
etc. — the same tags ricopic.one resolves at view time. We resolve them here so
the book-host renders the stored html natively (no lossy regex re-resolution).

The ``render_book`` filter compiles a stored html blob as a Django template
with this library loaded and renders it; ``{% csrf_token %}`` is stripped first
(server-form-only, and it collides with the builtin), and a malformed tag
degrades to escaped output rather than 500-ing the page.
"""
import os
import re

from django import template
from django.conf import settings
from django.template import Context, Template, TemplateSyntaxError
from django.urls import NoReverseMatch, reverse
from django.utils.html import conditional_escape
from django.utils.safestring import mark_safe

register = template.Library()


_IMG_EXTS = (".svg", ".png", ".jpg", ".jpeg", ".pdf")


@register.simple_tag
def media(path):
    p = str(path).lstrip("/")
    # meta-migrated figure refs are extensionless (resolve to <ref>.<ext> on
    # disk); find the staged file under MEDIA_ROOT and serve its real name.
    if not os.path.splitext(p)[1]:
        root = getattr(settings, "MEDIA_ROOT", None)
        if root:
            for ext in _IMG_EXTS:
                if os.path.exists(os.path.join(root, p + ext)):
                    return settings.MEDIA_URL + p + ext
    return settings.MEDIA_URL + p


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
    # Page templates load this library (for render_book), which shadows Django's
    # builtin {% url %}. Resolve real routes (breadcrumb/pager/login) and degrade
    # unknown ones (legacy homepage-django routes embedded in artifact html) to "#".
    if not args:
        return "#"
    name, params = args[0], list(args[1:])
    try:
        return reverse(name, args=params, kwargs=kwargs)
    except NoReverseMatch:
        return "#"


def _ed_query(book):
    """The ?ed=<id> suffix that addresses `book`'s edition — empty for the
    default edition (and single-edition books), which live at the bare URLs. So
    a section keeps one stable path; the query only selects the variant."""
    if book is None or book.is_default_edition:
        return ""
    return f"?ed={book.edition_id}"


@register.simple_tag
def index_url(book):
    """TOC URL for a book edition (bare for default, else ?ed=<id>)."""
    return reverse("parody_web:index") + _ed_query(book)


@register.simple_tag
def chapter_url(book, chapter_slug):
    """Chapter landing-page URL, keeping the edition (?ed=) so navigation stays
    on the same edition."""
    return reverse("parody_web:chapter", args=[chapter_slug]) + _ed_query(book)


@register.simple_tag
def section_url(book, chapter_slug, section_slug):
    """Section URL, keeping the edition (?ed=) so all in-edition navigation
    (TOC, breadcrumb, pager) stays on the same edition."""
    return (reverse("parody_web:section", args=[chapter_slug, section_slug])
            + _ed_query(book))


@register.simple_tag
def systems_url(book, version):
    """URL of a system's parts catalog within the current edition."""
    return reverse("parody_web:systems", args=[version]) + _ed_query(book)


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

# Pandoc emits math as <span class="math inline|display">…</span>. LaTeX braces
# inside (e.g. \sqrt{\frac{{K_M}^2+BR}{JL}} -> "{{…}}") would otherwise be parsed
# as Django {{ var }} / {% tag %} syntax and raise TemplateSyntaxError, taking
# down the whole page's tag expansion (including {% media %} images). Shield each
# math span's contents in {% verbatim %} before rendering.
_MATH_SPAN_RE = re.compile(r'(<span class="math(?:\s[^"]*)?">)(.*?)(</span>)', re.DOTALL)


def _shield_math(html):
    return _MATH_SPAN_RE.sub(
        lambda m: m.group(1) + "{% verbatim %}" + m.group(2) + "{% endverbatim %}" + m.group(3),
        html,
    )


_CODE_SPAN_RE = re.compile(r"`([^`]+)`")


@register.filter(is_safe=True)
def code_spans(text):
    """Render Markdown backtick code spans in a heading/title as <code>…</code>,
    HTML-escaping the rest. Section titles like "Function `sos2header()` for …"
    carry literal backticks from the source; the TOC, breadcrumb and pager would
    otherwise show them raw."""
    text = str(text or "")
    out, last = [], 0
    for m in _CODE_SPAN_RE.finditer(text):
        out.append(conditional_escape(text[last:m.start()]))
        out.append(f"<code>{conditional_escape(m.group(1))}</code>")
        last = m.end()
    out.append(conditional_escape(text[last:]))
    return mark_safe("".join(out))


@register.filter(is_safe=True)
def render_book(html):
    """Render stored Django-flavored html (defaults to '' for empty fields)."""
    if not html:
        return ""
    source = "{% load parody_web %}" + _shield_math(_CSRF_RE.sub("", html))
    try:
        return mark_safe(Template(source).render(Context({})))
    except TemplateSyntaxError as exc:
        # Don't take the page down over one unexpected tag; surface in a comment.
        return mark_safe(
            f"<!-- book-host: unresolved template content: "
            f"{conditional_escape(str(exc))} -->" + html
        )
