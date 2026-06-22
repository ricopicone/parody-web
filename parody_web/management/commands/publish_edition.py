"""Publish a draft edition live (clear its draft flag) without a rebuild.

    python manage.py publish_edition <edition_id> [--slug <book_slug>]

The reverse is ``unpublish_edition``. Both just flip Book.draft, so an edition
can be released (or pulled back) on announcement day without re-importing.
"""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from parody_web.models import Book


class Command(BaseCommand):
    help = "Clear an edition's draft flag (make it public)."
    draft_value = False  # publish clears draft; unpublish_edition sets it

    def add_arguments(self, parser):
        parser.add_argument("edition_id", help="the edition id (e.g. ed2)")
        parser.add_argument("--slug", help="book slug (defaults to BOOK_SLUG / "
                            "the only imported book)")

    def handle(self, *args, **opts):
        slug = opts.get("slug") or getattr(settings, "BOOK_SLUG", "")
        qs = Book.objects.filter(edition_id=opts["edition_id"])
        if slug:
            qs = qs.filter(slug=slug)
        books = list(qs)
        if not books:
            raise CommandError(
                f"no edition {opts['edition_id']!r}"
                + (f" for book {slug!r}" if slug else ""))
        if len(books) > 1:
            raise CommandError(
                f"edition {opts['edition_id']!r} is ambiguous across books; "
                "pass --slug")
        book = books[0]
        book.draft = self.draft_value
        book.save(update_fields=["draft"])
        state = "draft (owner-only)" if self.draft_value else "public"
        self.stdout.write(self.style.SUCCESS(
            f"edition {book.edition_id!r} of {book.slug!r} is now {state}"))
