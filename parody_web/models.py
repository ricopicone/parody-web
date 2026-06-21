"""Models mirroring a parody schema-v2 artifact, slimmed for a public,
read-only book site (no solution gating, enrollment, or annotations — those
are ricopic.one concerns). A Book holds the bibliographic/web metadata; a
Section stores the rendered (Django-template-flavored) html and any per-section
online-resources addenda."""

from django.db import models


class Book(models.Model):
    slug = models.SlugField(unique=True)
    title = models.CharField(max_length=300)
    description = models.TextField(blank=True)
    authors = models.JSONField(default=list, blank=True)
    # parody artifact top-level metadata (book-defs / videos / apocrypha)
    book_metadata = models.JSONField(null=True, blank=True)
    videos = models.JSONField(null=True, blank=True)
    apocrypha = models.JSONField(null=True, blank=True)
    source_commit = models.CharField(max_length=64, blank=True)
    built_at = models.CharField(max_length=40, blank=True)

    def __str__(self):
        return self.title


class Chapter(models.Model):
    book = models.ForeignKey(Book, related_name="chapters", on_delete=models.CASCADE)
    slug = models.SlugField(max_length=120)
    title = models.CharField(max_length=300)
    order = models.PositiveIntegerField(default=0)
    hash = models.CharField(max_length=100, blank=True, default="")
    appendix = models.BooleanField(default=False)
    number = models.CharField(max_length=16, blank=True, default="")

    class Meta:
        unique_together = ("book", "slug")
        ordering = ["order"]

    def __str__(self):
        return f"{self.book.slug} – {self.title}"


class Section(models.Model):
    book = models.ForeignKey(Book, related_name="sections", on_delete=models.CASCADE)
    chapter = models.ForeignKey(Chapter, related_name="sections", on_delete=models.CASCADE)
    slug = models.SlugField(max_length=120)
    title = models.CharField(max_length=300)
    order = models.PositiveIntegerField(default=0)
    hash = models.CharField(max_length=100, blank=True, default="")
    html = models.TextField(blank=True)
    online_resources = models.TextField(blank=True)
    online_only = models.BooleanField(default=False)
    # preview = public sees only a truncated excerpt + sign-in (old "versionless":
    # in print, not fully online). Full sections are everything else.
    preview = models.BooleanField(default=False)
    # display number/label, e.g. "3.2", "Lab Exercise 4", or "" (Problems/lead-in)
    number = models.CharField(max_length=32, blank=True, default="")
    anchors = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return f"{self.book.slug} – {self.title}"
