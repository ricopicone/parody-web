"""Generate read-along tracks. The only place synthesis ever happens.

    python manage.py generate_readalong rtc --section ch1/s2

The text comes from a `--clozes key` render of the section, which the host
imports alongside the published `--clozes blank` artifact and never serves. Key
mode is the one that carries the answers, marks them, and stages the complete
figure artwork; blank mode strips all three on purpose.

Three things can happen to a section, and only one of them costs money:

  same pages, same words   -> `have`, nothing done
  new pages, same words    -> `moved`, re-aligned for free and the mp3 kept
  new words                -> `made`, synthesised

That middle case is why editing chapter 1 no longer re-buys chapter 12. Reflow
cascades through a book, so `printing.slice_key_for` moves for nearly every
later section; `generate.text_key_for` does not, and the audio is keyed on it.

Which is also why `--force` should NOT be the habit. It re-buys everything,
including the sections whose text is untouched, and is for when the generator
itself changed. To redo one section after editing it, name it: `--section`.

When the ALIGNER changes, `--realign` is the flag: the pages have not moved, so
every section reports `have` and nothing happens, and `--force` would spend a
book's worth of Polly to correct geometry that is free to recompute. It re-boxes
what is already there and cannot call the engine at all.
"""

import copy
import json
import sys

from django.core.management.base import BaseCommand, CommandError

from parody_web import printing
from parody_web.models import Book, Section

from ... import refs
from ...generate import (EstimatedSynth, PollySynth, cloze_count, prepare,
                         reuse, synthesise, text_key_for)
from ...models import ReadAlongTrack
from ...speech import SkipMath, SreMath, sre_available
from ...storage import write_audio


def key_html_index(path):
    """Map section key -> key-mode HTML, read straight from an artifact file.

    Lets a host run read-along without importing the key artifact into its
    database at all: the file is built alongside the published one and read
    here, at generation time, on the machine doing the generating. Nothing
    about it is ever served.

Cross-references are resolved to the text a reader would SEE — "Equation
    (4.1)", not "eq:v_plus_minus" — but ONLY the reference spans are rewritten.

    Running the whole numbering pass and reading its output was tried twice and
    corrupted the section in production both times, on evidence that looked
    clean locally (see the numbering note in project memory). So the pass is
    still run, on a throwaway copy, purely to obtain its map of keys to printed
    labels; the html actually read is the html that was built, with reference
    spans swapped for their labels and nothing else touched.
    """
    data = json.loads(path.read_text())
    try:
        labels = refs.label_map(data)
    except Exception as err:                       # noqa: BLE001
        sys.stderr.write(
            f"warning: could not resolve references in {path.name} ({err}); "
            "they will be read aloud as their keys\n")
        labels = {}

    index = _index_sections(data)
    return {key: refs.resolve_refs(html, labels)
            for key, html in index.items()}


