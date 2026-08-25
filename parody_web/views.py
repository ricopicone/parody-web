"""Views for the book site.

Public visitors get the full table of contents, a preview of gated sections,
and the full text of the publicly-licensed sections; the owner (authenticated)
sees everything. One deployment holds the full artifact yet exposes only the
permitted subset publicly.
"""

import re
from html import unescape as _unescape
from pathlib import Path

from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.utils.html import escape, strip_tags
from django.utils.safestring import mark_safe

from django.utils import timezone

from . import editable_tables
from .access import get_policy

# The reader's own data leaves here in a documented shape, and something on the
# other end will grow to depend on it: name the shape and version it, so a later
# change to what a table exports is a new number rather than a silent break.
TABLE_EXPORT_FORMAT = "parody-table/1"
TABLES_EXPORT_FORMAT = "parody-tables/1"
from .books import resolve_slug
from .models import Book, Chapter, Section
from .numbering import section_own_heading

# Django-template tags embedded in stored html ({% media %}, {{ x }}); strip
# them from meta-description snippets so raw tags never leak into <meta>.
_TEMPLATE_TAG_RE = re.compile(r"\{%.*?%\}|\{\{.*?\}\}", re.DOTALL)


def _excerpt(html, n=155):
    """Plain-text snippet for <meta description> / og:description (never the
    full text — just the opening, safe to expose and good for SEO)."""
    text = " ".join(strip_tags(_TEMPLATE_TAG_RE.sub("", html or "")).split())
    return text[:n].rsplit(" ", 1)[0] + "…" if len(text) > n else text


def _book_slug(request=None):
    """The slug of the book this *request* is for — the host's resolver, else
    BOOK_SLUG, else the only imported book (see books.resolve_slug)."""
    return resolve_slug(request)


def _editions(slug):
    """Every edition row for a book slug, in switcher order."""
    return list(Book.objects.filter(slug=slug).order_by("edition_order", "id"))


def _is_owner(request):
    """Whether this request is the book's owner — the access policy's call
    (PARODY_WEB_ACCESS_POLICY), so a host project can redefine it."""
    return bool(get_policy().is_owner(request))


def _can_view_drafts(request):
    """Whether this request may see chapters that are not yet released."""
    return bool(get_policy().can_view_drafts(request))


def visible_chapters(book, request):
    """The book's chapters this request may see, in reading order.

    One helper rather than the same filter written out at nine call sites: a
    surface that forgets to filter leaks unreleased material to a class, so
    there should be exactly one obvious thing for a new surface to call.
    """
    chapters = book.chapters.all()
    if _can_view_drafts(request):
        return chapters
    return chapters.filter(draft=False)


def _resolve_book(request):
    """Select the edition to serve (from ?ed=<id>) and the visible roster.

    Draft editions are owner-only: hidden from the public switcher, skipped for
    the public default, and 404 for anonymous visitors. With no ?ed=, serve the
    default edition (flagged, else the latest by order) among the visible ones."""
    everything = _editions(_book_slug(request))
    if not everything:
        raise Http404("no book imported")
    owner = _is_owner(request)
    visible = everything if owner else [b for b in everything if not b.draft]
    edition_id = request.GET.get("ed") if request else None
    if edition_id:
        book = next((b for b in everything if b.edition_id == edition_id), None)
        if book is None or (book.draft and not owner):
            raise Http404(f"no edition {edition_id!r}")
        return book, visible
    if not visible:
        raise Http404("no published edition")
    book = next((b for b in visible if b.edition_default), None) or visible[-1]
    return book, visible


def _ed_query(book):
    """The ?ed=<id> suffix needed to address `book`'s edition — empty for the
    default edition (and single-edition books), which live at the bare URLs."""
    if book is None or book.is_default_edition:
        return ""
    return f"?ed={book.edition_id}"


def _current_book(request=None):
    book, _ = _resolve_book(request)
    return book


