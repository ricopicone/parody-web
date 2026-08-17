"""Composite a reader's ink into the PDF itself.

No new dependency. perfect-freehand already turned each stroke into a closed
outline, so a pen mark is a filled polygon and the exporter only has to speak
PDF's path operators. Highlighter translucency needs one ExtGState.

Coordinates arrive as the viewer stores them: PDF points, origin at the page's
top-left, y increasing downward. PDF's own space is y-up, so this module flips
— and it is the ONLY place that does, which is why the flip is a single
expression rather than a convention spread across the codebase.
"""

import re

# "M1 2 L3 4" / "M1,2Q3,4 5,6Z" — command letter followed by its numbers.
_TOKEN = re.compile(r"([MLQCZmlqcz])([^MLQCZmlqcz]*)")
_NUMBER = re.compile(r"-?\d*\.?\d+(?:[eE][-+]?\d+)?")


def _numbers(chunk):
    return [float(n) for n in _NUMBER.findall(chunk)]


def _fmt(value):
    """Trim float noise: PDF content streams get long fast."""
    return f"{value:.4f}".rstrip("0").rstrip(".") or "0"


def svg_path_to_pdf_ops(d, page_height):
    """Turn an SVG path into PDF path operators, flipping y once.

    Handles the subset perfect-freehand emits (M, L, Q, C, Z) in absolute
    form. PDF has no quadratic operator, so each Q is raised to an equivalent
    cubic — exactly, not approximately:

        C1 = P0 + 2/3 (Q - P0)     C2 = P1 + 2/3 (Q - P1)
    """
    def y(value):
        return page_height - value

    ops = []
    current = (0.0, 0.0)
    start = (0.0, 0.0)
    for command, chunk in _TOKEN.findall(d or ""):
        nums = _numbers(chunk)
        upper = command.upper()
        if upper == "M" and len(nums) >= 2:
            current = start = (nums[0], nums[1])
            ops.append(f"{_fmt(current[0])} {_fmt(y(current[1]))} m")
            # extra pairs after a moveto are implicit linetos
            for i in range(2, len(nums) - 1, 2):
                current = (nums[i], nums[i + 1])
                ops.append(f"{_fmt(current[0])} {_fmt(y(current[1]))} l")
        elif upper == "L":
            for i in range(0, len(nums) - 1, 2):
                current = (nums[i], nums[i + 1])
                ops.append(f"{_fmt(current[0])} {_fmt(y(current[1]))} l")
        elif upper == "Q":
            for i in range(0, len(nums) - 3, 4):
                qx, qy, px, py = nums[i:i + 4]
                c1 = (current[0] + 2 / 3 * (qx - current[0]),
                      current[1] + 2 / 3 * (qy - current[1]))
                c2 = (px + 2 / 3 * (qx - px), py + 2 / 3 * (qy - py))
                ops.append(f"{_fmt(c1[0])} {_fmt(y(c1[1]))} "
                           f"{_fmt(c2[0])} {_fmt(y(c2[1]))} "
                           f"{_fmt(px)} {_fmt(y(py))} c")
                current = (px, py)
        elif upper == "C":
            for i in range(0, len(nums) - 5, 6):
                x1, y1, x2, y2, px, py = nums[i:i + 6]
                ops.append(f"{_fmt(x1)} {_fmt(y(y1))} {_fmt(x2)} {_fmt(y(y2))} "
                           f"{_fmt(px)} {_fmt(y(py))} c")
                current = (px, py)
        elif upper == "Z":
            ops.append("h")
            current = start
    return " ".join(ops)


