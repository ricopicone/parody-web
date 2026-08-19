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


def export(html, values, table_id):
    """One table as a JSON-able dict: headers, cells, and what is still empty.

    Shaped for a spreadsheet or a plotting script — a list of rows, each cell
    carrying its column name — rather than mirroring the storage rows.
    """
    names = headers(html, table_id)
    cells = values.get(table_id, {})
    columns = sorted({int(c) for _, c in cells if str(c).isdigit()}
                     | {int(c) for c in names["columns"] if str(c).isdigit()})
    # The build reads the row names out of the first column, so that column is
    # the row label, not data: exporting it would put an empty "Task" beside
    # every row's own name.
    if names["rows"] and 1 in columns:
        columns.remove(1)
    rows = sorted({r for r, _ in cells}
                  | {int(r) for r in names["rows"] if str(r).isdigit()})
    return {
        "table_id": table_id,
        "columns": [{"index": c, "name": names["columns"].get(str(c), f"Column {c}")}
                    for c in columns],
        "rows": [
            {
                "index": r,
                "name": names["rows"].get(str(r), f"Row {r}"),
                "cells": {names["columns"].get(str(c), f"Column {c}"):
                          cells.get((r, str(c)), "") for c in columns},
            }
            for r in rows
        ],
    }


def materialise(html, *, request, book, section, values=None, export_url=None):
    """The frozen markup, resolved for this reader.

    ``export_url(table_id)`` returns the JSON-download URL for one table;
    ``values`` is :func:`stored_values` (fetched here when not supplied).
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