def _all_sections_ordered(book, request):
    """Every section this request may see, in reading order.

    The full TOC/nav is public; per-section gating is done at view time (full vs
    preview), not by hiding from the index. Sections of a DRAFT chapter are the
    exception — an unreleased chapter must not appear in the subject index, the
    prev/next nav, the sitemap or the table export.

    `request` is required rather than defaulting to None: a default would fail
    OPEN, and every caller has one.
    """
    qs = (Section.objects.filter(book=book)
          .select_related("chapter")
          .order_by("chapter__order", "order"))
    if not _can_view_drafts(request):
        qs = qs.exclude(chapter__draft=True)
    return list(qs)


_H2_ID_RE = re.compile(r'<h2\b[^>]*\bid="(?P<id>[^"]+)"[^>]*>(?P<text>.*?)</h2>', re.S)


def _chapter_nav(book, chapter, current=None):
    """The chapter's content sections in reading order, each flagged whether it
    is the one being read. The lead-in is intro prose, not a contents entry."""
    out = []
    for s in chapter.sections.all():
        if s.slug == "lead-in":
            continue
        s.is_current = bool(current and s.pk == current.pk)
        out.append(s)
    return out


def _page_anchors(html):
    """Subsection targets for the margin rail: <h2 id="..."> only.

    Some migrated sections carry headings with no id at all; those can't be
    linked, so they are skipped rather than guessed at."""
    out = []
    for mo in _H2_ID_RE.finditer(html or ""):
        # Unescape as well as strip: the heading's html says "Reading &amp;
        # Writing", and the template escapes what it is given — so the rail
        # read "Reading &amp; Writing" literally, ampersand entity and all.
        text = " ".join(_unescape(strip_tags(mo.group("text"))).split())
        if text:
            out.append({"id": mo.group("id"), "text": text})
    return out


def _resolve_code(request, code):
    """Map a printed short code (a chapter/section/figure/exercise hash, or a
    float id like ``fig:bode``) to a canonical in-site URL.

    The code QR-printed in the book never changes, but editions reorganize
    content, so we resolve to the LATEST visible edition that still contains the
    code (falling back to older editions if a newer one dropped it). Matching is
    case-insensitive. Returns the URL (with ?ed= and #anchor as needed) or None."""
    code = (code or "").strip().lstrip("#").lower()
    if not code:
        return None
    owner = _is_owner(request)
    editions = [b for b in _editions(_book_slug(request)) if owner or not b.draft]
    # newest edition first ("latest that still has it")
    for book in sorted(editions, key=lambda b: b.edition_order, reverse=True):
        ed_q = _ed_query(book)
        for ch in visible_chapters(book, request):
            if ch.hash and ch.hash.lower() == code:
                return reverse("parody_web:chapter", args=[ch.slug]) + ed_q
        for sec in book.sections.select_related("chapter"):
            base = reverse("parody_web:section",
                           args=[sec.chapter.slug, sec.slug])
            if sec.hash and sec.hash.lower() == code:
                return base + ed_q
            for a in (sec.anchors or []):
                if code in ((a.get("hash") or "").lower(),
                            (a.get("id") or "").lower()):
                    anchor = a.get("id") or ""
                    return base + ed_q + (f"#{anchor}" if anchor else "")
    return None


def index(request):
    book, editions = _resolve_book(request)
    public = not _is_owner(request)
    chapters = []
    for ch in visible_chapters(book, request):
        sections = list(ch.sections.all())
        if sections:
            chapters.append((ch, sections))
    return render(request, "parody_web/index.html", {
        "book": book, "editions": editions, "chapters": chapters,
        "ed_query": _ed_query(book),
        "public": public, "systems_list": book.parts or [],
        "meta_description": book.description or f"{book.title} — companion site.",
        "canonical_url": request.build_absolute_uri(request.path),
        **_print_context(request, book)})


_INDEX_SPAN_RE = re.compile(
    r'<span ([^>]*\bclass="[^"]*\bindex\b[^"]*"[^>]*)>(.*?)</span>', re.S)
