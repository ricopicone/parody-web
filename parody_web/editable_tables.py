"""Data-entry tables: the reader fills the table in and it stays filled in.

A lab manual authors an observation table as ``::: {.editable-table}``, and
parody's filter turns it into a form whose empty cells are text inputs. That
markup is frozen (ricopic.one styles it and parody's golden artifacts pin it),
so it comes to us speaking the *homepage's* dialect: a bare
``<form method="POST">`` that posts to the page, ``{% csrf_token %}``, a
``{% get_cell %}`` tag in every input's value, and a ``{% url %}`` naming a
route that exists only in that project.

Rather than ask parody to emit a second dialect, this module materialises the
frozen markup at request time — when we know who is reading and what they saved
before. It runs *before* ``render_book``, so what reaches the template engine is
ordinary HTML.

Two things it must get right:

* ``{% get_cell … %}`` sits **inside an attribute value**. The library's stub
  tag returned a ``<span>``, which ends the ``value="`` attribute at its first
  quote and spills markup into the row — every cell of every table on the site
  rendered broken. A cell's value is text, and is escaped as text.
* The reader may be anonymous. Then the table still shows (and prints), but the
  inputs are disabled and the buttons become a sign-in line: a form that looks
  saveable and silently isn't is worse than one that says so.
"""

import json
import re

from django.utils.html import conditional_escape, escape

# <div id="…" class="editable-table-anchor …" data-column-headers='…' …>
ANCHOR_RE = re.compile(
    r'<div id="(?P<id>[^"]+)" class="editable-table-anchor[^"]*"'
    r"(?P<attrs>[^>]*)>")
GET_CELL_RE = re.compile(
    r"""\{%\s*get_cell\s+["'](?P<table>[^"']+)["']\s+"""
    r"""(?P<row>\d+)\s+(?P<col>\d+)\s*%\}""")
EXPORT_URL_RE = re.compile(
    r"""\{%\s*url\s+["']teaching:export_table_data["'][^%]*?"""
    r"""["'](?P<table>[^"']+)["']\s*%\}""")
CSRF_RE = re.compile(r"\{%\s*csrf_token\s*%\}")
FORM_OPEN_RE = re.compile(r'<form method="POST" class="editable-table-wrapper">')
CELL_NAME_RE = re.compile(r"^cell-(?P<row>\d+)-(?P<col>\d+)$")
DATA_ATTR_RE = re.compile(r"data-(?P<which>column|row)-headers='(?P<json>[^']*)'")


def has_tables(html):
    """True when this section carries at least one data-entry table."""
    return "editable-table-anchor" in (html or "")


def table_ids(html):
    """Every data-entry table id in a section, in document order."""
    return [m.group("id") for m in ANCHOR_RE.finditer(html or "")]


def headers(html, table_id):
    """The column/row header names the build recorded on the anchor div.

    They are the export's column names, and they are only on the anchor — the
    ``<th>`` cells carry the same text but the row names live in the body.
    """
    out = {"columns": {}, "rows": {}}
    for m in ANCHOR_RE.finditer(html or ""):
        if m.group("id") != table_id:
            continue
        for attr in DATA_ATTR_RE.finditer(m.group("attrs")):
            try:
                parsed = json.loads(attr.group("json").replace("&quot;", '"'))
            except ValueError:
                continue
            out["columns" if attr.group("which") == "column" else "rows"] = parsed
        break
    return out


def stored_values(user, book, section):
    """{table_id: {(row, column): value}} for one reader, one section."""
    from .models import TableEntry

    if user is None or not getattr(user, "is_authenticated", False):
        return {}
    rows = TableEntry.objects.filter(
        user=user, book_slug=book.slug, edition_id=book.edition_id or "",
        section_key=section.key)
    values = {}
    for entry in rows:
        values.setdefault(entry.table_id, {})[(entry.row, entry.column)] = entry.value
    return values


def save_post(post, *, user, book, section):
    """Persist one submitted table. Returns the table id, or None if the POST
    is not a table submission (or the reader may not save).

    Only cells belonging to the posted table are written, and only when that
    table really is in this section's html — a page posts one form, but the
    field names alone would let any id through.
    """
    from .models import TableEntry

    if user is None or not getattr(user, "is_authenticated", False):
        return None
    table_id = (post.get("table_id") or "").strip()
    if not table_id or table_id not in table_ids(section.html or ""):
        return None
    for name, value in post.items():
        m = CELL_NAME_RE.match(name)
        if not m:
            continue
        TableEntry.objects.update_or_create(
            user=user, book_slug=book.slug, edition_id=book.edition_id or "",
            section_key=section.key, table_id=table_id,
            row=int(m.group("row")), column=m.group("col"),
            defaults={"value": (value or "")[:255]},
        )
    return table_id


