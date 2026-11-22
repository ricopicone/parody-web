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

`noise.gif` and `fulltable.gif` are where the codes DO grow: noise fills the
4096-entry table, so the codes reach 12 bits, and then what happens next is up
to the writer. Pillow clears and starts again (noise.gif). Other writers keep
going on the full table with no clear, every code 12 bits and no new entries;
`fulltable.gif` does that by hand in its first frame and clears in its second.
Every real book GIF is big enough to fill the table, and none of the small
fixtures above ever did.
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


def _lzw(indices, min_code_size, *, clear_when_full):
    """Real LZW, to the 4096-entry table and past it. A decoder adds an entry
    for every code but the first after a clear, one code behind the encoder,
    so the k-th code since a clear is as wide as `end + k` needs, capped at 12
    bits. With a full table, clear_when_full clears and starts again; without,
    the encoder carries on with the entries it has."""
    clear, end = 1 << min_code_size, (1 << min_code_size) + 1
    codes, filled = [], 0

    def emit(code, k):
        codes.append((code, min(12, (end + k).bit_length())))

    table, nxt, k = {(i,): i for i in range(clear)}, end + 1, 0
    codes.append((clear, min_code_size + 1))
    w = (indices[0],)
    for v in indices[1:]:
        wv = w + (v,)
        if wv in table:
            w = wv
            continue
        emit(table[w], k)
        k += 1
        if nxt < 4096:
            table[wv] = nxt
            nxt += 1
        else:
            filled += 1
            if clear_when_full:
                codes.append((clear, 12))
                table, nxt, k = {(i,): i for i in range(clear)}, end + 1, 0
        w = (v,)
    emit(table[w], k)
    emit(end, k + 1)
    # a fixture for the full table has to reach it, and go on past it
    assert filled > (0 if clear_when_full else 1000), f"full for {filled} codes"
    out, acc, nbits = bytearray(), 0, 0
    for c, width in codes:
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


def _noise(n, seed):
    """n palette indices in 0..15, the same on every run."""
    x, out = seed, []
    for _ in range(n):
        x = (x * 1103515245 + 12345) & 0x7FFFFFFF
        out.append((x >> 16) & 15)
    return out


SIDE = 128
PAL16 = bytes(v for i in range(16) for v in (i * 16, 255 - i * 13, (i * 37) % 256))


def fulltable_gif():
    """Two 128x128 frames of 16-colour noise (96x96 never fills the table).
    The first keeps going on a full table with no clear code; the second
    clears when the table fills."""
    w = h = SIDE
    body = b""
    for seed, clear_when_full in ((7, False), (11, True)):
        gce = b"\x21\xF9\x04" + struct.pack("<BHB", 1 << 2, 10, 0) + b"\x00"
        desc = b"\x2C" + struct.pack("<HHHHB", 0, 0, w, h, 0)
        body += gce + desc + _lzw(_noise(w * h, seed), 4,
                                  clear_when_full=clear_when_full)
    head = b"GIF89a" + struct.pack("<HHBBB", w, h, 0x80 | 0x03, 0, 0) + PAL16
    ext = b"\x21\xFF\x0BNETSCAPE2.0\x03\x01" + struct.pack("<H", 0) + b"\x00"
    return head + ext + body + b"\x3B"


def noise_gif_frames():
    ims = []
    for seed in (3, 5):
        im = Image.new("P", (SIDE, SIDE))
        im.putpalette(PAL16)
        im.putdata(_noise(SIDE * SIDE, seed))
        ims.append(im)
    return ims


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
    # the first frame keeps (1): Pillow and browsers disagree about a first
    # frame with disposal 3 (decode.test.js pins the browsers' reading)
    save("dispose3.gif", frames(5), duration=60, loop=0, disposal=[1, 3, 3, 3, 3])
    save("once.gif", frames(4), duration=60)
    save("fast.gif", frames(4), duration=10, loop=0)
    (HERE / "offset.gif").write_bytes(offset_gif())
    (HERE / "interlaced.gif").write_bytes(interlaced_gif())
    save("noise.gif", noise_gif_frames(), duration=100, loop=0)
    (HERE / "fulltable.gif").write_bytes(fulltable_gif())
    # the hand-written LZW is only a fixture if it says what it means to:
    # Pillow must read back exactly the noise that went in
    ft = Image.open(HERE / "fulltable.gif")
    for i, seed in enumerate((7, 11)):
        ft.seek(i)
        got = ft.convert("RGB").tobytes()
        want = b"".join(PAL16[3 * v:3 * v + 3] for v in _noise(SIDE * SIDE, seed))
        assert got == want, f"fulltable.gif frame {i} does not decode to its source"

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