# The fallback source, for books that never wrote .index spans — see book_index.
_KEYWORD_SPAN_RE = re.compile(
    r'<span ([^>]*\bclass="[^"]*\bkeyword\b[^"]*"[^>]*)>(.*?)</span>', re.S)


def book_index(request):
    """Alphabetical subject index, from the .index spans across every section
    (an "Entry!Subentry" hierarchy; deduped per section). Links point at the
    section that mentions the term — public, like the table of contents.

    Books that never wrote .index spans fall back to their **keywords**. Print
    has always done this: parody's \\keyword indexes as well as emphasises, so
    System Dynamics' 467 keyword spans produce a 378-entry printed index while
    this page said "No index entries" — and the same was true of the electronics
    primer and the math notes, three books out of four. A keyword has no
    Entry!Subentry hierarchy and no id of its own, so entries are flat and link
    to the section, exactly as the printed index points at a page.

    Case is folded in the fallback only: a keyword is prose emphasis, so the
    same term is capitalised at the start of a sentence and not in the middle,
    and "Input variables" and "input variables" are one entry. An .index span is
    authored deliberately, and its case is left alone.
    """
    book, editions = _resolve_book(request)
    edq = _ed_query(book)
    root = {}  # name -> {"locs": {section_key: (label, href)}, "subs": {…}}

    def harvest(pattern, fold_case=False):
        canon = {}  # lower-cased name -> the spelling to display
        for s in _all_sections_ordered(book, request):
            num = (s.number or "").strip()
            label = num if re.match(r"^[A-Za-z]?\d", num) else \
                (s.chapter.number or s.chapter.title or "").strip()
            section_key = (s.chapter.order, s.order)
            section_url = reverse(
                "parody_web:section", args=[s.chapter.slug, s.slug]) + edq
            for m in pattern.finditer(s.html or ""):
                attrs, inner = m.group(1), m.group(2)
                text = _unescape(re.sub(r"\s+", " ", strip_tags(inner))).strip()
                parts = [p.strip() for p in text.split("!") if p.strip()]
                idm = re.search(r'\bid="([^"]+)"', attrs)
                href = section_url + ("#" + idm.group(1) if idm else "")
                node = root
                for i, p in enumerate(parts):
                    if fold_case:
                        p = canon.setdefault(p.lower(), p)
                    node = node.setdefault(p, {"locs": {}, "subs": {}})
                    if i == len(parts) - 1:  # first occurrence per section wins
                        node["locs"].setdefault(section_key, (label, href))
                    node = node["subs"]

    harvest(_INDEX_SPAN_RE)
    if not root:
        harvest(_KEYWORD_SPAN_RE, fold_case=True)

    entries = []

    def walk(nodes, level):
        for name in sorted(nodes, key=lambda x: (x.lower(), x)):
            n = nodes[name]
            locs = [{"label": lbl, "url": u}
                    for k, (lbl, u) in sorted(n["locs"].items())]
            letter = name[0].upper() if name[:1].isalpha() else "#"
            entries.append({"level": level, "name": name, "locs": locs, "letter": letter})
            walk(n["subs"], level + 1)

    walk(root, 0)
    prev = None
    for e in entries:
        if e["level"] == 0 and e["letter"] != prev:
            e["new_letter"] = e["letter"]
            prev = e["letter"]
    return render(request, "parody_web/book_index.html", {
        "book": book, "editions": editions, "entries": entries, "ed_query": edq,
        "meta_description": f"Subject index for {book.title}.",
        "canonical_url": request.build_absolute_uri(request.path)})


def _highlight(seg, q):
    """Escape `seg` for HTML and wrap each (case-insensitive) occurrence of `q`
    in <mark>. Returns safe HTML."""
    low, ql, out, pos = seg.lower(), q.lower(), [], 0
    while True:
        i = low.find(ql, pos)
        if i < 0:
            out.append(escape(seg[pos:]))
            break
        out.append(escape(seg[pos:i]))
        out.append("<mark>" + escape(seg[i:i + len(q)]) + "</mark>")
        pos = i + len(q)
    return "".join(out)


