"""Remove archived book PDFs nothing needs any more.

Deliberately manual and dry-run by default. The failure mode of getting this
wrong is deleting the document behind a reader's annotations — notes that
still render, on pages that can no longer be produced. That is worth a
deliberate keystroke.
"""

from django.core.management.base import BaseCommand

from parody_web import printing
from parody_web.models import Book, BookPrintVersion


def referenced_shas():
    """Versions some reader has ink on.

    Imported defensively: core does not depend on the annotator, and a
    deployment that has not installed it simply has nothing referencing.
    """
    try:
        from parody_web_annotate.models import InkLayer
    except Exception:  # noqa: BLE001 - not installed, or not migrated
        return set()
    return set(InkLayer.objects.values_list("book_sha256", flat=True))


class Command(BaseCommand):
    help = "Remove archived book PDFs that are neither current nor annotated."

    def add_arguments(self, parser):
        parser.add_argument(
            "--yes", action="store_true",
            help="actually delete; without it the command only reports")

    def handle(self, *args, **options):
        keep = set(Book.objects.exclude(print_sha256="")
                   .values_list("print_sha256", flat=True))
        keep |= referenced_shas()

        removed = kept = 0
        for version in BookPrintVersion.objects.select_related("book"):
            if version.sha256 in keep:
                kept += 1
                continue
            path = printing.archived_pdf_path(version.book.slug, version.sha256)
            if options["yes"]:
                if path and path.exists():
                    path.unlink()
                version.delete()
                self.stdout.write(f"removed {version.book.slug}@{version.sha256[:12]}")
                removed += 1
            else:
                self.stdout.write(
                    f"would remove {version.book.slug}@{version.sha256[:12]}")
                removed += 1

        verb = "removed" if options["yes"] else "would remove"
        self.stdout.write(f"{verb} {removed}, kept {kept}")
        if not options["yes"] and removed:
            self.stdout.write("re-run with --yes to delete")
