"""Generate read-along tracks. The only place synthesis ever happens.

    python manage.py generate_readalong rtc --section ch1/s2

The text comes from a `--clozes key` render of the section, which the host
imports alongside the published `--clozes blank` artifact and never serves. Key
mode is the one that carries the answers, marks them, and stages the complete
figure artwork; blank mode strips all three on purpose.
"""

import json

from django.core.management.base import BaseCommand, CommandError

from parody_web import printing
from parody_web.models import Book, Section

from ...generate import EstimatedSynth, PollySynth, build_track
from ...models import ReadAlongTrack
from ...speech import SkipMath, SreMath
from ...storage import write_audio


def key_html_index(path):
    """Map section key -> key-mode HTML, read straight from an artifact file.

    Lets a host run read-along without importing the key artifact into its
    database at all: the file is built alongside the published one and read
    here, at generation time, on the machine doing the generating. Nothing
    about it is ever served.
    """
    data = json.loads(path.read_text())
    index = {}

    def walk(node, chapter=None):
        if isinstance(node, dict):
            if isinstance(node.get("sections"), list):
                for section in node["sections"]:
                    walk(section, node.get("slug"))
                return
            if node.get("html") is not None and node.get("slug"):
                key = node.get("hash") or f"{chapter}/{node['slug']}"
                index[key] = node["html"]
                index[f"{chapter}/{node['slug']}"] = node["html"]
            for value in node.values():
                walk(value, chapter)
        elif isinstance(node, list):
            for value in node:
                walk(value, chapter)

    walk(data)
    return index


def key_mode_html(section):
    """The section's `--clozes key` HTML, or "" if the host never imported it.

    Deliberately returns empty rather than falling back to the published
    blank-mode HTML: that has no answers in it, so read-along would generate a
    track whose blanks reveal nothing, and the failure would only show up in
    front of a student.
    """
    return getattr(section, "key_html", "") or ""


class Command(BaseCommand):
    help = "Synthesise read-along audio and timings for a book's sections."

    def add_arguments(self, parser):
        parser.add_argument("book_slug")
        parser.add_argument("--section", default=None,
                            help="Section.key; omit for every section")
        parser.add_argument("--voice", default="Matthew")
        parser.add_argument("--engine", default="neural",
                            choices=["neural", "standard"])
        parser.add_argument("--skip-math", action="store_true",
                            help="Do not shell out to SRE; leave math silent.")
        parser.add_argument("--force", action="store_true",
                            help="Re-synthesise even if a track exists.")
        parser.add_argument("--key-artifact", default=None,
                            help="Path to a `--clozes key` artifact to take "
                                 "section text from, instead of "
                                 "Section.key_html. Never served.")
        parser.add_argument("--no-audio", action="store_true",
                            help="Estimate timings at reading pace and store "
                                 "no audio. For judging the interaction "
                                 "without AWS; the viewer drives itself from "
                                 "a clock.")
        parser.add_argument("--wpm", type=int, default=150,
                            help="Reading pace for --no-audio.")
        parser.add_argument("--dry-run", action="store_true",
                            help="Report what would be synthesised, and the "
                                 "character count, without calling Polly.")

    def handle(self, *args, **options):
        book = Book.objects.filter(slug=options["book_slug"]).first()
        if book is None:
            raise CommandError(f"no book {options['book_slug']!r}")

        # `Section.key` is a property, not a column — it prefers the authored
        # short hash and falls back to the chapter/section slug pair — so
        # selecting by it has to happen in Python.
        sections = list(Section.objects.filter(book=book)
                        .select_related("chapter"))
        if options["section"]:
            wanted = options["section"]
            sections = [s for s in sections if s.key == wanted]
        if not sections:
            raise CommandError("no matching sections")

        from pathlib import Path
        keys = {}
        if options["key_artifact"]:
            path = Path(options["key_artifact"])
            if not path.exists():
                raise CommandError(f"no such artifact: {path}")
            keys = key_html_index(path)
            self.stdout.write(f"key artifact: {len(keys)} section entries")

        math = SkipMath() if options["skip_math"] else SreMath()
        if options["dry_run"]:
            synth = _counting_synth()
        elif options["no_audio"]:
            synth = EstimatedSynth(wpm=options["wpm"])
        else:
            synth = PollySynth(voice_id=options["voice"],
                               engine=options["engine"])

        made = skipped = 0
        for section in sections:
            slice_key = printing.slice_key_for(book, section)
            if not slice_key:
                self.stderr.write(f"skip {section.key}: no section pdf")
                skipped += 1
                continue

            exists = ReadAlongTrack.objects.filter(
                book_slug=book.slug, edition_id=book.edition_id or "",
                section_key=section.key, slice_key=slice_key,
                voice_id=options["voice"]).exists()
            if exists and not options["force"]:
                self.stdout.write(f"have {section.key}")
                skipped += 1
                continue

            html = keys.get(section.key) or key_mode_html(section)
            if not html:
                self.stderr.write(
                    f"skip {section.key}: no key-mode html imported "
                    "(build the artifact with --clozes key)")
                skipped += 1
                continue

            pdf_path = printing.section_pdf_path(book, section)
            if pdf_path is None or not pdf_path.exists():
                self.stderr.write(f"skip {section.key}: section pdf missing")
                skipped += 1
                continue

            track = build_track(html, pdf_path.read_bytes(), synth, math=math)

            if options["dry_run"]:
                self.stdout.write(
                    f"would make {section.key}: {len(track['text'])} chars, "
                    f"{len(track['clozes'])} blanks")
                continue

            # No audio means no file: the endpoint 404s and the client falls
            # back to its clock, which is exactly what a preview should do.
            name = ""
            if track["audio_bytes"]:
                name = f"{slice_key}-{options['voice']}.mp3"
                write_audio(name, track["audio_bytes"])
            ReadAlongTrack.objects.update_or_create(
                book_slug=book.slug, edition_id=book.edition_id or "",
                section_key=section.key, slice_key=slice_key,
                voice_id=options["voice"],
                defaults={"engine": options["engine"], "audio_name": name,
                          "duration_ms": track["duration_ms"],
                          "words": track["words"], "clozes": track["clozes"],
                          "pages": track["pages"]})
            made += 1
            self.stdout.write(
                f"made {section.key}: {len(track['words'])} words, "
                f"{len(track['clozes'])} blanks")

        self.stdout.write(f"{made} made, {skipped} skipped")


def _counting_synth():
    """A stand-in that produces no audio and no marks, for --dry-run."""
    def synth(text):
        return b"", []
    return synth
