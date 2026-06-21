"""Views for the book site.

Public visitors see only the online-only sections (the licensed public subset);
the private parts of the book are gated behind login — only the owner has an
account. This lets one deployment hold the full artifact yet expose only the
permitted subset publicly.
"""

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.http import Http404
from django.shortcuts import get_object_or_404, render

from .models import Book, Section


def _current_book():
    if getattr(settings, "BOOK_SLUG", ""):
        return get_object_or_404(Book, slug=getattr(settings, "BOOK_SLUG", ""))
    book = Book.objects.first()
    if book is None:
        raise Http404("no book imported")
    return book


def _visible_sections(book, user):
    """All sections for the owner; only online-only for the public."""
    qs = Section.objects.filter(book=book).select_related("chapter")
    if not user.is_authenticated:
        qs = qs.filter(online_only=True)
    return list(qs)


def index(request):
    book = _current_book()
    public = not request.user.is_authenticated
    chapters = []
    for ch in book.chapters.all():
        sections = list(ch.sections.all())
        if public:
            sections = [s for s in sections if s.online_only]
        if sections:
            chapters.append((ch, sections))
    return render(request, "parody_web/index.html", {
        "book": book, "chapters": chapters, "public": public})


def section_detail(request, chapter_slug, section_slug):
    book = _current_book()
    section = get_object_or_404(
        Section, book=book, chapter__slug=chapter_slug, slug=section_slug)
    # private (non-online-only) sections are owner-only
    if not section.online_only and not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())

    flat = _visible_sections(book, request.user)
    idx = next((i for i, s in enumerate(flat) if s.pk == section.pk), None)
    prev_s = flat[idx - 1] if idx else None
    next_s = flat[idx + 1] if idx is not None and idx + 1 < len(flat) else None
    return render(request, "parody_web/section.html", {
        "book": book, "section": section, "chapter": section.chapter,
        "prev": prev_s, "next": next_s,
        # The artifact html usually carries its own <h1>; only render the
        # template title when it doesn't (e.g. chapter "lead-in" intros).
        "title_in_html": "<h1" in (section.html or ""),
    })