def _index_sections(data):
    """section key -> html, for whichever artifact we ended up with."""
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
                            help="Re-synthesise even where the words are "
                                 "unchanged. For when the generator changed; "
                                 "an edit needs only --section.")
        parser.add_argument("--respeak", action="store_true",
                            help="Re-read the script and buy audio ONLY where "
                                 "the spoken text actually changed. For when "
                                 "the way maths is SPOKEN changed: nothing "
                                 "moved on the page, so the cheap exit would "
                                 "report `have` for the whole book.")
        parser.add_argument("--realign", action="store_true",
                            help="Re-box existing tracks against the pages "
                                 "they already sit on, keeping their audio. "
                                 "For when the ALIGNER changed: --force would "
                                 "re-buy recordings that are already right. "
                                 "Never calls the engine.")
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
        parser.add_argument("--include-drafts", action="store_true",
                            help="also voice chapters marked draft (for "
                                 "hearing one before releasing it). Needs a "
                                 "print PDF built WITH drafts; the ordinary "
                                 "build omits them, so their sections have no "
                                 "page range to align against.")
        parser.add_argument("--dry-run", action="store_true",
                            help="Report what would be synthesised and what "
                                 "would merely be re-aligned, with the "
                                 "character count, without calling Polly.")

    def handle(self, *args, **options):
        book = Book.objects.filter(slug=options["book_slug"]).first()
        if book is None:
            raise CommandError(f"no book {options['book_slug']!r}")

        # `Section.key` is a property, not a column — it prefers the authored
        # short hash and falls back to the chapter/section slug pair — so
        # selecting by it has to happen in Python.
        # A DRAFT chapter is not released, so it is not voiced. Its sections
        # are already absent from the print PDF and _one would skip each one
        # with "no section pdf" — but that protection is incidental, inherited
        # from print, and would evaporate the moment a preview PDF included
        # drafts. Filtering here states the intent and avoids opening the PDF
        # once per unreleased section.
        #
        # Nothing detects the moment a chapter is published: a released chapter
        # simply appears in this queryset on the next run, and _one's cheap exit
        # skips everything already voiced. So re-running after a publish costs
        # only the new chapter.
        qs = Section.objects.filter(book=book).select_related("chapter")
        if not options["include_drafts"]:
            qs = qs.exclude(chapter__draft=True)
        sections = list(qs)
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

        if options["skip_math"]:
            math = SkipMath()
        else:
            # Ask BEFORE synthesising a book's worth of audio. SreMath treats
            # every failure as silence, so a misconfigured host would otherwise
            # produce every track with its equations missing, at full cost, and
            # say nothing about it.
            ok, why = sre_available()
            if not ok:
                raise CommandError(
                    f"maths cannot be spoken here: {why}\n"
                    "Point PARODY_WEB_READALOUD_SRE at a speak.mjs whose npm "
                    "dependencies resolve (see docs/host-integration.md), or "
                    "pass --skip-math to accept silent equations.")
            math = SreMath()
        synth = None
        if options["no_audio"]:
            synth = EstimatedSynth(wpm=options["wpm"])
        elif not options["dry_run"]:
            synth = PollySynth(voice_id=options["voice"],
                               engine=options["engine"])

        made = moved = skipped = 0
        for section in sections:
            outcome = self._one(book, section, keys, synth, math, options)
            if outcome == "made":
                made += 1
            elif outcome == "moved":
                moved += 1
            else:
                skipped += 1

        self.stdout.write(f"{made} made, {moved} moved, {skipped} skipped")

    def _one(self, book, section, keys, synth, math, options):
        """Bring one section up to date. Returns made | moved | skipped."""
        voice, engine = options["voice"], options["engine"]

        slice_key = printing.slice_key_for(book, section)
        if not slice_key:
            self.stderr.write(f"skip {section.key}: no section pdf")
            return "skipped"

        rows = ReadAlongTrack.objects.filter(
            book_slug=book.slug, edition_id=book.edition_id or "",
            section_key=section.key, voice_id=voice)

        # The cheap exit, and the common one: this exact pagination is already
        # done and already carries a text key, so there is nothing to learn by
        # parsing the section. A row with no text key predates the split and is
        # worth preparing for, to stamp one on.
        # --realign has to pass this exit by definition: the pagination is
        # unchanged, which is exactly the case the exit exists to skip, and
        # the boxes are what it has come to redo.
        # --respeak has to pass it too, and for a subtler reason than
        # --realign: the exit tests that a text key EXISTS, never that it still
        # describes the script. A change in how maths is spoken moves no page,
        # so every section would report `have` and the new narration would
        # never be bought. Past the exit the ordinary logic is already right —
        # a section whose text really did change finds no prior and is
        # synthesised; one whose text did not is re-boxed for nothing.
        exact = rows.filter(slice_key=slice_key).first()
        if (exact is not None and exact.text_key and not options["force"]
                and not options["realign"] and not options["respeak"]):
            self.stdout.write(f"have {section.key}")
            return "skipped"

        html = keys.get(section.key) or key_mode_html(section)
        if not html:
            self.stderr.write(
                f"skip {section.key}: no key-mode html imported "
                "(build the artifact with --clozes key)")
            return "skipped"

        pdf_path = printing.section_pdf_path(book, section)
        if pdf_path is None or not pdf_path.exists():
            self.stderr.write(f"skip {section.key}: section pdf missing")
            return "skipped"

        prep = prepare(html, pdf_path.read_bytes(), math=math)
        text_key = text_key_for(prep.text, voice, engine)

        if exact is not None and not options["force"] \
                and not options["realign"] and not options["respeak"]:
            # Nothing moved and nothing changed; the row simply never learned
            # its own text key. Stamp it so the NEXT reflow can reuse it.
            #
            # Not under --respeak: there the text may well have changed, and
            # stamping the NEW key onto the OLD recording would label audio
            # nobody has made as audio already made.
            if not options["dry_run"]:
                exact.text_key = text_key
                exact.token_count = len(prep.tokens)
                exact.save(update_fields=["text_key", "token_count"])
            self.stdout.write(f"have {section.key} (text key recorded)")
            return "skipped"

        # A preview track (--no-audio) and a bought one are different products
        # that hash alike: same words, same voice, same engine. Reusing one for
        # the other would quietly hand a class estimated timings and no sound,
        # or hand a preview run audio it did not ask for.
        wants_audio = not options["no_audio"]
        prior = (None if options["force"]
                 else self._prior(rows, text_key, wants_audio, prep, section))

        if options["dry_run"]:
            if prior is not None:
                self.stdout.write(
                    f"would move {section.key}: same words, re-align only")
            else:
                self.stdout.write(
                    f"would make {section.key}: {len(prep.text)} chars, "
                    f"{cloze_count(prep)} blanks")
            return "skipped"

        # A re-alignment that cannot reuse must stop, not fall through: the
        # whole point of the flag is that it cannot spend money, and a silent
        # slide into synthesis would re-buy the book at the moment an operator
        # believed they were only moving boxes.
        if options["realign"] and prior is None:
            self.stderr.write(
                f"skip {section.key}: nothing to re-align onto "
                "(no stored timings for these words); leave it to a run "
                "without --realign")
            return "skipped"

        track = reuse(prep, prior.words) if prior is not None else None
        if track is None:
            if options["realign"]:
                self.stderr.write(
                    f"skip {section.key}: stored timings do not fit this "
                    "script; leave it to a run without --realign")
                return "skipped"
            if prior is not None:
                # Belt and braces behind the token-count guard: a stored token
                # that does not index this script would silently box words in
                # the wrong place, which is worse than paying for the audio.
                self.stderr.write(
                    f"{section.key}: stored timings do not fit this script; "
                    "synthesising")
                prior = None
            track = synthesise(prep, synth)

        if prior is not None:
            # The audio is byte-identical to what it was, so it keeps its file.
            audio_name, duration = prior.audio_name, prior.duration_ms
        else:
            # No audio means no file: the endpoint 404s and the client falls
            # back to its clock, which is exactly what a preview should do.
            #
            # Named from the TEXT key, not the slice key: the file is the same
            # recording whatever page it now sits on, and two paginations of
            # one section share it rather than storing it twice.
            audio_name, duration = "", track["duration_ms"]
            if track["audio_bytes"]:
                audio_name = f"{text_key}-{voice}.mp3"
                write_audio(audio_name, track["audio_bytes"])

        ReadAlongTrack.objects.update_or_create(
            book_slug=book.slug, edition_id=book.edition_id or "",
            section_key=section.key, slice_key=slice_key, voice_id=voice,
            defaults={"engine": engine, "audio_name": audio_name,
                      "text_key": text_key,
                      "token_count": track["token_count"],
                      "duration_ms": duration,
                      "words": track["words"], "clozes": track["clozes"],
                      "pages": track["pages"],
                      "regions": track["regions"]})

        if prior is not None:
            self.stdout.write(
                f"moved {section.key}: {len(track['words'])} words re-boxed, "
                "audio reused")
            return "moved"
        self.stdout.write(
            f"made {section.key}: {len(track['words'])} words, "
            f"{len(track['clozes'])} blanks")
        return "made"

    def _prior(self, rows, text_key, wants_audio, prep, section):
        """A previous track of these exact words, if one survives a check.

        The words were spoken in the order the script fixes and every stored
        word carries the token that said it, so timings and geometry separate
        cleanly. What that rests on is a stable parse: same text in, same token
        indices out. `text_key` IS the hash of that text, so it holds by
        construction — but a figure cloze is never spoken, so a token stream
        CAN move underneath identical spoken text. Check rather than trust.
        """
        for row in rows.filter(text_key=text_key):
            if not row.words or bool(row.audio_name) != wants_audio:
                continue
            if row.token_count == len(prep.tokens):
                return row
            self.stderr.write(
                f"{section.key}: a track with the same words parsed to "
                f"{row.token_count} tokens, not {len(prep.tokens)}; "
                "synthesising rather than reusing its timings")
        return None