def caption(html, table_id):
    """The table's caption text, if the build gave it one."""
    for m in ANCHOR_RE.finditer(html or ""):
        if m.group("id") != table_id:
            continue
        after = html[m.end():m.end() + 2000]
        cap = re.search(r'<div class="table-caption">(.*?)</div>', after, re.DOTALL)
        return " ".join(re.sub(r"<[^>]+>", "", cap.group(1)).split()) if cap else ""
    return ""


def _column_names(names, columns):
    """Column index -> the name this export uses for it, all distinct.

    Two columns headed "Notes" would collide as keys and the second would eat
    the first, so the later one becomes "Notes (2)". An unheaded column gets
    "Column <n>" rather than "", which is unusable as a key.
    """
    out, seen = {}, {}
    for c in columns:
        base = str(names["columns"].get(str(c), "") or "").strip() or f"Column {c}"
        seen[base] = seen.get(base, 0) + 1
        out[c] = base if seen[base] == 1 else f"{base} ({seen[base]})"
    return out


def table_payload(html, values, table_id):
    """One table as the shape a reader can actually use.

    ``columns`` is the header row, and ``rows`` is one flat object per row
    keyed by those headers — so `pd.DataFrame(t["rows"], columns=t["columns"])`
    reproduces the table as it appears on the page, and a spreadsheet import
    finds the header row where it expects it.

    The row LABEL is a cell like any other, under its own column heading. It
    used to live beside the data as a separate `name`, which read fine but
    dropped out of every dataframe built from the cells — the labels are what
    say which trial a reading belongs to, so they have to be in the table.

    Rectangular on purpose: every row carries every column, empty ones as "",
    so a half-filled table still loads as a table.
    """
    names = headers(html, table_id)
    cells = values.get(table_id, {})
    columns = sorted({int(c) for _, c in cells if str(c).isdigit()}
                     | {int(c) for c in names["columns"] if str(c).isdigit()})
    labelled = bool(names["rows"])
    column_names = _column_names(names, columns)
    rows = sorted({r for r, _ in cells}
                  | {int(r) for r in names["rows"] if str(r).isdigit()})

    def record(r):
        out = {}
        for c in columns:
            # Column 1 holds the row labels when the table has them: the build
            # reads its own row headers out of that column, and no input is
            # rendered there.
            if labelled and c == 1:
                out[column_names[c]] = names["rows"].get(str(r), "")
            else:
                out[column_names[c]] = cells.get((r, str(c)), "")
        return out

    return {
        "table": {"id": table_id, "caption": caption(html, table_id)},
        "columns": [column_names[c] for c in columns],
        "rows": [record(r) for r in rows],
    }


def materialise(html, *, request, book, section, values=None, export_url=None,
                all_tables_url=None):
    """The frozen markup, resolved for this reader.

    ``export_url(table_id)`` returns the JSON-download URL for one table,
    ``all_tables_url`` the book-wide one; ``values`` is :func:`stored_values`
    (fetched here when not supplied).
    """
    if not has_tables(html):
        return html
    user = getattr(request, "user", None)
    signed_in = bool(user is not None and getattr(user, "is_authenticated", False))
    if values is None:
        values = stored_values(user, book, section) if signed_in else {}

    def cell(m):
        saved = values.get(m.group("table"), {})
        return escape(saved.get((int(m.group("row")), m.group("col")), ""))

    html = GET_CELL_RE.sub(cell, html)
    html = EXPORT_URL_RE.sub(
        lambda m: escape(export_url(m.group("table"))) if export_url else "#", html)

    if signed_in:
        from django.middleware.csrf import get_token

        token = get_token(request)
        html = CSRF_RE.sub(
            '<input type="hidden" name="csrfmiddlewaretoken" '
            f'value="{escape(token)}">', html)
        html = FORM_OPEN_RE.sub(
            '<form method="post" class="editable-table-wrapper">', html)
        if all_tables_url:
            # Beside this table's download, because that is where a reader who
            # wants their data is standing — and by the end of term the file
            # they actually want is all of it, not this one lab's.
            html = html.replace(
                "</a>\n  </div>",
                '</a>\n    <a class="all-tables" href="'
                f'{escape(all_tables_url)}">All my tables</a>\n  </div>')
        return html

    # Anonymous: keep the table readable, say plainly why it cannot be saved.
    html = CSRF_RE.sub("", html)
    html = FORM_OPEN_RE.sub(
        '<form class="editable-table-wrapper is-signed-out" '
        'onsubmit="return false">', html)
    html = html.replace('<input name="cell-', '<input disabled name="cell-')
    html = re.sub(
        r'<div class="flex gap-2 mt-2">.*?</div>',
        '<p class="editable-table-note">'
        f'{conditional_escape("Sign in to fill this table in and keep it.")}</p>',
        html, flags=re.DOTALL)
    return html
