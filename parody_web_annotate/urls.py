"""Ink routes, mounted alongside parody_web's under the same book prefix.

All versioned routes live here rather than in core: resolving a version key
back to an archived book and a page range needs the reader's InkLayer row, and
core has no access to it.
"""

from django.urls import path

from . import views

app_name = "parody_web_annotate"

urlpatterns = [
    path("<slug:chapter_slug>/<slug:section_slug>/ink/",
         views.ink, name="ink"),
    path("<slug:chapter_slug>/<slug:section_slug>/ink/carry-forward/",
         views.carry_forward, name="carry_forward"),
    path("<slug:chapter_slug>/<slug:section_slug>/pdf/at/",
         views.section_pdf_at_version, name="section_pdf_at_version"),
    path("<slug:chapter_slug>/<slug:section_slug>/pdf/annotated/",
         views.annotated_section_pdf, name="annotated_section_pdf"),
]
