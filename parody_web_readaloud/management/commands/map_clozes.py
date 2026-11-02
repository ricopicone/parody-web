"""Record where each section's blanks sit on its PDF. Free: no speech, no Polly.

    python manage.py map_clozes electronics --key-artifact electronics-key.json

A read-along track knows where its section's blanks are, but a book without
read-along has no tracks. This writes the same boxes (`ClozeMap`) for every
released section of any blanked book, so a host can measure a student's notes
against the blanks whether or not anyone has paid for the audio.

Idempotent like generate_readalong, so it is safe on every deploy: a section
whose pagination is already mapped reports `have` and is not parsed. A reflow
changes the slice key, and the new pages get a map of their own beside the
old one, which still describes the ink students wrote on those older pages.
"""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from parody_web import printing
from parody_web.models import Book, Section

from ...generate import cloze_boxes
from ...models import ClozeMap
from .generate_readalong import key_html_index, key_mode_html


class Command(BaseCommand):
    help = "Record where each section's blanks sit on its PDF (no audio)."

    def add_arguments(self, parser):
        parser.add_argument("book_slug")
        parser.add_argument("--section", default=None,
                            help="Only this section key (hash or ch/sec).")
        parser.add_argument("--key-artifact", default=None,
                            help="Path to a `--clozes key` artifact to take "
                                 "section text from, instead of "
                                 "Section.key_html.")
        parser.add_argument("--force", action="store_true",
                            help="Re-map sections already mapped at this "
                                 "pagination (after an aligner change).")

    def handle(self, *args, **options):
        book = Book.objects.filter(slug=options["book_slug"]).first()
        if book is None:
            raise CommandError(f"no book {options['book_slug']!r}")

        # Drafts are not printed, so they have no PDF to map — and are not
        # released, so no student writes on them.
        sections = list(Section.objects.filter(book=book).exclude(draft=True)
                        .select_related("chapter"))
        if options["section"]:
            sections = [s for s in sections if s.key == options["section"]]
        if not sections:
            raise CommandError("no matching sections")

        keys = {}
        if options["key_artifact"]:
            path = Path(options["key_artifact"])
            if not path.exists():
                raise CommandError(f"no such artifact: {path}")
            keys = key_html_index(path)

        mapped = have = skipped = 0
        for section in sections:
            outcome = self._one(book, section, keys, options["force"])
            if outcome == "mapped":
                mapped += 1
            elif outcome == "have":
                have += 1
            else:
                skipped += 1
        self.stdout.write(f"{mapped} mapped, {have} unchanged, {skipped} skipped")

    def _one(self, book, section, keys, force):
        slice_key = printing.slice_key_for(book, section)
        if not slice_key:
            return "skipped"                     # not in the print PDF
        where = dict(book_slug=book.slug, edition_id=book.edition_id or "",
                     section_key=section.key, slice_key=slice_key)
        if not force and ClozeMap.objects.filter(**where).exists():
            return "have"

        # Key mode is the build that marks each answer. The blank build's
        # empty placeholders leave nothing to align a blank to its words by.
        html = keys.get(section.key) or key_mode_html(section)
        if not html:
            self.stderr.write(f"skip {section.key}: no key-mode html imported "
                              "(build the artifact with --clozes key)")
            return "skipped"
        pdf_path = printing.section_pdf_path(book, section)
        if pdf_path is None or not pdf_path.exists():
            self.stderr.write(f"skip {section.key}: section pdf missing")
            return "skipped"

        boxes = cloze_boxes(html, pdf_path.read_bytes())
        ClozeMap.objects.update_or_create(**where, defaults={"clozes": boxes})
        self.stdout.write(f"mapped {section.key}: {len(boxes)} blanks")
        return "mapped"
