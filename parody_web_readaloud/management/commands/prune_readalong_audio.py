"""Remove generated audio that no track refers to any more.

    python manage.py prune_readalong_audio [--delete] [--older-than DAYS]

Editing a section changes its `text_key`, so `generate_readalong` writes a new
`<text_key>-<voice>.mp3` and updates the row to point at it. The file the row
used to name is then referred to by nothing, and nothing has ever removed it —
on disk or in the bucket. This is that missing half.

REPORTING IS THE DEFAULT. `--delete` is what actually removes anything.
Re-synthesising a section costs real money, so the failure this command must
never have is deleting audio that is still in use; a report that has to be run
twice is a much cheaper mistake than a bucket that has to be re-bought.

Three guards, and each one exists because the obvious version is wrong:

  * "Live" is every `audio_name` in the WHOLE table — not this book's, not this
    edition's. Audio is named from the text, so two editions of a section whose
    words are identical share one file, and a per-book prune would delete a
    file another book is still serving.
  * Only names of the shape the generator writes are ever candidates. Anything
    else under the root is REPORTED and left alone, because a bucket prefix is
    not necessarily this app's private property.
  * Nothing newer than `--older-than` days is touched. `generate_readalong`
    writes the file before it writes the row, so a file with no row may simply
    be a run that is still going.
"""

import re
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from ... import storage
from ...models import ReadAlongTrack

# Both naming eras: <64 hex>-<voice>.mp3, the key being a slice key on the
# oldest rows and a text key since 0.62.0. Nothing else was ever written.
GENERATED = re.compile(r"^[0-9a-f]{64}-[A-Za-z0-9_.-]+\.mp3$")

DEFAULT_OLDER_THAN = 7


def human(size):
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024


class Command(BaseCommand):
    help = "Report (or delete) read-along audio no track refers to."

    def add_arguments(self, parser):
        parser.add_argument(
            "--delete", action="store_true",
            help="Actually remove the stale files. Without this, report only.")
        parser.add_argument(
            "--older-than", type=int, default=DEFAULT_OLDER_THAN,
            metavar="DAYS",
            help=f"Never touch anything written in the last DAYS days "
                 f"(default {DEFAULT_OLDER_THAN}). 0 disables the hold-back.")
        parser.add_argument(
            "--force", action="store_true",
            help="Prune even when the database names no audio at all. Refused "
                 "by default: an empty table looks identical to a database "
                 "that is not the one this store belongs to.")

    def handle(self, *args, **options):
        try:
            store = storage.backend()
        except RuntimeError as error:
            raise CommandError(str(error))

        live = set(
            ReadAlongTrack.objects.exclude(audio_name="")
            .values_list("audio_name", flat=True))

        entries = list(store.entries())
        if not entries:
            self.stdout.write("no audio in the store; nothing to prune")
            return

        if not live and not options["force"]:
            raise CommandError(
                f"{len(entries)} files are in the store and NO track names "
                "any audio. That is what a fresh or wrong database looks like, "
                "and pruning here would delete everything. Pass --force if the "
                "table really is empty on purpose.")

        # 0 means no hold-back AT ALL, rather than "written before this
        # instant". The timestamp being compared is the STORE's, and S3's runs
        # ahead of ours — it rounds up to the second and the clocks differ, so
        # an object written moments ago reads as 0.6 s in the FUTURE. Compared
        # against a zero cutoff every fresh object is "too new" and a prune
        # that should have taken everything takes nothing. Measured, not
        # supposed.
        older_than = options["older_than"]
        cutoff = (timezone.now() - timedelta(days=older_than)
                  if older_than > 0 else None)
        kept = stale = young = foreign = 0
        kept_bytes = stale_bytes = 0

        for name, size, modified in entries:
            if name in live:
                kept += 1
                kept_bytes += size
                continue
            if not GENERATED.match(name):
                foreign += 1
                self.stderr.write(
                    f"left alone (not ours): {name} ({human(size)})")
                continue
            if cutoff is not None and modified > cutoff:
                young += 1
                self.stderr.write(
                    f"held back (written {modified:%Y-%m-%d}): {name}")
                continue

            stale += 1
            stale_bytes += size
            if options["delete"]:
                store.delete(name)
                self.stdout.write(f"deleted {name} ({human(size)})")
            else:
                self.stdout.write(f"stale {name} ({human(size)})")

        verb = "deleted" if options["delete"] else "would delete"
        self.stdout.write(
            f"{verb} {stale} ({human(stale_bytes)}); "
            f"in use {kept} ({human(kept_bytes)}); "
            f"too new to touch {young}; not ours {foreign}")
        if stale and not options["delete"]:
            self.stdout.write("re-run with --delete to remove them")