def _snippets(plain, q, radius=90, maxn=2):
    """Up to `maxn` highlighted context windows (±`radius` chars) around `q`."""
    low, ql, out, start = plain.lower(), q.lower(), [], 0
    for _ in range(maxn):
        i = low.find(ql, start)
        if i < 0:
            break
        a, b = max(0, i - radius), min(len(plain), i + len(q) + radius)
        pre = "… " if a > 0 else ""
        suf = " …" if b < len(plain) else ""
        out.append(mark_safe(pre + _highlight(plain[a:b], q) + suf))
        start = b
    return out


def search(request):
    """"Search inside": full-text match over sections, returning highlighted
    snippets only (never the full gated text) plus a buy CTA for anon visitors —
    discoverability without exposing copyrighted prose."""
    book, editions = _resolve_book(request)
    edq = _ed_query(book)
    q = (request.GET.get("q") or "").strip()
    results = []
    if len(q) >= 2:
        qs = (Section.objects.filter(book=book, plain__icontains=q)
              .select_related("chapter").order_by("chapter__order", "order"))
        if not _can_view_drafts(request):
            qs = qs.exclude(chapter__draft=True)
        for s in qs:
            snips = _snippets(s.plain, q)
            if not snips:
                continue
            results.append({
                "title": s.title, "number": s.number, "chapter": s.chapter.title,
                "url": reverse("parody_web:section", args=[s.chapter.slug, s.slug]) + edq,
                "snippets": snips, "count": s.plain.lower().count(q.lower()),
                "gated": s.preview,
            })
        results.sort(key=lambda r: -r["count"])
    return render(request, "parody_web/search.html", {
        "book": book, "editions": editions, "q": q, "results": results,
        "ed_query": edq, "public": not _is_owner(request),
        "meta_description": f"Search inside {book.title}.",
        "canonical_url": request.build_absolute_uri(request.path)})


def chapter_detail(request, chapter_slug):
    """A chapter's landing page: the chapter lead-in prose (if any), the list of
    the chapter's sections (as on the index), and a continue button into the
    first section. The lead-in is no longer a separate TOC line — it lives here."""
    book, editions = _resolve_book(request)
    chapter = Chapter.objects.filter(book=book, slug=chapter_slug).first()
    if chapter is not None and chapter.draft and not _can_view_drafts(request):
        # 404, never 403: a 403 confirms the chapter exists and leaks its slug.
        raise Http404("chapter not available")
    if chapter is None:
        # A printed short code with a trailing slash (e.g. /q9/) lands here too;
        # try resolving it before giving up.
        target = _resolve_code(request, chapter_slug)
        if target:
            return redirect(target)
        raise Http404(f"no chapter {chapter_slug!r}")
    policy = get_policy()
    public = not policy.is_owner(request)

    sections = list(chapter.sections.all())
    # The lead-in section (slug "lead-in") is intro prose shown above the
    # contents, not listed among them; everything else is a content section.
    leadin = next((s for s in sections if s.slug == "lead-in"), None)
    contents = [s for s in sections if s.slug != "lead-in"]
    # "Continue" enters at the first content section.
    first = contents[0] if contents else None
    # A preview lead-in teases the public exactly like a preview section.
    preview = bool(leadin and policy.section_is_preview(request, leadin))
    return render(request, "parody_web/chapter.html", {
        "book": book, "editions": editions,
        "chapter": chapter, "leadin": leadin, "contents": contents,
        "chapter_nav": _chapter_nav(book, chapter),
        "first": first, "public": public, "preview": preview,
        "next_path": request.get_full_path(),
        "meta_description": _excerpt(leadin.html if leadin else "")
        or f"{chapter.title} — {book.title}.",
        "canonical_url": request.build_absolute_uri(request.path),
        # The chapter title + lead-in prose is one print unit, and the lead-in
        # is read HERE rather than at /<ch>/lead-in/ — so this is the only page
        # its PDF can be offered on.
        **_print_context(request, book, leadin),
    })


