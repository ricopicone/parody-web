"""Translated twin PDFs (parody twin): the sidecar a twin arrives with.

parody writes ``<twin>.twin.json`` beside each twin PDF. Validation is the
sha256 of the bytes, never a parse of the PDF, so it needs no pypdf.
"""

import hashlib
import json
from pathlib import Path

from . import printing

SIDECAR_SCHEMA = 1

# The languages parody translates into, by the code its CLI takes, with the
# name each is known by to its own readers (what the language list shows).
LANGUAGE_NAMES = {
    "de": "Deutsch",
    "es": "Español",
    "fr": "Français",
    "ko": "한국어",
    "zh": "中文",
}


def _basename(name, what):
    if not isinstance(name, str) or not name or Path(name).name != name or "\\" in name:
        raise ValueError(f"{what} must be a bare file name, not {name!r}")
    return name


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _ranges(sections):
    if not isinstance(sections, dict):
        raise ValueError("sections must map chapter/section to [first, last]")
    for key, pages in sections.items():
        if (not isinstance(pages, list) or len(pages) != 2
                or not all(isinstance(p, int) for p in pages)
                or not 1 <= pages[0] <= pages[1]):
            raise ValueError(f"section {key!r} has no valid page range: {pages!r}")
    return sections


def load_sidecar(path):
    """``(data, warnings)`` for the twin sidecar at ``path``.

    Raises ValueError, with the reason, when the twin cannot be served: an
    unreadable sidecar, another schema, a language parody does not translate
    into, no print root, or a PDF that is missing or is not the one the sidecar
    describes. A side-by-side file that is missing only drops that file, with
    a warning: the twin itself is still good.
    """
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ValueError(f"could not read it: {e}")
    if not isinstance(data, dict) or data.get("schema") != SIDECAR_SCHEMA:
        raise ValueError(f"schema {data.get('schema') if isinstance(data, dict) else None!r}, "
                         f"this host reads {SIDECAR_SCHEMA}")
    if data.get("language") not in LANGUAGE_NAMES:
        raise ValueError(f"unknown language {data.get('language')!r}")
    root = printing.print_root()
    if root is None:
        raise ValueError("PARODY_WEB_PRINT_ROOT is not set")
    pdf = root / _basename(data.get("pdf"), "pdf")
    if not pdf.is_file():
        raise ValueError(f"{pdf} does not exist")
    if _sha256(pdf) != data.get("sha256"):
        raise ValueError(f"{pdf} is not the PDF the sidecar describes (sha256 differs)")
    _ranges(data.get("sections"))
    warnings = []
    sbs = data.get("side_by_side")
    if sbs:
        if not (root / _basename(sbs, "side_by_side")).is_file():
            warnings.append(f"side-by-side {sbs} does not exist; serving the twin without it")
            data["side_by_side"] = None
    try:
        data["key"] = _key(root, data.get("key"))
    except ValueError as e:
        warnings.append(f"key twin: {e}; serving the twin without it")
        data["key"] = None
    return data, warnings


def _key(root, key):
    """The sidecar's ``key`` entry (parody twin --key), checked as the twin is:
    None when there is none. Raises ValueError when it names a key that is
    missing or is not the PDF it describes — which drops only the key."""
    if not key:
        return None
    if not isinstance(key, dict):
        raise ValueError(f"not a description of one: {key!r}")
    pdf = root / _basename(key.get("pdf"), "key pdf")
    if not pdf.is_file():
        raise ValueError(f"{pdf} does not exist")
    if _sha256(pdf) != key.get("sha256"):
        raise ValueError(f"{pdf} is not the PDF the sidecar describes (sha256 differs)")
    sbs = key.get("side_by_side")
    if sbs and not (root / _basename(sbs, "key side_by_side")).is_file():
        sbs = None
    return {"pdf": pdf.name, "sha256": key["sha256"], "side_by_side": sbs or None}
