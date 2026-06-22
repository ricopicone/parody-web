"""Views for the book site.

Public visitors get the full table of contents, a preview of gated sections,
and the full text of the publicly-licensed sections; the owner (authenticated)
sees everything. One deployment holds the full artifact yet exposes only the
permitted subset publicly.
"""

import re

from django.conf import settings
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils.html import strip_tags

from .models import Book, Section

# Django-template tags embedded in stored html ({% media %}, {{ x }}); strip
# them from meta-description snippets so raw tags never leak into <meta>.
_TEMPLATE_TAG_RE = re.compile(r"\{%.*?%\}|\{\{.*?\}\}", re.DOTALL)


def _excerpt(html, n=155):
    """Plain-text snippet for <meta description> / og:description (never the
    full text — just the opening, safe to expose and good for SEO)."""
    text = " ".join(strip_tags(_TEMPLATE_TAG_RE.sub("", html or "")).split())
    return text[:n].rsplit(" ", 1)[0] + "…" if len(text) > n else text


def _book_slug():
    """The slug of the book this deployment serves (BOOK_SLUG, else the only
    imported book's slug)."""
    s = getattr(settings, "BOOK_SLUG", "")
    if s:
        return s
    book = Book.objects.first()
    if book is None:
        raise Http404("no book imported")
    return book.slug


def _editions(slug):
    """Every edition row for a book slug, in switcher order."""
    return list(Book.objects.filter(slug=slug).order_by("edition_order", "id"))


def _is_owner(request):
    return bool(request and request.user.is_authenticated)


def _resolve_book(request, edition_id=None):
    """Select the edition to serve and the visible edition roster.

    Draft editions are owner-only: hidden from the public switcher, skipped for
    the public default, and their pages 404 for anonymous visitors. With no
    edition_id, serve the default edition (flagged, else the latest by order)
    among the visible ones."""
    everything = _editions(_book_slug())
    if not everything:
        raise Http404("no book imported")
    owner = _is_owner(request)
    visible = everything if owner else [b for b in everything if not b.draft]
    if edition_id:
        book = next((b for b in everything if b.edition_id == edition_id), None)
        if book is None or (book.draft and not owner):
            raise Http404(f"no edition {edition_id!r}")
        return book, visible
    if not visible:
        raise Http404("no published edition")
    book = next((b for b in visible if b.edition_default), None) or visible[-1]
    return book, visible


def _current_book(request=None):
    book, _ = _resolve_book(request)
    return book


def _all_sections_ordered(book):
    """Every section in reading order. The full TOC/nav is public; gating is
    per-section at view time (full vs preview), not by hiding from the index."""
    return list(
        Section.objects.filter(book=book)
        .select_related("chapter")
        .order_by("chapter__order", "order"))


def index(request, edition_id=None):
    book, editions = _resolve_book(request, edition_id)
    public = not request.user.is_authenticated
    chapters = []
    for ch in book.chapters.all():
        sections = list(ch.sections.all())
        if sections:
            chapters.append((ch, sections))
    return render(request, "parody_web/index.html", {
        "book": book, "editions": editions, "chapters": chapters,
        "public": public, "systems_list": book.parts or [],
        "meta_description": book.description or f"{book.title} — companion site.",
        "canonical_url": request.build_absolute_uri(request.path)})


def section_detail(request, chapter_slug, section_slug, edition_id=None):
    book, editions = _resolve_book(request, edition_id)
    section = get_object_or_404(
        Section, book=book, chapter__slug=chapter_slug, slug=section_slug)
    # Sections flagged `preview` (in-print but not fully online) show a preview
    # + sign-in to the public; everything else is full. The owner sees all full.
    preview = section.preview and not request.user.is_authenticated

    flat = _all_sections_ordered(book)
    idx = next((i for i, s in enumerate(flat) if s.pk == section.pk), None)
    prev_s = flat[idx - 1] if idx else None
    next_s = flat[idx + 1] if idx is not None and idx + 1 < len(flat) else None
    return render(request, "parody_web/section.html", {
        "book": book, "editions": editions,
        "section": section, "chapter": section.chapter,
        "prev": prev_s, "next": next_s,
        # The artifact html usually carries its own <h1>; only render the
        # template title when it doesn't (e.g. chapter "lead-in" intros).
        "title_in_html": "<h1" in (section.html or ""),
        "preview": preview,
        "next_path": request.get_full_path(),
        "meta_description": _excerpt(section.html),
        "canonical_url": request.build_absolute_uri(request.path),
    })


def systems(request, version, edition_id=None):
    """The specific-parts catalog for one system (ts or ds version) of the
    current edition — every component with its specs and device choices +
    suppliers, from the artifact's structured `parts`."""
    book, editions = _resolve_book(request, edition_id)
    system = next((s for s in (book.parts or []) if s.get("version") == version),
                  None)
    if system is None:
        raise Http404(f"no system {version!r}")
    return render(request, "parody_web/systems.html", {
        "book": book, "editions": editions, "system": system,
        "systems_list": book.parts or [],
        "meta_description": f"Parts catalog for the {system.get('title', version)} "
                            f"— {book.title}.",
        "canonical_url": request.build_absolute_uri(request.path)})


def sitemap_xml(request):
    """Plain XML sitemap (index + every section, across all editions); no
    contrib.sitemaps/sites dep. The default edition sits at the root; other
    editions under /editions/<id>/."""
    # public sitemap: skip draft (unreleased) editions
    editions = [b for b in _editions(_book_slug()) if not b.draft]
    urls = [request.build_absolute_uri("/")]
    for book in editions:
        prefix = "" if book.is_default_edition else f"editions/{book.edition_id}/"
        if prefix:
            urls.append(request.build_absolute_uri(f"/{prefix}"))
        for s in _all_sections_ordered(book):
            urls.append(request.build_absolute_uri(
                f"/{prefix}{s.chapter.slug}/{s.slug}/"))
        for sys_ in (book.parts or []):
            urls.append(request.build_absolute_uri(
                f"/{prefix}systems/{sys_.get('version')}/"))
    body = ['<?xml version="1.0" encoding="UTF-8"?>',
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    body += [f"<url><loc>{u}</loc></url>" for u in urls]
    body.append("</urlset>")
    return HttpResponse("\n".join(body), content_type="application/xml")


def errata(request):
    book = _current_book(request)
    if not book.errata:
        raise Http404("no errata")
    return render(request, "parody_web/errata.html", {
        "book": book,
        "meta_description": f"Errata and typos for {book.title}.",
        "canonical_url": request.build_absolute_uri(request.path)})


def robots_txt(request):
    sm = request.build_absolute_uri("/sitemap.xml")
    return HttpResponse(f"User-agent: *\nAllow: /\nSitemap: {sm}\n",
                        content_type="text/plain")
