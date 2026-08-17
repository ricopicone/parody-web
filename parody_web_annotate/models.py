from django.conf import settings
from django.db import models


class InkLayer(models.Model):
    """One reader's freehand marks on one version of one section's PDF.

    Deliberately self-sufficient. `book_sha256` and `pages` are stored rather
    than looked up because `Section.print_pages` is overwritten by every
    import: without them, a row would name a version it could no longer
    produce the moment the book moved on. With them it can always reconstruct
    its own PDF from the archive.

    Keyed by slug/edition/section_key rather than a Section foreign key for
    the same reason `docs/host-integration.md` section 5 prescribes that key —
    sections are deleted and recreated on re-import, and a FK would cascade a
    reader's notes away with them.
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="parody_ink_layers")
    book_slug = models.CharField(max_length=100)
    edition_id = models.CharField(max_length=50, blank=True, default="")
    section_key = models.CharField(max_length=200)

    # Which version of the section's PDF this ink belongs to.
    slice_key = models.CharField(max_length=64)
    # Everything needed to cut that PDF again, forever.
    book_sha256 = models.CharField(max_length=64)
    pages = models.JSONField()

    strokes = models.JSONField(default=dict, blank=True)
    # The scratch pad beside each page, keyed the same way as `strokes`. Kept
    # separate rather than mixed in under a special page key: the two live in
    # different coordinate spaces, and the exporter has to widen a page for one
    # and not the other.
    pads = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("user", "book_slug", "edition_id",
                           "section_key", "slice_key")
        indexes = [
            models.Index(fields=["user", "book_slug", "section_key"]),
            models.Index(fields=["book_sha256"]),
        ]
        ordering = ["-updated_at"]

    def __str__(self):
        return f"{self.user} · {self.book_slug}/{self.section_key}@{self.slice_key[:8]}"

    @property
    def stroke_count(self):
        """Everything the reader drew, on the page and beside it."""
        return (sum(len(v) for v in (self.strokes or {}).values())
                + sum(len(v) for v in (self.pads or {}).values()))
