"""Where generated audio lives.

Local disk under PARODY_WEB_READALOUD_CACHE, mirroring the print cache rather
than reaching for S3: the deploy already knows how to keep a directory, and the
same X-Accel arrangement can hand the file off to nginx.
"""

from pathlib import Path

from django.conf import settings


def cache_root() -> Path:
    value = getattr(settings, "PARODY_WEB_READALOUD_CACHE", "")
    if not value:
        raise RuntimeError(
            "PARODY_WEB_READALOUD_CACHE is unset; read-along cannot store or "
            "serve audio. Set it to a writable directory.")
    return Path(value)


def audio_path(name: str) -> Path:
    """Resolve a track's audio file inside the cache.

    Names are generated from slice_key and voice, never from user input, but
    the containment check stands anyway: a malformed row must not be able to
    read a file outside the cache directory.
    """
    if not name:
        raise ValueError("empty audio name")
    root = cache_root().resolve()
    path = (root / name).resolve()
    if path != root and root not in path.parents:
        raise ValueError(f"audio name escapes the cache root: {name!r}")
    return path


def write_audio(name: str, data: bytes) -> Path:
    path = audio_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path
