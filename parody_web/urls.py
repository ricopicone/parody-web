from django.urls import path

from . import views

app_name = "parody_web"

urlpatterns = [
    path("", views.index, name="index"),
    path("sitemap.xml", views.sitemap_xml, name="sitemap"),
    path("robots.txt", views.robots_txt, name="robots"),
    path("errata/", views.errata, name="errata"),
    # Non-default editions live under /editions/<id>/; the default (latest)
    # edition is served at the root patterns below. "editions" is a reserved
    # first path segment (no chapter may use it). Listed before the bare
    # <chapter>/<section>/ pattern so the prefix wins.
    path("editions/<str:edition_id>/", views.index, name="edition_index"),
    path("editions/<str:edition_id>/<slug:chapter_slug>/<slug:section_slug>/",
         views.section_detail, name="edition_section"),
    path("<slug:chapter_slug>/<slug:section_slug>/", views.section_detail,
         name="section"),
]
