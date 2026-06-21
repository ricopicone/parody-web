from django.urls import path

from . import views

app_name = "parody_web"

urlpatterns = [
    path("", views.index, name="index"),
    path("sitemap.xml", views.sitemap_xml, name="sitemap"),
    path("robots.txt", views.robots_txt, name="robots"),
    path("<slug:chapter_slug>/<slug:section_slug>/", views.section_detail,
         name="section"),
]