def section_detail(request, chapter_slug, section_slug):
    book, editions = _resolve_book(request)
    section = get_object_or_404(
        Section, book=book, chapter__slug=chapter_slug, slug=section_slug)
    policy = get_policy()
    if section.chapter.draft and not _can_view_drafts(request):
        raise Http404("section not available")
    if not policy.can_view_section(request, section):
        raise Http404("section not available")
    # Sections the policy calls preview (in-print but not fully online) show a
    # teaser + sign-in; everything else is full. The owner sees all full.
    preview = policy.section_is_preview(request, section)

    # A data-entry table posts to its own page. Save, then redirect to the
    # table's anchor so a refresh cannot re-submit and the reader lands back on
    # the row they were filling in.
    if request.method == "POST" and not preview:
        table_id = editable_tables.save_post(
            request.POST, user=request.user, book=book, section=section)
        target = reverse("parody_web:section", args=[chapter_slug, section_slug])
        return redirect(f"{target}{_ed_query(book)}"
                        + (f"#{table_id}" if table_id else ""))

    flat = _all_sections_ordered(book, request)
    idx = next((i for i, s in enumerate(flat) if s.pk == section.pk), None)
    prev_s = flat[idx - 1] if idx else None
    next_s = flat[idx + 1] if idx is not None and idx + 1 < len(flat) else None
    return render(request, "parody_web/section.html", {
        "book": book, "editions": editions,
        "section": section, "chapter": section.chapter,
        # The reader's own copy of the section: data-entry tables carry what
        # they saved. Identical to section.html for every other book.
        "section_html": editable_tables.materialise(
            section.html, request=request, book=book, section=section,
            export_url=lambda tid: _table_url(book, chapter_slug, section_slug, tid),
            all_tables_url=_tables_url(book)),
        "chapter_nav": _chapter_nav(book, section.chapter, current=section),
        "page_anchors": [] if preview else _page_anchors(section.html),
        "prev": prev_s, "next": next_s,
        # The artifact html usually carries its own <h1>; only render the
        # template title when it doesn't (e.g. chapter "lead-in" intros). A
        # section written as a ## carrying its own id has its title heading at
        # h2 instead, and looking only for "<h1" printed the title twice — once
        # bare from the template, once numbered from the html (#576).
        "title_in_html": bool(
            section_own_heading(section.html or "", section.hash)),
        "preview": preview,
        "next_path": request.get_full_path(),
        "meta_description": _excerpt(section.html),
        "canonical_url": request.build_absolute_uri(request.path),
        **_print_context(request, book, section),
    })


def _pdf_response(path, download_name, inline=False):
    """Stream a PDF, delegating to nginx when X-Accel is configured.

    With PARODY_WEB_PRINT_XACCEL set, nginx serves the bytes from its internal
    location and Django's worker is free immediately; without it, FileResponse
    streams from the process, which is fine for dev and small deployments.

    `inline` is what the full-window viewer needs: an attachment disposition
    makes the browser DOWNLOAD the file even inside an <iframe>, so the viewer
    would just re-download the PDF instead of showing it.
    """
    from .printing import print_root, xaccel_prefix

    prefix = xaccel_prefix()
    if prefix:
        rel = Path(path).resolve().relative_to(Path(print_root()).resolve())
        resp = HttpResponse(content_type="application/pdf")
        resp["X-Accel-Redirect"] = f"{prefix.rstrip('/')}/{rel}"
    else:
        resp = FileResponse(open(path, "rb"), content_type="application/pdf")
    disposition = "inline" if inline else "attachment"
    resp["Content-Disposition"] = f'{disposition}; filename="{download_name}"'
    return resp


