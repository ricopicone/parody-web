from django.urls import path

from . import views

app_name = "parody_web"

urlpatterns = [
    path("", views.index, name="index"),
    path("sitemap.xml", views.sitemap_xml, name="sitemap"),
    path("robots.txt", views.robots_txt, name="robots"),
    path("errata/", views.errata, name="errata"),
    # Editions are selected by a ?ed=<id> query string (not a path prefix), so a
    # section keeps ONE stable URL across editions — the query just picks the
    # variant. No ?ed= serves the default (latest) edition. This keeps the short
    # codes printed in the book (and the QR codes that point at them) resolving
    # to steady URLs regardless of which edition is current.
    path("go/", views.go_code, name="go"),
    # /systems/<version>/ — the per-edition specific-parts catalog. "systems" is
    # a reserved first segment (like "errata"/"go"); listed before the bare
    # <chapter>/ patterns so it wins.
    path("systems/<str:version>/", views.systems, name="systems"),
    # /index/ — the subject index built from the .index spans (reserved segment).
    path("index/", views.book_index, name="book_index"),
    # /search/ — "search inside" (snippet results + buy CTA).
    path("search/", views.search, name="search"),
    # /pdf/ — the whole book as one PDF (reserved segment). Gated by the access
    # policy: print PDFs are never served off disk by nginx, because that tree
    # has no auth and the PDF holds the full text of gated sections.
    path("pdf/", views.book_pdf, name="book_pdf"),
    # One exercise's worked solution, gated by the access policy. <str:> not
    # <slug:> because exercise ids carry a colon ("exe:z3-agent"). Listed before
    # the bare section pattern so the reserved "solutions" segment reads first.
    path("<slug:chapter_slug>/<slug:section_slug>/solutions/<str:exercise_id>/",
         views.solution_detail, name="solution"),
    # Full-window PDF reader. Longer path first so it wins over the download.
    path("<slug:chapter_slug>/<slug:section_slug>/pdf/view/",
         views.section_pdf_view, name="section_pdf_view"),
    # This section's pages from the print PDF. Before the bare section pattern
    # so the reserved "pdf" segment reads first.
    path("<slug:chapter_slug>/<slug:section_slug>/pdf/", views.section_pdf,
         name="section_pdf"),
    path("<slug:chapter_slug>/<slug:section_slug>/", views.section_detail,
         name="section"),
    # Chapter landing page (lead-in + contents). A code with a trailing slash
    # (e.g. /q9/) also lands here; chapter_detail falls back to code resolution.
    path("<slug:chapter_slug>/", views.chapter_detail, name="chapter"),
    # Short codes printed in the book: /q9 (no trailing slash, so the QR stays
    # tiny) → 302 to the canonical page. Last so the reserved/known patterns win.
    path("<str:code>", views.code_redirect, name="code"),
]
