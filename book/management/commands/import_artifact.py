"""Import a parody artifact JSON into the book-host DB.

Feed it the partial (``parody build --online-only``) artifact for a public
copyright-restricted book: the full text never enters this database. Upsert by
slug so re-imports are idempotent and stable.
"""
import json

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from book.models import Book, Chapter, Section


class Command(BaseCommand):
    help = "Import a parody artifact JSON into the book-host database."

    def add_arguments(self, parser):
        parser.add_argument("artifact", help="path to the parody artifact JSON")
        parser.add_argument(
            "--slug", help="book slug (defaults to the artifact's slug or filename)"
        )

    def handle(self, *args, **opts):
        path = opts["artifact"]
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            raise CommandError(f"could not read artifact {path}: {e}")

        version = data.get("schema_version", 0)
        if not isinstance(version, int) or version < 2:
            self.stderr.write(self.style.WARNING(
                f"artifact schema_version {version!r}: this host targets v2 "
                "(textbooks); importing what it can."))

        slug = opts.get("slug") or data.get("slug") or path.rsplit("/", 1)[-1][:-5]

        with transaction.atomic():
            self._import(slug, data)

    def _import(self, slug, data):
        book, _ = Book.objects.update_or_create(slug=slug, defaults={
            "title": data.get("title", slug),
            "description": data.get("description", ""),
            "authors": data.get("author", []),
            "book_metadata": data.get("book"),
            "videos": data.get("videos"),
            "apocrypha": data.get("apocrypha"),
            "source_commit": data.get("source_commit") or "",
            "built_at": data.get("built_at") or "",
        })

        seen_ch, seen_sec = set(), set()
        for ci, ch in enumerate(data.get("chapters", [])):
            chapter, _ = Chapter.objects.update_or_create(
                book=book, slug=ch["slug"], defaults={
                    "title": ch.get("title", ""),
                    "order": ci + 1,
                    "hash": ch.get("hash", ""),
                    "appendix": bool(ch.get("appendix", False)),
                })
            seen_ch.add(chapter.slug)
            for si, sec in enumerate(ch.get("sections", [])):
                Section.objects.update_or_create(
                    book=book, chapter=chapter, slug=sec["slug"], defaults={
                        "title": sec.get("title", ""),
                        "order": si + 1,
                        "hash": sec.get("hash", ""),
                        "html": sec.get("html", ""),
                        "online_resources": sec.get("online_resources", ""),
                        "online_only": bool(sec.get("online_only", False)),
                        "anchors": sec.get("anchors", []),
                    })
                seen_sec.add((chapter.slug, sec["slug"]))

        # prune rows no longer in the artifact
        for sec in book.sections.all():
            if (sec.chapter.slug, sec.slug) not in seen_sec:
                sec.delete()
        for ch in book.chapters.all():
            if ch.slug not in seen_ch:
                ch.delete()

        n_sec = book.sections.count()
        self.stdout.write(self.style.SUCCESS(
            f"imported '{book.title}' ({slug}): {book.chapters.count()} chapters, "
            f"{n_sec} sections"))
