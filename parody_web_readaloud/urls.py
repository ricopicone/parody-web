"""Read-along routes, mounted alongside parody_web's under the same book prefix."""

from django.urls import path

from . import views

app_name = "parody_web_readaloud"

urlpatterns = [
    path("<slug:chapter_slug>/<slug:section_slug>/readalong/",
         views.track, name="track"),
    path("<slug:chapter_slug>/<slug:section_slug>/readalong/audio/",
         views.audio, name="audio"),
]
