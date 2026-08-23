"""Upload already-generated read-along audio into the configured bucket.

    python manage.py sync_readalong_audio [--dry-run] [--from DIR]

The audio a box has already paid Polly for is MOVED, not re-bought. `text_key`
exists precisely so that unchanged words are never synthesised twice, and
regenerating a book to relocate its files would spend money on audio that is
byte-identical to what is already on disk.

Read the `missing` count. A row whose file is not on disk is a track that would
404 for a reader today; the sync is where that becomes visible rather than
being discovered by someone pressing play.

Local files are left where they are. This change should be reversible by
setting PARODY_WEB_READALOUD_BUCKET back to "".
"""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from ... import storage
from ...models import ReadAlongTrack


class Command(BaseCommand):
    help = "Upload generated read-along audio from local disk into S3."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Report what would be uploaded and upload nothing.")
        parser.add_argument(
            "--from", dest="source", default="",
            help="Directory to read from (default: "
                 "PARODY_WEB_READALOUD_CACHE).")

    def handle(self, *args, **options):
        store = storage.backend()
        if not isinstance(store, storage.S3Audio):
            raise CommandError(
                "PARODY_WEB_READALOUD_BUCKET is unset; there is nowhere to "
                "sync to. Set it first.")

        where = options["source"] or getattr(
            settings, "PARODY_WEB_READALOUD_CACHE", "")
        if not where:
            raise CommandError(
                "No source directory: pass --from, or set "
                "PARODY_WEB_READALOUD_CACHE to where the audio is now.")
        source = Path(where)

        names = sorted(set(
            ReadAlongTrack.objects.exclude(audio_name="")
            .values_list("audio_name", flat=True)))
        if not names:
            self.stdout.write("no tracks carry audio; nothing to sync")
            return

        counts = {"uploaded": 0, "present": 0, "missing": 0}
        for name in names:
            try:
                storage.safe_name(name)
            except ValueError as error:
                counts["missing"] += 1
                self.stderr.write(f"skipped {name!r}: {error}")
                continue

            if store.exists(name):
                counts["present"] += 1
                continue

            local = source / name
            if not local.is_file():
                counts["missing"] += 1
                self.stderr.write(
                    f"{name}: no file at {local} — this track would 404")
                continue

            if options["dry_run"]:
                self.stdout.write(f"would upload {name} ({local.stat().st_size} B)")
            else:
                store.write(name, local.read_bytes())
                self.stdout.write(f"uploaded {name}")
            counts["uploaded"] += 1

        verb = "would upload" if options["dry_run"] else "uploaded"
        self.stdout.write(
            f"{verb} {counts['uploaded']}, already there {counts['present']}, "
            f"missing from disk {counts['missing']}")