def _pdf_filename(book, section=None):
    """A download name a reader can recognise in their downloads folder."""
    from django.utils.text import slugify

    stem = slugify(book.title) or book.slug
    if section is None:
        return f"{stem}.pdf"
    parts = [stem]
    if section.number:
        parts.append(slugify(section.number))
    parts.append(slugify(section.title) or section.slug)
    return "-".join(p for p in parts if p) + ".pdf"


def _print_context(request, book, section=None):
    """PDF links for the chrome, empty when there is nothing to offer.

    Everything here is computed from what the reader may actually have, so a
    template can render the affordance on truthiness alone. `section` may be
    None (the home page) or a chapter's lead-in (the chapter page, where that
    unit's PDF is the chapter title + intro prose).
    """
    from .printing import book_pdf_path, section_pdf_path

    policy = get_policy()
    ctx = {"section_pdf_url": "", "section_pdf_view_url": "",
           "section_pdf_pages": None, "book_pdf_url": ""}
    if book_pdf_path(book) and policy.can_download_book_pdf(request, book):
        ctx["book_pdf_url"] = reverse("parody_web:book_pdf")
    if section is not None \
            and policy.can_download_section_pdf(request, section) \
            and section_pdf_path(book, section) is not None:
        ctx["section_pdf_url"] = reverse(
            "parody_web:section_pdf", args=[section.chapter.slug, section.slug])
        ctx["section_pdf_view_url"] = reverse(
            "parody_web:section_pdf_view",
            args=[section.chapter.slug, section.slug])
        ctx["section_pdf_pages"] = section.print_page_count
    return ctx


@xframe_options_sameorigin
def section_pdf(request, chapter_slug, section_slug):
    """This section's pages, cut out of the full print PDF.

    Same-origin framing is allowed because the shipped viewer frames this very
    URL: `_pdf_view_stage.html` is an <iframe> around it. A host inherits
    Django's X_FRAME_OPTIONS = "DENY", which forbids framing even same-origin,
    so without this the default stage renders its chrome around a frame the
    browser refuses. SAMEORIGIN still blocks cross-origin framing.

    404 covers every unavailable case — no page range, no PDF on disk, no
    pypdf, or refused by the policy. A refusal must not distinguish itself from
    an absence, or it would confirm that gated content exists.
    """
    from .printing import section_pdf_path

    book, _ = _resolve_book(request)
    section = get_object_or_404(
        Section, book=book, chapter__slug=chapter_slug, slug=section_slug)
    if section.chapter.draft and not _can_view_drafts(request):
        # An unreleased chapter has no page range in the print PDF
        # anyway; this makes the refusal explicit and indistinguishable
        # from an absence.
        raise Http404("section pdf not available")
    if not get_policy().can_download_section_pdf(request, section):
        raise Http404("no pdf for this section")
    path = section_pdf_path(book, section)
    if path is None:
        raise Http404("no pdf for this section")
    # ?inline=1 — the viewer embeds this same URL and needs it rendered, not
    # downloaded. The download links omit it.
    return _pdf_response(path, _pdf_filename(book, section),
                         inline=bool(request.GET.get("inline")))


def section_pdf_view(request, chapter_slug, section_slug):
    """Full-window PDF reader for one section.

    Deliberately chrome-free: no masthead, sidebar, or rail. The document
    itself comes from _pdf_view_stage.html, which a host may shadow to replace
    the default iframe outright — parody_web_annotate does, with a pdf.js
    viewer it can draw on. See docs/host-integration.md.
    """
    from .printing import section_pdf_path

    book, editions = _resolve_book(request)
    section = get_object_or_404(
        Section, book=book, chapter__slug=chapter_slug, slug=section_slug)
    if section.chapter.draft and not _can_view_drafts(request):
        # An unreleased chapter has no page range in the print PDF
        # anyway; this makes the refusal explicit and indistinguishable
        # from an absence.
        raise Http404("section pdf not available")
    if not get_policy().can_download_section_pdf(request, section):
        raise Http404("no pdf for this section")
    if section_pdf_path(book, section) is None:
        raise Http404("no pdf for this section")
    return render(request, "parody_web/pdf_view.html", {
        "book": book, "editions": editions,
        "section": section, "chapter": section.chapter,
        "canonical_url": request.build_absolute_uri(request.path),
        # The stage partial builds its own src from this, so a replacement
        # stage does not have to know parody-web's URL names.
        "pdf_url": reverse("parody_web:section_pdf",
                           args=[chapter_slug, section_slug]),
    })


