"""The answer key: a section with its fill-in-the-blanks filled, for staff.

A book with clozes ships two builds from one commit. `<slug>.json` is the
student build (`parody build --clozes blank`), whose answers were removed at
build time — an empty `.cloze-blank` span holds the place, so there is nothing
in a student's page to reveal. `<slug>-key.json` is the instructor build
(`--clozes key`): the same sections with every answer rendered in place.

An instructor teaching from the notes live wants the second on the site. It
cannot be the same page with the answers hidden by CSS, because then every
student has them in View Source. So the key's html is stored beside the
student html at import (`Section.key_html`) and the view serves it only to a
reader `can_view_staff_notes` admits, and only when that reader has asked for it.

The key is only useful if it is the key to *this* page. A key from another
release shows an instructor answers to blanks that have moved, in front of a
class. So the import checks that the two builds are the same text apart from
the blanks themselves — not that they have the same number of blanks, which a
book's own `\\underline{\\hspace{1em}}` placeholders in an equation defeat (the
system-dynamics Bode-plot section has ten, identical in both builds) — and
refuses a key that is not.
"""

import re

#: Placeholders the comparison reduces every blank and every answer to. Not
#: valid html or TeX on purpose: they exist only inside a comparison.
INLINE, BLOCK, MATH = "\x00cloze-inline\x00", "\x00cloze-block\x00", "\x00cloze-math\x00"

# --- the student build -------------------------------------------------------

_BLANK_SPAN = re.compile(r'<span class="cloze-blank"[^>]*></span>')
_BLANK_BOX = re.compile(r'<div class="cloze-lines cloze-box"[^>]*></div>')
#: A blank in maths, and also any rule an author typed by hand. Both builds
#: carry the hand-typed ones, so reducing them on both sides is what lets them
#: compare equal.
_MATH_RULE = re.compile(r"\\underline\{\\hspace\{[^{}]*\}\}")

# --- the key build -----------------------------------------------------------

_KEY_SPAN_OPEN = re.compile(r'<span class="cloze-key">')
_KEY_DIV_OPEN = re.compile(r'<div class="cloze-key-block">')
_KEY_MATH = "\\class{cloze-key}{"

#: Anything that marks an answer in a key build. A section with none has no
#: key worth storing: its key page would be its student page.
_HAS_ANSWER = re.compile(
    r'class="cloze-key(?:-block)?"|\\class\{cloze-key\}\{')


def has_answers(html):
    """Does this key-build html fill in any blank at all?"""
    return bool(html) and bool(_HAS_ANSWER.search(html))


def _replace_balanced_tags(html, opener, tag, token):
    """Replace each element `opener` starts, through its matching close tag.

    Nested elements of the same tag are balanced, so an answer holding inline
    maths (`<span class="cloze-key"><span class="math inline">…</span></span>`)
    is replaced whole. An element that never closes is left in place, which
    makes the comparison fail — the right outcome for markup that is broken.
    """
    any_tag = re.compile(rf"<{tag}\b[^>]*>|</{tag}\s*>", re.I)
    out, pos = [], 0
    while (m := opener.search(html, pos)) is not None:
        depth, cursor = 1, m.end()
        while depth and (t := any_tag.search(html, cursor)):
            depth += -1 if t.group(0).startswith("</") else 1
            cursor = t.end()
        if depth:
            break
        out += [html[pos:m.start()], token]
        pos = cursor
    out.append(html[pos:])
    return "".join(out)


def _replace_key_math(text):
    """Replace each `\\class{cloze-key}{…}` through its balanced closing brace."""
    out, pos = [], 0
    while (start := text.find(_KEY_MATH, pos)) != -1:
        depth, j = 1, start + len(_KEY_MATH)
        while j < len(text) and depth:
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
            j += 1
        if depth:
            break
        out += [text[pos:start], MATH]
        pos = j
    out.append(text[pos:])
    return "".join(out)


def reduce_student(html):
    """Student-build html with every blank reduced to its placeholder."""
    html = _BLANK_SPAN.sub(INLINE, html or "")
    html = _BLANK_BOX.sub(BLOCK, html)
    return _MATH_RULE.sub(MATH, html)


