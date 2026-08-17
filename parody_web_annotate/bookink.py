"""Laying every section's notes onto the whole book.

Students print this to take into an exam, so the one thing it must never do is
put a note on the wrong page. Everything here is arranged around that.

Strokes are stored per page *within a section*, which is what makes this
possible at all: a note's place in the book is
``section_start + (stroke_page - 1)``, and section_start is read from the
CURRENT book. Notes made against an older release therefore still land
correctly, as long as the section itself did not change shape.
"""

from collections import namedtuple

from parody_web.access import get_policy

from .models import InkLayer

Skipped = namedtuple("Skipped", "section_key title reason")


def latest_layers(user, book):
    """The newest non-empty layer per section, newest first.

    A reader may have annotated several versions of one section; the newest is
    the one they have been working in.
    """
    seen = {}
    for layer in InkLayer.objects.filter(
            user=user, book_slug=book.slug,
            edition_id=book.edition_id or "").order_by("-updated_at"):
        if layer.section_key in seen or not layer.stroke_count:
            continue
        seen[layer.section_key] = layer
    return seen


def _sections_by_key(book):
    return {s.key: s for s in book.sections.select_related("chapter")}


def plan_book_overlay(request, book):
    """Where every note goes in the current book, and what had to be left out.

    Returns ``(pages, pads, skipped)``: pages and pads each map an absolute
    1-based book page to what was drawn there — on the page and in the margin
    beside it — and skipped names the sections whose notes could not be placed.

    Sections share a page where one ends and the next begins, and both sets of
    notes are drawn on it — they both genuinely belong there.
    """
    if not getattr(request.user, "is_authenticated", False):
        return {}, {}, []

    policy = get_policy()
    sections = _sections_by_key(book)
    pages = {}
    pads = {}
    skipped = []

    for key, layer in latest_layers(request.user, book).items():
        section = sections.get(key)
        if section is None:
            skipped.append(Skipped(key, key, "gone"))
            continue
        # A section the reader may not have is simply not in their book. Not
        # reported: saying "skipped 2 sections" would confirm they exist.
        if not policy.can_download_section_pdf(request, section):
            continue
        current = section.print_pages
        if not current or len(current) != 2:
            skipped.append(Skipped(key, section.title, "no-pages"))
            continue
        if not layer.pages or len(layer.pages) != 2:
            skipped.append(Skipped(key, section.title, "no-pages"))
            continue

        current_count = current[1] - current[0] + 1
        noted_count = layer.pages[1] - layer.pages[0] + 1
        if current_count != noted_count:
            # The section changed shape since these notes were made, so page
            # N of the notes is not page N of the section any more. Refusing
            # beats printing a note against the wrong paragraph.
            skipped.append(Skipped(key, section.title, "relaid"))
            continue

        for target, source in ((pages, layer.strokes), (pads, layer.pads)):
            for page_key, strokes in (source or {}).items():
                try:
                    offset = int(page_key)
                except (TypeError, ValueError):
                    continue
                if offset < 1 or offset > current_count or not strokes:
                    continue
                book_page = current[0] + offset - 1
                target.setdefault(book_page, []).extend(strokes)

    return pages, pads, skipped


def summary(request, book):
    """What to tell the reader before they print.

    `stale` are sections whose notes were left out because the section was
    re-laid; each carries the URL to open it, where carry-forward is offered.
    """
    from django.urls import reverse

    pages, pads, skipped = plan_book_overlay(request, book)
    sections = _sections_by_key(book)
    stale = []
    for item in skipped:
        if item.reason != "relaid":
            continue
        section = sections.get(item.section_key)
        stale.append({
            "title": item.title,
            "url": reverse("parody_web:section_pdf_view",
                           args=[section.chapter.slug, section.slug])
            if section else "",
        })
    return {
        "any": bool(pages or pads),
        "pages": len(set(pages) | set(pads)),
        "stale": stale,
    }
