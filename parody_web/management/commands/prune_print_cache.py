"""Remove print cache files nothing can reach any more.

Everything under the print cache is derived: cut on demand from files kept
elsewhere (the book PDF and its twins in the print root, older versions in
the print archive) and cut again by the next request that wants it. But a
file is only ever looked up by the hash of what it was cut from, so every
release leaves the previous release's files behind, unread, for good — and
an annotated copy is named by the reader's ink, so each new stroke leaves the
last copy behind too. This removes those:

- a book's section cuts from any build but the current one (``<sha12>/``),
  and everything of a book no longer imported;
- the cuts, side-by-side cuts and paired PDFs of any twin but the book's
  current ones (``twin-<lang>-<sha12>[-sbs|-paired]/``);
- cuts of an archived version (``v<sha12>/``) once the version is gone from
  the archive, or older than ``--max-age-days`` (the archive cuts it again);
- annotated copies (``annotated/``, ``annotated-book/``) superseded by a newer
  copy of the same pages, cut from an older build, or older than
  ``--max-age-days`` (the next download composites it again);
- temporary files an interrupted write left.

What it does not recognise it reports and leaves. A file written in the last
few minutes is never touched: a request that read the book before an import
may still be writing it. Safe to run at any time, which is why the deploy
runs it after every import.
"""

import re
import time
from collections import defaultdict
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from parody_web import printing
from parody_web.models import Book

GRACE_SECONDS = 600
_SHA = r"[0-9a-f]{12}"
_BUILD = re.compile(_SHA)
_VERSION = re.compile(rf"v{_SHA}")
_TWIN = re.compile(rf"(twin-[a-z]{{2,3}}-{_SHA})(?:-sbs|-paired)?")
_STAMPED = re.compile(rf"(.+)-({_SHA})\.pdf")


def _inside(path, parent):
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


