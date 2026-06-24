"""Views for the book site.

Public visitors get the full table of contents, a preview of gated sections,
and the full text of the publicly-licensed sections; the owner (authenticated)
sees everything. One deployment holds the full artifact yet exposes only the
permitted subset publicly.
"""

import re
from html import unescape as _unescape

from django.conf import settings
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.html import escape, strip_tags
from django.utils.safestring import mark_safe

from .models import Book, Chapter, Section

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


def _resolve_book(request):
    """Select the edition to serve (from ?ed=<id>) and the visible roster.

    Draft editions are owner-only: hidden from the public switcher, skipped for
    the public default, and 404 for anonymous visitors. With no ?ed=, serve the
    default edition (flagged, else the latest by order) among the visible ones."""
    everything = _editions(_book_slug())
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


def _all_sections_ordered(book):
    """Every section in reading order. The full TOC/nav is public; gating is
    per-section at view time (full vs preview), not by hiding from the index."""
    return list(
        Section.objects.filter(book=book)
        .select_related("chapter")
        .order_by("chapter__order", "order"))


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
    editions = [b for b in _editions(_book_slug()) if owner or not b.draft]
    # newest edition first ("latest that still has it")
    for book in sorted(editions, key=lambda b: b.edition_order, reverse=True):
        ed_q = _ed_query(book)
        for ch in book.chapters.all():
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
    public = not request.user.is_authenticated
    chapters = []
    for ch in book.chapters.all():
        sections = list(ch.sections.all())
        if sections:
            chapters.append((ch, sections))
    return render(request, "parody_web/index.html", {
        "book": book, "editions": editions, "chapters": chapters,
        "ed_query": _ed_query(book),
        "public": public, "systems_list": book.parts or [],
        "meta_description": book.description or f"{book.title} — companion site.",
        "canonical_url": request.build_absolute_uri(request.path)})


_INDEX_SPAN_RE = re.compile(
    r'<span ([^>]*\bclass="[^"]*\bindex\b[^"]*"[^>]*)>(.*?)</span>', re.S)


def book_index(request):
    """Alphabetical subject index built from the .index spans across every
    section (an "Entry!Subentry" hierarchy; deduped per section). Links point at
    the section that mentions the term — public, like the table of contents."""
    book, editions = _resolve_book(request)
    edq = _ed_query(book)
    root = {}  # name -> {"locs": {section_key: (label, href)}, "subs": {…}}
    for s in _all_sections_ordered(book):
        num = (s.number or "").strip()
        label = num if re.match(r"^[A-Za-z]?\d", num) else \
            (s.chapter.number or s.chapter.title or "").strip()
        section_key = (s.chapter.order, s.order)
        section_url = reverse("parody_web:section", args=[s.chapter.slug, s.slug]) + edq
        for m in _INDEX_SPAN_RE.finditer(s.html or ""):
            attrs, inner = m.group(1), m.group(2)
            text = _unescape(re.sub(r"\s+", " ", strip_tags(inner))).strip()
            parts = [p.strip() for p in text.split("!") if p.strip()]
            idm = re.search(r'\bid="([^"]+)"', attrs)
            href = section_url + ("#" + idm.group(1) if idm else "")
            node = root
            for i, p in enumerate(parts):
                node = node.setdefault(p, {"locs": {}, "subs": {}})
                if i == len(parts) - 1:  # first occurrence per section wins
                    node["locs"].setdefault(section_key, (label, href))
                node = node["subs"]

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
        "ed_query": edq, "public": not request.user.is_authenticated,
        "meta_description": f"Search inside {book.title}.",
        "canonical_url": request.build_absolute_uri(request.path)})


def chapter_detail(request, chapter_slug):
    """A chapter's landing page: the chapter lead-in prose (if any), the list of
    the chapter's sections (as on the index), and a continue button into the
    first section. The lead-in is no longer a separate TOC line — it lives here."""
    book, editions = _resolve_book(request)
    chapter = Chapter.objects.filter(book=book, slug=chapter_slug).first()
    if chapter is None:
        # A printed short code with a trailing slash (e.g. /q9/) lands here too;
        # try resolving it before giving up.
        target = _resolve_code(request, chapter_slug)
        if target:
            return redirect(target)
        raise Http404(f"no chapter {chapter_slug!r}")
    public = not request.user.is_authenticated

    sections = list(chapter.sections.all())
    # The lead-in section (slug "lead-in") is intro prose shown above the
    # contents, not listed among them; everything else is a content section.
    leadin = next((s for s in sections if s.slug == "lead-in"), None)
    contents = [s for s in sections if s.slug != "lead-in"]
    # "Continue" enters at the first content section.
    first = contents[0] if contents else None
    # A preview lead-in teases the public exactly like a preview section.
    preview = bool(leadin and leadin.preview and public)
    return render(request, "parody_web/chapter.html", {
        "book": book, "editions": editions,
        "chapter": chapter, "leadin": leadin, "contents": contents,
        "first": first, "public": public, "preview": preview,
        "next_path": request.get_full_path(),
        "meta_description": _excerpt(leadin.html if leadin else "")
        or f"{chapter.title} — {book.title}.",
        "canonical_url": request.build_absolute_uri(request.path),
    })


def section_detail(request, chapter_slug, section_slug):
    book, editions = _resolve_book(request)
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
    editions = [b for b in _editions(_book_slug()) if not b.draft]
    urls = [request.build_absolute_uri("/")]
    for book in editions:
        q = _ed_query(book)
        if q:
            urls.append(request.build_absolute_uri(f"/{q}"))
        for ch in book.chapters.all():
            urls.append(request.build_absolute_uri(f"/{ch.slug}/{q}"))
        for s in _all_sections_ordered(book):
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
