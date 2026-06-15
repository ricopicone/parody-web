"""Public, read-only views for the partial book site (rtcbook.org)."""

from django.conf import settings
from django.http import Http404
from django.shortcuts import get_object_or_404, render

from .models import Book, Section


def _current_book():
    if settings.BOOK_SLUG:
        return get_object_or_404(Book, slug=settings.BOOK_SLUG)
    book = Book.objects.first()
    if book is None:
        raise Http404("no book imported")
    return book


def index(request):
    book = _current_book()
    chapters = []
    for ch in book.chapters.all():
        chapters.append((ch, list(ch.sections.all())))
    return render(request, "book/index.html", {"book": book, "chapters": chapters})


def section_detail(request, chapter_slug, section_slug):
    book = _current_book()
    section = get_object_or_404(
        Section, book=book, chapter__slug=chapter_slug, slug=section_slug)
    # flat prev/next across the book
    flat = list(Section.objects.filter(book=book).select_related("chapter"))
    idx = next((i for i, s in enumerate(flat) if s.pk == section.pk), None)
    prev_s = flat[idx - 1] if idx else None
    next_s = flat[idx + 1] if idx is not None and idx + 1 < len(flat) else None
    return render(request, "book/section.html", {
        "book": book, "section": section, "chapter": section.chapter,
        "prev": prev_s, "next": next_s,
    })
