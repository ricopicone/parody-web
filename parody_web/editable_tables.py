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

import re
from html import unescape

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

# The rendered table itself, which is what the export reads. The anchor div also
# carries data-column-headers / data-row-headers, and reading THOSE is how the
# export used to work — but the build writes header text into them verbatim, so
# a heading like \(R_i\) lands as an invalid JSON escape, json.loads throws, and
# every column and row name in the table quietly became "Column 3". Nearly every
# real lab table has maths in its headings. The markup below cannot lie about
# what the reader is looking at, and it also carries the cells the AUTHOR filled
# in (a nominal resistance, say), which the attributes never mentioned.
THEAD_RE = re.compile(r"<thead>(.*?)</thead>", re.DOTALL)
TBODY_RE = re.compile(r"<tbody>(.*?)</tbody>", re.DOTALL)
TH_RE = re.compile(r"<th[^>]*>(.*?)</th>", re.DOTALL)
TR_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL)
TD_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.DOTALL)
CELL_INPUT_RE = re.compile(r'name="cell-(?P<row>\d+)-(?P<col>\d+)"')
# \(x\) and $x$ delimit maths for MathJax; in a column heading they are noise.
MATH_DELIM_RE = re.compile(r"\\\((.*?)\\\)|\\\[(.*?)\\\]|\$([^$]*)\$", re.DOTALL)


def has_tables(html):
    """True when this section carries at least one data-entry table."""
    return "editable-table-anchor" in (html or "")


def table_ids(html):
    """Every data-entry table id in a section, in document order."""
    return [m.group("id") for m in ANCHOR_RE.finditer(html or "")]


def _text(fragment):
    """A cell's text: tags gone, entities decoded, maths unwrapped.

    A heading reads \\(R_i\\) in the markup because MathJax needs the
    delimiters. As a column name in a data file they are noise, so the maths
    comes out as the author wrote it — R_i — and stays their notation.
    """
    text = MATH_DELIM_RE.sub(
        lambda m: next(g for g in m.groups() if g is not None), fragment or "")
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(unescape(text).split())


def _table_markup(html, table_id):
    """The one table's rendered markup, anchor div to closing form."""
    for m in ANCHOR_RE.finditer(html or ""):
        if m.group("id") != table_id:
            continue
        rest = (html or "")[m.end():]
        end = rest.find("</form>")
        return rest if end < 0 else rest[:end]
    return ""


def parse_table(html, table_id):
    """The table as rendered: its column names, and its rows of cells.

    Each cell is either ``("text", "1.5")`` — fixed content, whether a row label
    or a value the author filled in — or ``("input", (row, col))``, a blank for
    the reader, carrying the very coordinates their saved values are keyed to.
    """
    markup = _table_markup(html, table_id)
    head = THEAD_RE.search(markup)
    columns = [_text(th) for th in TH_RE.findall(head.group(1))] if head else []
    body = TBODY_RE.search(markup)
    rows = []
    for tr in TR_RE.findall(body.group(1) if body else ""):
        cells = []
        for td in TD_RE.findall(tr):
            hit = CELL_INPUT_RE.search(td)
            cells.append(("input", (int(hit.group("row")), hit.group("col")))
                         if hit else ("text", _text(td)))
        rows.append(cells)
    return columns, rows


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


def _column_names(headings, width):
    """The name this export uses for each column, all distinct.

    Two columns headed "Notes" would collide as keys and the second would eat
    the first, so the later one becomes "Notes (2)". An unheaded column — lab
    tables often leave the label column's heading blank — gets "Column <n>"
    rather than "", which is unusable as a key.
    """
    out, seen = [], {}
    for i in range(width):
        base = (headings[i].strip() if i < len(headings) else "") or f"Column {i + 1}"
        seen[base] = seen.get(base, 0) + 1
        out.append(base if seen[base] == 1 else f"{base} ({seen[base]})")
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

    Read off the rendered table, so what comes out is what the reader saw: row
    labels, the author's own prefilled cells, and the reader's answers, each in
    its column.
    """
    headings, body = parse_table(html, table_id)
    cells = values.get(table_id, {})
    width = max([len(headings)] + [len(r) for r in body]) if (headings or body) else 0
    names = _column_names(headings, width)

    def record(row):
        out = {name: "" for name in names}
        for i, cell in enumerate(row):
            if i >= width:
                break
            kind, payload = cell
            out[names[i]] = (payload if kind == "text"
                             else cells.get(payload, ""))
        return out

    return {
        "table": {"id": table_id, "caption": caption(html, table_id)},
        "columns": names,
        "rows": [record(row) for row in body],
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
