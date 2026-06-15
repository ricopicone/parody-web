from django.urls import path

from . import views

app_name = "book"

urlpatterns = [
    path("", views.index, name="index"),
    path("<slug:chapter_slug>/<slug:section_slug>/", views.section_detail,
         name="section"),
]
