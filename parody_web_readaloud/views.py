"""Read-along endpoints.

Both ask the access policy exactly the question `parody_web.views.section_pdf`
asks. Anything a reader may not download, they may not listen to, and a refusal
must not distinguish itself from an absence.

NEITHER SYNTHESISES. A miss is a 404. Lazy synthesis is the one path by which an
anonymous visitor to a public book could mint new audio, and the only way cost
starts tracking requests instead of content.
"""

from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from parody_web import printing
from parody_web.access import get_policy
from parody_web.models import Section
from parody_web.views import _resolve_book

from . import storage
from .models import ReadAlongTrack

DEFAULT_VOICE = "Matthew"


def _section_or_404(request, chapter_slug, section_slug):
    book, _ = _resolve_book(request)
    section = get_object_or_404(
        Section, book=book, chapter__slug=chapter_slug, slug=section_slug)
    if not get_policy().can_download_section_pdf(request, section):
        raise Http404("no pdf for this section")
    return book, section


def _track_or_404(request, chapter_slug, section_slug):
    book, section = _section_or_404(request, chapter_slug, section_slug)
    voice = request.GET.get("voice") or DEFAULT_VOICE
    track = ReadAlongTrack.objects.filter(
        book_slug=book.slug, edition_id=book.edition_id or "",
        section_key=section.key,
        slice_key=printing.slice_key_for(book, section),
        voice_id=voice).first()
    if track is None:
        raise Http404("no read-along for this section")
    return book, section, track


@require_http_methods(["GET"])
def track(request, chapter_slug, section_slug):
    _, _, row = _track_or_404(request, chapter_slug, section_slug)
    return JsonResponse({
        "slice_key": row.slice_key,
        "voice_id": row.voice_id,
        "duration_ms": row.duration_ms,
        "words": row.words,
        "clozes": row.clozes,
        "pages": row.pages,
        "audio_url": reverse("parody_web_readaloud:audio", kwargs={
            "chapter_slug": chapter_slug, "section_slug": section_slug,
        }) + f"?voice={row.voice_id}",
    })


@require_http_methods(["GET"])
def audio(request, chapter_slug, section_slug):
    _, _, row = _track_or_404(request, chapter_slug, section_slug)
    try:
        path = storage.audio_path(row.audio_name)
    except (RuntimeError, ValueError):
        # Misconfiguration, not a reader error — but still a 404 rather than a
        # 500, because the reader can do nothing with the difference.
        raise Http404("read-along audio is not configured")
    if not path.exists():
        raise Http404("read-along audio has not been generated")
    return FileResponse(path.open("rb"), content_type="audio/mpeg")
