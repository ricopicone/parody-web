"""Write the GIF player's test fixtures and Pillow's verdict on every frame.

Run from the repo root:

    uv run --no-project --with pillow python assets/gifplayer/fixtures/make_fixtures.py

Each fixture is tiny and exercises one way a GIF can be put together. Pillow is
the reference: for every frame it reports `seek(i); convert("RGBA")`, the
composited picture, which the decoder must reproduce pixel for pixel. A pixel
with alpha 0 is normalised to 0,0,0,0 because its colour is meaningless and the
two decoders are free to disagree about it.

`offset.gif` and `interlaced.gif` are written by hand, because Pillow's writer
will not make them: it always writes a full-size first frame and a local palette
per frame, and it drops `interlace=True`. They are "uncompressed" GIFs: LZW with
a clear code often enough that the codes never grow.
"""
import hashlib
import json
import struct
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
W, H = 32, 24


def scene(i, n, w=W, h=H, bg=(240, 236, 228)):
    """A square sliding right over a fixed bar: most of each frame is
    unchanged, so an optimising writer emits small deltas."""
    im = Image.new("RGB", (w, h), bg)
    d = ImageDraw.Draw(im)
    d.rectangle([0, h - 4, w - 1, h - 1], fill=(40, 60, 90))
    x = 2 + i * (w - 10) // max(n - 1, 1)
    d.rectangle([x, 4, x + 6, 10], fill=(200 - 20 * i, 80, 30 + 25 * i))
    return im


def frames(n, **kw):
    return [scene(i, n, **kw) for i in range(n)]


def save(name, ims, **kw):
    ims[0].save(HERE / name, save_all=True, append_images=ims[1:], **kw)


# --- the hand-written GIF -------------------------------------------------

def _lzw_uncompressed(indices, min_code_size):
    """LZW that never builds a table: emit a clear code before the table would
    grow past the starting width, so every code is min_code_size+1 bits."""
    clear, end = 1 << min_code_size, (1 << min_code_size) + 1
    width = min_code_size + 1
    # after a clear the first code adds no table entry and each later one
    # adds one; stop one short of the entry that would widen the codes
    room = (1 << width) - (end + 1)
    codes = [clear]
    since = 0
    for v in indices:
        if since == room:
            codes.append(clear)
            since = 0
        codes.append(v)
        since += 1
    codes.append(end)
    out, acc, nbits = bytearray(), 0, 0
    for c in codes:
        acc |= c << nbits
        nbits += width
        while nbits >= 8:
            out.append(acc & 0xFF)
            acc >>= 8
            nbits -= 8
    if nbits:
        out.append(acc & 0xFF)
    blocks = bytearray()
    for i in range(0, len(out), 255):
        chunk = out[i:i + 255]
        blocks += bytes([len(chunk)]) + chunk
    return bytes([min_code_size]) + bytes(blocks) + b"\x00"


def _frame(x, y, w, h, pixels, *, delay, disposal, transparent=None,
           interlace=False):
    flags = (disposal << 2) | (1 if transparent is not None else 0)
    gce = b"\x21\xF9\x04" + struct.pack("<BHB", flags, delay, transparent or 0) + b"\x00"
    if interlace:
        rows = [pixels[r * w:(r + 1) * w] for r in range(h)]
        order = [r for start, step in ((0, 8), (4, 8), (2, 4), (1, 2))
                 for r in range(start, h, step)]
        pixels = [v for r in order for v in rows[r]]
    desc = b"\x2C" + struct.pack("<HHHHB", x, y, w, h, 0x40 if interlace else 0)
    return gce + desc + _lzw_uncompressed(pixels, 2)


def _gif(sw, sh, body, *, loop=True):
    # palette: 0 transparent, 1 sand, 2 navy, 3 rust
    pal = bytes([0, 0, 0, 240, 236, 228, 40, 60, 90, 200, 80, 30])
    head = b"GIF89a" + struct.pack("<HHBBB", sw, sh, 0x80 | 0x01, 0, 0) + pal
    ext = b"\x21\xFF\x0BNETSCAPE2.0\x03\x01" + struct.pack("<H", 0) + b"\x00"
    return head + (ext if loop else b"") + body + b"\x3B"


def offset_gif():
    """Screen 12x10, one global palette, no local tables. Frame 0 covers only
    the middle, so the rest of the screen must stay transparent. Frame 1 draws
    a patch with disposal 3, so it must be gone again in frame 2. Frame 2
    draws rust with disposal 2, so frame 3 shows a transparent hole there."""
    body = b""
    body += _frame(2, 2, 8, 6, [1] * 48, delay=10, disposal=1, transparent=0)
    body += _frame(3, 3, 4, 3, [2, 0, 2, 2] * 3, delay=10, disposal=3, transparent=0)
    body += _frame(6, 5, 3, 3, [3] * 9, delay=10, disposal=2, transparent=0)
    body += _frame(0, 0, 2, 2, [2] * 4, delay=10, disposal=1, transparent=0)
    return _gif(12, 10, body)


def interlaced_gif():
    """Two interlaced 16x16 frames. Every row differs from its neighbours, so
    a row put back in the wrong place changes the picture."""
    rows = [[1 + (r + c) % 3 for c in range(16)] for r in range(16)]
    flat = [v for row in rows for v in row]
    body = _frame(0, 0, 16, 16, flat, delay=10, disposal=1, interlace=True)
    shifted = [1 + (v % 3) for v in flat]
    body += _frame(0, 0, 16, 16, shifted, delay=10, disposal=1, interlace=True)
    return _gif(16, 16, body)


def main():
    save("delta.gif", frames(6), duration=60, loop=0)
    save("dispose2.gif", frames(5), duration=60, loop=0, disposal=2, transparency=0)
    save("dispose3.gif", frames(5), duration=60, loop=0, disposal=3)
    save("once.gif", frames(4), duration=60)
    save("fast.gif", frames(4), duration=10, loop=0)
    (HERE / "offset.gif").write_bytes(offset_gif())
    (HERE / "interlaced.gif").write_bytes(interlaced_gif())

    expected = {}
    for path in sorted(HERE.glob("*.gif")):
        im = Image.open(path)
        delays, hashes = [], []
        for i in range(im.n_frames):
            im.seek(i)
            delays.append(im.info.get("duration", 0))
            rgba = bytearray(im.convert("RGBA").tobytes())
            for p in range(0, len(rgba), 4):
                if rgba[p + 3] == 0:
                    rgba[p:p + 4] = b"\x00\x00\x00\x00"
            hashes.append(hashlib.sha256(rgba).hexdigest())
        expected[path.name] = {
            "width": im.width, "height": im.height,
            "loop": im.info.get("loop"), "delays": delays, "frames": hashes}
    (HERE / "expected.json").write_text(json.dumps(expected, indent=1) + "\n")


if __name__ == "__main__":
    main()
