"""Models mirroring a parody schema-v2 artifact, slimmed for a public,
read-only book site (no solution gating, enrollment, or annotations — those
are ricopic.one concerns). A Book holds the bibliographic/web metadata; a
Section stores the rendered (Django-template-flavored) html and any per-section
online-resources addenda."""

from django.db import models


class Book(models.Model):
    # A row is one *edition* of a book. Editions of the same book share a slug
    # and are distinguished by edition_id; a single-edition book has
    # edition_id="" and behaves exactly as before. parody build emits one
    # artifact per edition (top-level `edition`/`editions` keys), each imported
    # into its own row. The default (latest) edition serves at the bare URLs;
    # the others are selected with a ?ed=<id> query (a section keeps one stable
    # path across editions). See parody's editions-p1-implementation.
    slug = models.SlugField()
    edition_id = models.CharField(max_length=64, blank=True, default="")
    edition_title = models.CharField(max_length=200, blank=True, default="")
    edition_default = models.BooleanField(default=False)
    edition_order = models.PositiveIntegerField(default=0)  # switcher order
    # draft = built but not yet released: visible only to the authenticated
    # owner (hidden from the public switcher; its pages 404 for anonymous
    # visitors) until published. Toggle live with the publish_edition command.
    draft = models.BooleanField(default=False)
    title = models.CharField(max_length=300)
    description = models.TextField(blank=True)
    authors = models.JSONField(default=list, blank=True)
    # parody artifact top-level metadata (book-defs / videos / apocrypha)
    book_metadata = models.JSONField(null=True, blank=True)
    videos = models.JSONField(null=True, blank=True)
    apocrypha = models.JSONField(null=True, blank=True)
    source_commit = models.CharField(max_length=64, blank=True)
    built_at = models.CharField(max_length=40, blank=True)
    cover_image = models.CharField(max_length=200, blank=True, default="")
    errata = models.TextField(blank=True, default="")  # rendered html, optional
    # structured systems catalog (artifact `parts`): list of systems for this
    # edition's active versions; rendered by the /systems/<version>/ pages.
    parts = models.JSONField(null=True, blank=True)

    class Meta:
        unique_together = ("slug", "edition_id")
        ordering = ["slug", "edition_order"]

    @property
    def is_default_edition(self):
        """Default/latest edition (or a single-edition book) — served at the
        bare URLs with no ?ed=<id> query."""
        return self.edition_default or not self.edition_id

    def __str__(self):
        if self.edition_id:
            return f"{self.title} ({self.edition_title or self.edition_id})"
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
    # indexed: a host project looks sections up by this to attach its own
    # per-section records (see the `key` property and docs/host-integration.md)
    hash = models.CharField(max_length=100, blank=True, default="", db_index=True)
    html = models.TextField(blank=True)
    # plain-text rendering of `html`, for the "search inside" feature (icontains)
    plain = models.TextField(blank=True, default="")
    online_resources = models.TextField(blank=True)
    online_only = models.BooleanField(default=False)
    # preview = public sees only a truncated excerpt + sign-in (old "versionless":
    # in print, not fully online). Full sections are everything else.
    preview = models.BooleanField(default=False)
    # display number/label, e.g. "3.2", "Lab exercise 4", or "" (Problems/lead-in)
    number = models.CharField(max_length=32, blank=True, default="")
    anchors = models.JSONField(default=list, blank=True)
    # Per-exercise solutions/problems from the artifact, each
    # {exercise_id: {"title", "content"}}. Commercial/partial artifacts carry
    # none and import as {}; course books carry both. Storing them is not
    # exposing them — the access policy decides who may read a solution (see
    # parody_web/access.py).
    has_solutions = models.BooleanField(default=False)
    solutions = models.JSONField(default=dict, blank=True)
    problems = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return f"{self.book.slug} – {self.title}"

    def solution_for(self, exercise_id):
        """The stored solution entry for one exercise, or None."""
        return (self.solutions or {}).get(exercise_id)

    def problem_for(self, exercise_id):
        """The stored problem statement for one exercise, or None."""
        return (self.problems or {}).get(exercise_id)

    @property
    def key(self):
        """The stable identity a host keys its own per-section records to.

        The authored short hash when there is one — it survives renames and
        reorganization, and parody build-checks it for uniqueness within a book.
        But parody emits a hash only when the source authors one in front
        matter, and course books generally do not (0 of 43 sections in the
        engineering-artificial-intelligence golden artifact), so fall back to
        the always-present chapter/section slug pair rather than keying every
        section to "".
        """
        return self.hash or f"{self.chapter.slug}/{self.slug}"