def reduce_key(html):
    """Key-build html with every answer reduced to its placeholder.

    A manual blank (`[]{.blank}`) has no answer, so the key build keeps its
    empty `.cloze-blank` span; reducing those too is what makes it match.
    """
    html = _replace_balanced_tags(html or "", _KEY_SPAN_OPEN, "span", INLINE)
    html = _replace_balanced_tags(html, _KEY_DIV_OPEN, "div", BLOCK)
    html = _replace_key_math(html)
    return reduce_student(html)


def _sections(data):
    return {(ch.get("slug"), sec.get("slug")): sec
            for ch in data.get("chapters", [])
            for sec in ch.get("sections", [])}


def mismatches(student, key):
    """Every reason `key` is not the answer key to `student`, as strings.

    Empty means they line up: same book, same commit, same edition, the same
    sections, and each section's text identical once blanks and answers are
    reduced to placeholders. Compared BEFORE numbering, which rewrites both.
    """
    problems = []
    for field in ("slug", "source_commit"):
        a, b = student.get(field), key.get(field)
        if a and b and a != b:
            problems.append(f"{field}: student build {a!r}, key build {b!r}")
    ed_a = str((student.get("edition") or {}).get("id", ""))
    ed_b = str((key.get("edition") or {}).get("id", ""))
    if ed_a != ed_b:
        problems.append(f"edition: student build {ed_a!r}, key build {ed_b!r}")

    ours, theirs = _sections(student), _sections(key)
    for k in sorted(set(ours) - set(theirs)):
        problems.append(f"{k[0]}/{k[1]}: missing from the key build")
    for k in sorted(set(theirs) - set(ours)):
        problems.append(f"{k[0]}/{k[1]}: in the key build only")
    for k in sorted(set(ours) & set(theirs)):
        a = reduce_student(ours[k].get("html", ""))
        b = reduce_key(theirs[k].get("html", ""))
        if a != b:
            at = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y),
                      min(len(a), len(b)))
            problems.append(
                f"{k[0]}/{k[1]}: text differs from the student build at "
                f"character {at}: {a[max(0, at - 40):at + 40]!r} vs "
                f"{b[max(0, at - 40):at + 40]!r}")
    return problems


# --- serving -----------------------------------------------------------------

#: The reader's choice, kept for the session rather than per page: teaching
#: live means walking a class through section after section, and a toggle that
#: reset on every "next" would be switched back on at the front of the room
#: every few minutes. The banner on each keyed page says it is on.
SESSION_KEY = "parody_web_show_answers"

#: ?answers=on / ?answers=off flips the session flag. Any other value is ignored.
QUERY = "answers"
_ON, _OFF = "on", "off"


def _is_staff(request):
    from parody_web.access import get_policy

    return bool(request is not None
                and get_policy().can_view_staff_notes(request))


def toggle(request):
    """Apply a ?answers=on|off request; return the url to redirect to, or None.

    Only a reader the policy admits as staff can set the flag. For anyone else
    the parameter does nothing at all — no redirect and no session write — so a
    student who adds it to a url gets exactly the page they would have had.
    The redirect drops the parameter and keeps the rest (?ed=…), so a reload
    or a shared link never re-toggles.
    """
    value = request.GET.get(QUERY)
    if value not in (_ON, _OFF) or not _is_staff(request):
        return None
    request.session[SESSION_KEY] = value == _ON
    rest = request.GET.copy()
    rest.pop(QUERY, None)
    query = rest.urlencode()
    return request.path + (f"?{query}" if query else "")


def for_reader(request, section):
    """(html, state) for `section` as this reader may see it.

    `state` is None when the reader cannot have the key — every student, and
    staff on a section with no blanks — so the page offers no toggle at all.
    Otherwise it is "shown" or "hidden". The html is the key's only when it is
    "shown"; staff-only blocks are still for the caller to strip, from either.
    """
    if not section.key_html or not _is_staff(request):
        return section.html, None
    if request.session.get(SESSION_KEY):
        return section.key_html, "shown"
    return section.html, "hidden"


def toggle_url(request, state):
    """The link that flips `state`, keeping the page's other parameters."""
    params = request.GET.copy()
    params[QUERY] = _OFF if state == "shown" else _ON
    return f"{request.path}?{params.urlencode()}"
