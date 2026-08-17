from django.db import models


class ReadAlongTrack(models.Model):
    """One synthesis of one version of one section.

    Deliberately NOT per-user: cached audio makes cost constant in the number
    of listeners, which is the whole reason read-along needs no access tier of
    its own. Listeners are not the meter; content is.

    Keyed by slug/edition/section_key/slice_key rather than a Section foreign
    key, for the reason `docs/host-integration.md` section 5 gives: sections are
    deleted and recreated on re-import, and a FK would cascade the cache away on
    every publish.
    """

    book_slug = models.CharField(max_length=100)
    edition_id = models.CharField(max_length=50, blank=True, default="")
    section_key = models.CharField(max_length=200)

    # Which version of the section's PDF these boxes are true of. The same key
    # InkLayer uses, so a reader's notes and their audio go stale together
    # rather than drifting into disagreement.
    slice_key = models.CharField(max_length=64)

    voice_id = models.CharField(max_length=50)
    engine = models.CharField(max_length=20, default="neural")

    # Filename within PARODY_WEB_READALOUD_CACHE, not a path: the cache root is
    # a setting and may move between deploys.
    audio_name = models.CharField(max_length=200)
    duration_ms = models.PositiveIntegerField(default=0)

    # [{word, start_ms, end_ms, page, x0, y0, x1, y1, token}]
    words = models.JSONField(default=list, blank=True)
    # [{token, kind, answer, src, page, x0, y0, x1, y1, start_ms, end_ms}]
    clozes = models.JSONField(default=list, blank=True)
    # [[widthPt, heightPt], ...] — what the client divides the rendered page
    # width by to recover the zoom scale.
    pages = models.JSONField(default=list, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("book_slug", "edition_id", "section_key",
                           "slice_key", "voice_id")
        indexes = [
            models.Index(fields=["book_slug", "section_key"]),
            models.Index(fields=["slice_key"]),
        ]
        ordering = ["-updated_at"]

    def __str__(self):
        return (f"{self.book_slug}/{self.section_key}"
                f"@{self.slice_key[:8]} ({self.voice_id})")

    @property
    def cloze_count(self):
        """How many blanks the student will fill on this section."""
        return len(self.clozes or [])
