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
    path("<slug:chapter_slug>/<slug:section_slug>/", views.section_detail,
         name="section"),
    # Chapter landing page (lead-in + contents). A code with a trailing slash
    # (e.g. /q9/) also lands here; chapter_detail falls back to code resolution.
    path("<slug:chapter_slug>/", views.chapter_detail, name="chapter"),
    # Short codes printed in the book: /q9 (no trailing slash, so the QR stays
    # tiny) → 302 to the canonical page. Last so the reserved/known patterns win.
    path("<str:code>", views.code_redirect, name="code"),
]
