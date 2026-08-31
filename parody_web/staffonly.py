"""`.staff-only` blocks: content that ships in the artifact, gated per reader.

A book may carry material written for whoever is *teaching* from it rather than
reading it — marking guidance at the end of a worked solution, what to insist
on, which slip to watch for, what partial credit is worth. It belongs next to
the answer it is about, in the same source, and it must not reach the reader
the answer is for.

Two existing mechanisms nearly fit and both are wrong for this:

* `.solutions-only` is a **build-time** gate. parody deletes the div unless the
  run is producing the solutions manual, so the content never enters the
  artifact at all. That cannot work here: one artifact serves students and
  staff, and rebuilding per audience is exactly what a single artifact exists
  to avoid.
* `can_view_solution` is an all-or-nothing gate on a whole page. A solution
  opens to a student when the assignment falls due — which is the point of
  posting it — and the marking guidance must not open with it.

So the mark survives the build with its class intact, and the decision moves
here, to serve time, where `can_view_staff_notes` can be asked about a
particular reader.

The stripper is deliberately a scanner rather than a parser. It runs on every
section render, it must never mangle the surrounding html, and it must fail
*closed*: content it cannot make sense of is dropped, not served.
"""

import re

#: Opens a staff-only block. Matched loosely on the class attribute so a div
#: carrying other classes (`.staff-only .grading-notes` is the shape books
#: actually write), an id, or data attributes is still recognised.
#:
#: The class boundary is `(?<![-\w]) … (?![-\w])`, not `\b`: a word boundary
#: matches at a HYPHEN, so `\bstaff-only\b` also matched `staff-only-preview`
#: and stripped a div that was never marked. Same rule as parody's
#: `_fence_has_class`, and for the same reason.
_OPEN = re.compile(
    r'<div\b[^>]*\bclass="[^"]*(?<![-\w])staff-only(?![-\w])[^"]*"[^>]*>',
    re.I)

#: Any div tag at all, for balancing the scan.
_ANY_DIV = re.compile(r"<div\b[^>]*>|</div\s*>", re.I)


def strip_staff_only(html):
    """Return `html` with every `.staff-only` div, and its contents, removed.

    Scans forward from each opening tag balancing nested `<div>`s, so a block
    that grows a nested div later is removed whole rather than leaving its tail
    behind as visible markup.

    An unbalanced block — one that never closes — drops the remainder of the
    document rather than shipping half of it. That is the safe direction: a
    reader seeing a truncated page is a bug report, a reader seeing the answer
    key is not recoverable.

    Content with no such div is returned untouched and unparsed, which is what
    makes this cheap enough to run on every render and safe to run over books
    authored before the convention existed.
    """
    if not html or "staff-only" not in html:
        return html

    out = []
    pos = 0
    while True:
        opening = _OPEN.search(html, pos)
        if opening is None:
            out.append(html[pos:])
            break
        out.append(html[pos:opening.start()])

        depth = 1
        cursor = opening.end()
        while depth and (tag := _ANY_DIV.search(html, cursor)):
            depth += -1 if tag.group(0).startswith("</") else 1
            cursor = tag.end()
        if depth:
            break  # never closes: drop the remainder rather than serve half
        pos = cursor

    return "".join(out)


def for_reader(request, html):
    """`html` as this reader may see it — whole for staff, stripped otherwise.

    The policy is asked once per call. `request` may be None on helper paths
    that have none, and a policy that cannot identify a reader answers no, so
    the None case strips.
    """
    from parody_web.access import get_policy

    if get_policy().can_view_staff_notes(request):
        return html
    return strip_staff_only(html)