def book_pdf(request):
    """The whole book as one PDF."""
    from .printing import book_pdf_path

    book, _ = _resolve_book(request)
    if not get_policy().can_download_book_pdf(request, book):
        raise Http404("no pdf for this book")
    path = book_pdf_path(book)
    if path is None:
        raise Http404("no pdf for this book")
    return _pdf_response(path, _pdf_filename(book))


def _table_url(book, chapter_slug, section_slug, table_id):
    """Download URL for one data-entry table's saved values."""
    return (reverse("parody_web:table_export",
                    args=[chapter_slug, section_slug, table_id])
            + _ed_query(book))


def _tables_url(book):
    """Download URL for every table this reader has filled in, book-wide."""
    return reverse("parody_web:tables_export") + _ed_query(book)


def _book_stamp(book):
    return {"slug": book.slug, "title": book.title,
            "edition": book.edition_id or ""}


def _section_stamp(request, book, section):
    return {
        "key": section.key,
        "number": section.number or "",
        "title": section.title,
        "url": request.build_absolute_uri(
            reverse("parody_web:section",
                    args=[section.chapter.slug, section.slug]) + _ed_query(book)),
    }


def _json_download(payload, filename):
    response = JsonResponse(payload, json_dumps_params={"indent": 2})
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def table_export(request, chapter_slug, section_slug, table_id):
    """One data-entry table as JSON, for the reader who filled it in.

    Their measurements, in a shape a spreadsheet or a plotting script can read
    — the point of typing them into the page rather than onto paper. Nobody
    else's values are reachable: the query is keyed to request.user.
    """
    book, _editions = _resolve_book(request)
    section = get_object_or_404(
        Section, book=book, chapter__slug=chapter_slug, slug=section_slug)
    if not get_policy().can_view_section(request, section):
        raise Http404("section not available")
    if not request.user.is_authenticated:
        return JsonResponse({"error": "sign in to download your table"}, status=401)
    if table_id not in editable_tables.table_ids(section.html or ""):
        raise Http404("no such table in this section")
    values = editable_tables.stored_values(request.user, book, section)
    payload = {
        "format": TABLE_EXPORT_FORMAT,
        "exported_at": timezone.now().isoformat(timespec="seconds"),
        "book": _book_stamp(book),
        "section": _section_stamp(request, book, section),
        **editable_tables.table_payload(section.html or "", values, table_id),
    }
    return _json_download(
        payload, f"{book.slug}-{section.slug}-{table_id}.json")


def tables_export(request):
    """Every table this reader has filled in, across the whole book, as one file.

    A lab manual's tables are a term's measurements spread over a dozen labs,
    and asking for them one page at a time is asking someone to remember which
    pages they typed on. Tables with nothing in them are left out — this is the
    reader's data, not the book's blank forms.
    """
    book, _editions = _resolve_book(request)
    if not request.user.is_authenticated:
        return JsonResponse({"error": "sign in to download your tables"},
                            status=401)
    policy = get_policy()
    tables = []
    for section in _all_sections_ordered(book, request):
        if not editable_tables.has_tables(section.html or ""):
            continue
        if not policy.can_view_section(request, section):
            continue
        values = editable_tables.stored_values(request.user, book, section)
        for table_id in editable_tables.table_ids(section.html or ""):
            # Emptiness is judged on what the reader SAVED, not on the rendered
            # records — those now carry the book's own row labels, so every
            # untouched table would look full.
            if not any(v for v in values.get(table_id, {}).values()):
                continue
            tables.append({"section": _section_stamp(request, book, section),
                           **editable_tables.table_payload(
                               section.html or "", values, table_id)})
    payload = {
        "format": TABLES_EXPORT_FORMAT,
        "exported_at": timezone.now().isoformat(timespec="seconds"),
        "book": _book_stamp(book),
        "tables": tables,
    }
    return _json_download(payload, f"{book.slug}-tables.json")