class Command(BaseCommand):
    help = "Remove print cache files nothing can reach any more (all of it is cut again on demand)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="report what would go, delete nothing")
        parser.add_argument("--max-age-days", type=float, default=30,
                            help="annotated copies and archived-version cuts older than this go too")

    def handle(self, *args, **options):
        cache = printing.print_cache_root()
        archive = printing.print_archive_root()
        if cache is not None and archive is not None and _inside(archive, cache):
            raise CommandError(f"the print archive {archive} is inside the cache {cache}: "
                               "refusing, since it holds the only copy of older versions")
        root = printing.print_root()
        if cache is not None and root is not None and cache.resolve() == root.resolve():
            raise CommandError("the print cache is the print root itself: refusing")
        if cache is None or not cache.is_dir():
            self.stdout.write("no print cache; nothing to prune")
            return

        now = time.time()
        self.cutoff = now - options["max_age_days"] * 86400
        self.grace = now - GRACE_SECONDS
        self.doomed = defaultdict(list)  # reason -> [path]
        self.unknown = []

        for book_dir in sorted(p for p in cache.iterdir() if p.is_dir() and not p.is_symlink()):
            if book_dir.name == "annotated":
                self._annotated(book_dir)
            elif book_dir.name == "annotated-book":
                self._annotated_books(book_dir)
            else:
                for ed_dir in sorted(p for p in book_dir.iterdir() if p.is_dir()):
                    self._edition(book_dir.name, ed_dir)
        for tmp in cache.rglob("*.tmp"):
            self._doom(tmp, "interrupted write")

        self._report_and_apply(cache, options["dry_run"])

    # -- what goes ---------------------------------------------------------

    def _doom(self, path, reason):
        if path.is_file() and not path.is_symlink() and path.stat().st_mtime < self.grace:
            self.doomed[reason].append(path)

    def _doom_tree(self, directory, reason):
        for path in directory.rglob("*"):
            self._doom(path, reason)

    def _edition(self, slug, ed_dir):
        edition = "" if ed_dir.name == "_" else ed_dir.name
        book = Book.objects.filter(slug=slug, edition_id=edition).first()
        if book is None:
            self._doom_tree(ed_dir, "book no longer imported")
            return
        current = (book.print_sha256 or "")[:12]
        twins = {f"twin-{t.language}-{t.sha256[:12]}" for t in book.twins.all()}
        archived = set()
        for version in book.print_versions.all():
            path = printing.archived_pdf_path(book.slug, version.sha256)
            if path is not None and path.is_file():
                archived.add(f"v{version.sha256[:12]}")
        for d in sorted(p for p in ed_dir.iterdir()):
            name = d.name
            if not d.is_dir() or d.is_symlink():
                self.unknown.append(d)
            elif name == current:
                continue
            elif _BUILD.fullmatch(name):
                self._doom_tree(d, "older build")
            elif m := _TWIN.fullmatch(name):
                if m.group(1) not in twins:
                    self._doom_tree(d, "older twin")
            elif _VERSION.fullmatch(name):
                if name not in archived:
                    self._doom_tree(d, "version gone from the archive")
                else:
                    for path in d.rglob("*.pdf"):
                        if path.stat().st_mtime < self.cutoff:
                            self._doom(path, "archived-version cut past max age")
            else:
                self.unknown.append(d)

    def _annotated(self, top):
        """``annotated/<user>/<slug>/<pages>-<stamp>.pdf``: per pages, the
        newest copy stays while it is younger than the max age."""
        groups = defaultdict(list)
        for path in top.rglob("*.pdf"):
            m = _STAMPED.fullmatch(path.name)
            if m is None:
                self.unknown.append(path)
                continue
            groups[(path.parent, m.group(1))].append(path)
        for paths in groups.values():
            paths.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            newest, *older = paths
            for path in older:
                self._doom(path, "annotated copy superseded")
            if newest.stat().st_mtime < self.cutoff:
                self._doom(newest, "annotated copy past max age")

    def _annotated_books(self, top):
        """``annotated-book/<user>/<slug>/<sha12>-<stamp>.pdf``: the newest
        copy of the current build stays while it is younger than the max age."""
        current = defaultdict(set)
        for slug, sha in Book.objects.values_list("slug", "print_sha256"):
            current[slug].add((sha or "")[:12])
        for directory in {p.parent for p in top.rglob("*.pdf")}:
            slug = directory.name
            paths = sorted(directory.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
            kept = False
            for path in paths:
                sha = path.name[:12]
                if sha not in current.get(slug, ()):
                    self._doom(path, "annotated book from an older build")
                elif kept:
                    self._doom(path, "annotated copy superseded")
                elif path.stat().st_mtime < self.cutoff:
                    self._doom(path, "annotated copy past max age")
                else:
                    kept = True

    # -- doing it ----------------------------------------------------------

    def _report_and_apply(self, cache, dry_run):
        files = sum(len(v) for v in self.doomed.values())
        size = sum(p.stat().st_size for v in self.doomed.values() for p in v)
        for reason, paths in sorted(self.doomed.items()):
            mb = sum(p.stat().st_size for p in paths) / 1e6
            self.stdout.write(f"  {reason}: {len(paths)} files, {mb:.1f} MB")
        for path in self.unknown:
            self.stdout.write(f"  left alone (not a cache entry this knows): {path.relative_to(cache)}")
        verb = "would remove" if dry_run else "removed"
        if not dry_run:
            emptied = set()
            for paths in self.doomed.values():
                for path in paths:
                    path.unlink(missing_ok=True)
                    emptied.add(path.parent)
            self._remove_emptied_dirs(cache, emptied)
        self.stdout.write(f"{verb} {files} files, {size / 1e6:.1f} MB")

    def _remove_emptied_dirs(self, cache, emptied):
        """The directories this emptied, and their parents up to the cache, when
        empty: never one a request has just made and not yet written into."""
        candidates = set()
        for d in emptied:
            while d != cache and _inside(d, cache):
                candidates.add(d)
                d = d.parent
        for d in sorted(candidates, key=lambda p: len(p.parts), reverse=True):
            try:
                d.rmdir()  # only when empty: a file written since keeps it
            except OSError:
                pass