def _rgb(colour):
    """#rrggbb (or #rgb) to PDF's 0-1 triple. Unparseable colours draw black —
    a visible mark in the wrong colour beats a silently missing one."""
    value = (colour or "").lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    if len(value) != 6:
        return (0.0, 0.0, 0.0)
    try:
        r, g, b = (int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except ValueError:
        return (0.0, 0.0, 0.0)
    return (r, g, b)


def page_content(strokes, page_height):
    """The content stream drawing one page's strokes, or "" for none.

    Wrapped in q/Q so nothing it sets — colour, alpha, path state — can leak
    into the page it is drawn over.
    """
    if not strokes:
        return ""
    body = []
    for stroke in strokes:
        d = stroke.get("d")
        if not d:
            continue
        r, g, b = _rgb(stroke.get("color"))
        opacity = stroke.get("opacity", 1)
        # Pen and highlighter arrive as closed outlines from perfect-freehand
        # and are filled. Shape tools (line, rect, circle) are stroked paths
        # with a width. One code path either way: everything is a path.
        stroked = stroke.get("mode") == "stroke"
        body.append("q")
        if opacity is not None and opacity < 1:
            body.append(f"/PdA{int(round(opacity * 100))} gs")
        if stroked:
            body.append(f"{_fmt(r)} {_fmt(g)} {_fmt(b)} RG")
            body.append(f"{_fmt(stroke.get('width', 1) or 1)} w")
            body.append("1 J 1 j")          # round caps and joins, as on screen
        else:
            body.append(f"{_fmt(r)} {_fmt(g)} {_fmt(b)} rg")
        body.append(svg_path_to_pdf_ops(d, page_height))
        body.append("S" if stroked else "f")
        body.append("Q")
    return " ".join(p for p in body if p)


def _for_page(by_page, number):
    """Strokes for a 1-based page, whichever way the key was stored."""
    if not by_page:
        return []
    return by_page.get(str(number)) or by_page.get(number) or []


def _alpha_states(strokes_by_page):
    """Every distinct translucency the ink uses, as ExtGState entries."""
    alphas = set()
    for strokes in (strokes_by_page or {}).values():
        for stroke in strokes:
            opacity = stroke.get("opacity", 1)
            if opacity is not None and opacity < 1:
                alphas.add(int(round(opacity * 100)))
    return alphas


# How wide the scratch pad is, as a fraction of the page it hangs off.
PAD_RATIO = 0.5


def pad_width(page_width):
    return page_width * PAD_RATIO


def composite(src_path, strokes_by_page, dest_path, pads_by_page=None):
    """Write `src_path` with the ink drawn on top to `dest_path`.

    Page keys are 1-based and relative to the slice, matching how the viewer
    numbers the pages it showed.

    `pads_by_page` is the scratch pad beside each page. A page whose pad has
    anything on it is widened to make room and the notes are drawn in the new
    strip; a page with an empty pad is left exactly the size it was, so a book
    with three annotated margins does not become 118 wide pages.
    """
    from pypdf import PdfWriter
    from pypdf.generic import (ArrayObject, DecodedStreamObject, DictionaryObject,
                               FloatObject, NameObject)

    # Clone the document rather than copying its pages. add_page() carries the
    # page and nothing else, so the annotated book came out with all 118 pages
    # and none of its 55 bookmarks — the contents pane empty in every reader.
    # Cloning keeps the outline, the internal links and the metadata.
    writer = PdfWriter(clone_from=str(src_path))

    alphas = _alpha_states(strokes_by_page)

    alphas |= _alpha_states(pads_by_page)

    for index, page in enumerate(writer.pages):
        strokes = _for_page(strokes_by_page, index + 1)
        pad_strokes = _for_page(pads_by_page, index + 1)
        if not strokes and not pad_strokes:
            continue
        box = page.mediabox
        height = float(box.top) - float(box.bottom)
        content = page_content(strokes, height)

        if pad_strokes:
            # Widen the page rather than build a new one and merge: the
            # original content keeps its exact position, and the strip that
            # appears to the right of it is simply empty paper.
            right = float(box.right)
            extra = pad_width(right - float(box.left))
            page.mediabox.upper_right = (right + extra, float(box.top))
            crop = page.get("/CropBox")
            if crop is not None:
                page.cropbox.upper_right = (float(page.cropbox.right) + extra,
                                            float(page.cropbox.top))
            pad = page_content(pad_strokes, height)
            if pad:
                # Pad coordinates start at the pad's own left edge, so the
                # whole block is shifted across by the page width.
                content = f"{content} q 1 0 0 1 {_fmt(right)} 0 cm {pad} Q"
        if not content:
            continue

        resources = page.get("/Resources")
        if resources is None:
            resources = DictionaryObject()
            page[NameObject("/Resources")] = resources
        resources = resources.get_object()
        if alphas:
            gs = resources.get("/ExtGState")
            gs = gs.get_object() if gs is not None else DictionaryObject()
            for alpha in alphas:
                state = DictionaryObject()
                state[NameObject("/ca")] = FloatObject(alpha / 100)
                state[NameObject("/CA")] = FloatObject(alpha / 100)
                gs[NameObject(f"/PdA{alpha}")] = state
            resources[NameObject("/ExtGState")] = gs

        stream = DecodedStreamObject()
        stream.set_data(content.encode("latin-1", "replace"))
        existing = page.get("/Contents")
        contents = ArrayObject()
        if existing is not None:
            # Fence the page's own drawing inside q/Q. Appending to it meant
            # inheriting whatever graphics state it happened to leave behind —
            # a page that ends mid-transform silently moved and rescaled every
            # mark drawn on it. Found when a note in the margin landed 90pt
            # high and a third narrower than it was drawn.
            opening = DecodedStreamObject()
            opening.set_data(b"q\n")
            contents.append(writer._add_object(opening))
            if isinstance(existing.get_object(), ArrayObject):
                contents.extend(existing.get_object())
            else:
                contents.append(existing)
            closing = DecodedStreamObject()
            closing.set_data(b"\nQ\n")
            contents.append(writer._add_object(closing))
        contents.append(writer._add_object(stream))
        page[NameObject("/Contents")] = contents

    with open(dest_path, "wb") as handle:
        writer.write(handle)