def solution_detail(request, chapter_slug, section_slug, exercise_id):
    """One exercise's worked solution, gated by the access policy.

    parody-web's own answer is "the owner, and nobody else"; a course site
    points PARODY_WEB_ACCESS_POLICY at a class that knows about enrollment and
    due dates. A refusal still renders a page (403) so the host can say when
    the solution opens — see DefaultPolicy.solution_denied_context.
    """
    book, editions = _resolve_book(request)
    section = get_object_or_404(
        Section, book=book, chapter__slug=chapter_slug, slug=section_slug)
    entry = section.solution_for(exercise_id)
    if not entry:
        raise Http404(f"no solution for {exercise_id!r}")

    policy = get_policy()
    base = {"book": book, "editions": editions, "section": section,
            "chapter": section.chapter, "exercise_id": exercise_id,
            "exercise_title": entry.get("title") or "Exercise",
            "canonical_url": request.build_absolute_uri(request.path)}
    if not policy.can_view_solution(request, section, exercise_id):
        ctx = dict(base)
        ctx.update(policy.solution_denied_context(request, section, exercise_id))
        return render(request, "parody_web/solution_denied.html", ctx, status=403)
    return render(request, "parody_web/solution.html",
                  dict(base, solution_html=entry.get("content") or ""))


def systems(request, version):
    """The specific-parts catalog for one system (ts or ds version) of the
    current edition — every component with its specs and device choices +
    suppliers, from the artifact's structured `parts`."""
    book, editions = _resolve_book(request)
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


def code_redirect(request, code):
    """A short code printed in the book (/q9) → 302 to its canonical page. Falls
    back to the chapter landing page if the token is actually a chapter slug
    typed without a trailing slash, so /chapter behaves like /chapter/."""
    target = _resolve_code(request, code)
    if target:
        return redirect(target)
    book, _ = _resolve_book(request)
    if Chapter.objects.filter(book=book, slug=code).exists():
        return redirect(reverse("parody_web:chapter", args=[code]) + _ed_query(book))
    raise Http404(f"no code {code!r}")


def go_code(request):
    """The index 'go to a code' box submits here (?code=…); resolve and redirect,
    or bounce back to the index if it doesn't match anything."""
    target = _resolve_code(request, request.GET.get("code", ""))
    return redirect(target or reverse("parody_web:index"))


def sitemap_xml(request):
    """Plain XML sitemap (index + every chapter/section/system, across all
    editions); no contrib.sitemaps/sites dep. The default edition sits at the
    bare URLs; other editions carry a ?ed=<id> query."""
    # public sitemap: skip draft (unreleased) editions
    editions = [b for b in _editions(_book_slug(request)) if not b.draft]
    urls = [request.build_absolute_uri("/")]
    for book in editions:
        q = _ed_query(book)
        if q:
            urls.append(request.build_absolute_uri(f"/{q}"))
        for ch in visible_chapters(book, request):
            urls.append(request.build_absolute_uri(f"/{ch.slug}/{q}"))
        for s in _all_sections_ordered(book, request):
            urls.append(request.build_absolute_uri(
                f"/{s.chapter.slug}/{s.slug}/{q}"))
        for sys_ in (book.parts or []):
            urls.append(request.build_absolute_uri(
                f"/systems/{sys_.get('version')}/{q}"))
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
