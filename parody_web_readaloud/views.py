"""Read-along endpoints.

Both ask the access policy exactly the question `parody_web.views.section_pdf`
asks. Anything a reader may not download, they may not listen to, and a refusal
must not distinguish itself from an absence.

NEITHER SYNTHESISES. A miss is a 404. Lazy synthesis is the one path by which an
anonymous visitor to a public book could mint new audio, and the only way cost
starts tracking requests instead of content.
"""

import re

from django.http import (FileResponse, Http404, HttpResponse,
                         HttpResponseRedirect, JsonResponse)
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
        "regions": row.regions,
        # A preview track carries timings but no audio. The client drives
        # itself from a clock when this is null, so the pacing and the reveals
        # can be judged before a voice is chosen or paid for.
        "audio_url": (reverse("parody_web_readaloud:audio", kwargs={
            "chapter_slug": chapter_slug, "section_slug": section_slug,
        }) + f"?voice={row.voice_id}") if row.audio_name else None,
    })


_RANGE = re.compile(r"bytes=(\d*)-(\d*)$")


def _ranged(request, path):
    """Serve a local `path` honouring HTTP Range.

    The LOCAL path only. When audio lives in S3 the view redirects and S3 does
    Range itself; this is what keeps `runserver` working with no AWS, and a
    developer who cannot seek locally cannot test seeking.

    Without this the browser CANNOT SEEK. It has to fetch the file linearly
    from the start, so jumping to 4 minutes into a 4 MB track silently snaps
    back to the beginning — which is what made "read from here", resume and
    skip-ahead all appear to "start at the beginning" no matter what.

    Django's FileResponse does not do this for us here: a Range request came
    back 200 with the whole file, no Content-Range and no Accept-Ranges.
    """
    size = path.stat().st_size
    header = request.headers.get("Range", "")
    match = _RANGE.match(header.strip()) if header else None

    if not match:
        response = FileResponse(path.open("rb"), content_type="audio/mpeg")
        response["Accept-Ranges"] = "bytes"
        response["Content-Length"] = str(size)
        return response

    start_raw, end_raw = match.groups()
    if start_raw:
        start = int(start_raw)
        end = int(end_raw) if end_raw else size - 1
    else:
        # `bytes=-N` — the LAST n bytes, which is how some players probe a file.
        if not end_raw:
            return HttpResponse(status=416)
        start = max(0, size - int(end_raw))
        end = size - 1

    end = min(end, size - 1)
    if start > end or start >= size:
        response = HttpResponse(status=416)
        response["Content-Range"] = f"bytes */{size}"
        return response

    handle = path.open("rb")
    handle.seek(start)
    length = end - start + 1
    response = FileResponse(handle, content_type="audio/mpeg", status=206)
    response["Content-Range"] = f"bytes {start}-{end}/{size}"
    response["Content-Length"] = str(length)
    response["Accept-Ranges"] = "bytes"
    # FileResponse would otherwise stream to EOF, past the requested range.
    response.streaming_content = _chunks(handle, length)
    return response


def _chunks(handle, length, size=64 * 1024):
    remaining = length
    while remaining > 0:
        data = handle.read(min(size, remaining))
        if not data:
            break
        remaining -= len(data)
        yield data
    handle.close()


@require_http_methods(["GET", "HEAD"])
def audio(request, chapter_slug, section_slug):
    _, _, row = _track_or_404(request, chapter_slug, section_slug)
    try:
        store = storage.backend()
        present = store.exists(row.audio_name)
    except (RuntimeError, ValueError):
        # Misconfiguration, not a reader error — but still a 404 rather than a
        # 500, because the reader can do nothing with the difference.
        raise Http404("read-along audio is not configured")
    if not present:
        raise Http404("read-along audio has not been generated")

    url = store.url(row.audio_name)
    if url is None:
        return _ranged(request, store.path(row.audio_name))

    # The gate has already been asked, above, exactly as `section_pdf` asks it.
    # Only now is a URL minted, and it is short-lived.
    response = HttpResponseRedirect(url)
    # A signed URL dies twice over: at its expiry, and — earlier, on the box —
    # when the instance-role credentials that signed it rotate. Nothing may
    # serve a dead one out of a cache; the client re-fetches this endpoint
    # instead, which re-runs the access check and mints a fresh URL.
    response["Cache-Control"] = "private, no-store"
    return response
