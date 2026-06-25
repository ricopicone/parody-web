"""Number a parody artifact (chapters, sections, subsections, figures) and
resolve its cross-references, at import time.

The artifact ships unnumbered: headings carry stable short hashes (``data-h`` /
``anchors``) and cross-references are ``<span class="hashref">TARGET</span>``
where TARGET is a heading hash (2 chars), a chapter hash, or a ``fig:``/``tbl:``
… id. Print gets numbering from LaTeX; the web build does not, so we compute it
here and rewrite the stored html:

* chapters → ``1, 2, …`` (arabic) or ``A, B, …`` (appendix)
* sections → ``C.m`` — except "Problems" (unnumbered) and labs ("Lab Exercise N:")
* subsections → ``C.m.k[.j]`` within numbered sections
* figures → ``Figure C.k`` (per chapter), captions prefixed
* ``hashref`` spans → links showing the target's label ("Section 3.2", "Figure 3.1", …)

Conventions (Problems unnumbered, labs get an exercise prefix) match the book's
print layout. Targets it can't resolve (tbl:/eq:/… for now) are left as-is.
"""
import re
from html import escape as _esc

_HEADING_RE = re.compile(r'(<(h[1-6])\b[^>]*\bdata-h="(?P<hash>[^"]+)"[^>]*>)')
_FIG_RE = re.compile(r'<figure\b[^>]*\bid="(?P<id>[^"]+)"[^>]*>(?P<rest>.*?)</figure>',
                     re.S)
_FIGCAP_RE = re.compile(r'(<figcaption[^>]*>)', re.S)
# .hashref keeps the reference lower-case ("section 3.2"); .Hashref capitalizes
# it ("Section 3.2") for sentence starts — mirrors print.lua's hashrefer.
_HASHREF_RE = re.compile(r'<span class="([Hh]ashref)">([^<]*)</span>')
# pandoc rendered some cross-refs (written [@fig:x]) as citations because
# pandoc-crossref didn't run; resolve those against the same target map.
_CITE_RE = re.compile(
    r'<span class="citation" data-cites="([^"]+)">\[@([^\]]*)\]</span>')

# raw LaTeX that leaked into table cells etc. as `\cmd`{=latex}. (Math is in
# <span class="math">…</span>, never backtick-{=latex}, so it's untouched.)
_RAWTEX_RE = re.compile(r'`([^`]*)`\{=latex\}')
_RAWTEX_ICONS = {"faTree": "\U0001F332", "textbullet": "•",
                 "faTimes": "✕", "faCheck": "✓", "faWindows": "⊞"}
_RAWTEX_DROP = {"raggedleft", "arraybackslash", "cmidrule", "newpage",
                "clearpage", "ifdefined", "centering", "hline", "toprule",
                "midrule", "bottomrule", "fi", "vspace", "hspace"}


# Some math leaked as single-dollar $…$ (MathJax 3 only processes \(…\)). Convert
# $…$ runs that contain a TeX math indicator (\ _ ^ {) to \(…\); prose dollar
# amounts ($5) have none of those and are left alone.
_DOLLAR_MATH_RE = re.compile(r'(?<!\$)\$(?!\$)([^$<\n]{1,60}?)\$(?!\$)')


def _fix_dollar_math(html):
    def conv(mo):
        c = mo.group(1)
        # math if it has a TeX indicator, or is a short space-free token ($10/$b);
        # "$10 to $20" (spaces, no indicator) is left as prose.
        if re.search(r"[\\_^{]", c) or (" " not in c and len(c) <= 30):
            return f'<span class="math inline">\\({c}\\)</span>'
        return mo.group(0)
    return _DOLLAR_MATH_RE.sub(conv, html)


def _target_url(t):
    """The href for a resolved target; chapter refs point at their first section."""
    url = t.get("url")
    if url is None and t.get("chapter"):
        secs = t["chapter"].get("sections", [])
        url = f"/{t['chapter']['slug']}/{secs[0]['slug']}/" if secs else "#"
    return url or "#"


def _lookup_target(tgt, targets):
    """Resolve one cross-ref key to its target entry, with the sentence-start
    'Fig:'/'Tbl:' capitalization fallback. Returns None if absent."""
    t = targets.get(tgt)
    if not t and tgt[:1].isupper():
        t = targets.get(tgt[:1].lower() + tgt[1:])
    return t


def _recase_label(label, cap):
    """Set a cross-ref label's leading-letter case (task #296). Every reference
    kind follows the case requested at the *reference site* — figures, tables,
    equations, sections, chapters, examples, theorems alike. cap=True ->
    "Figure 1.2", cap=False -> "figure 1.2". Lookup stays case-insensitive (see
    _lookup_target); only the displayed first letter changes."""
    if not label:
        return label
    return (label[:1].upper() if cap else label[:1].lower()) + label[1:]


def _link(label, url):
    return f'<a class="xref" href="{url}">{label}</a>'


def _join_oxford(parts):
    if len(parts) <= 1:
        return parts[0] if parts else ""
    if len(parts) == 2:
        return f"{parts[0]} and {parts[1]}"
    return ", ".join(parts[:-1]) + ", and " + parts[-1]


def _render_refs(tgt, targets, cap_class=False):
    """Resolve a cross-ref target, which may be a comma-separated list of keys
    ([4n,us,rq]{.hashref} → "chapters 2, 3, and 4", each number linked). When the
    targets share a label word the word is factored out and pluralized; otherwise
    the full labels are listed. Returns None if any key is unresolved (the caller
    then leaves the span as-is rather than rendering a half-broken ref).

    Case follows the reference site (task #296): cap_class is set when the span
    asked to capitalize (a .Hashref / \\Cref), and an upper-case key letter
    (Fig:, S4) also capitalizes — otherwise the label is lower-cased."""
    resolved = []
    for k in (k.strip() for k in tgt.split(",")):
        if not k:
            continue
        t = _lookup_target(k, targets)
        if not t:
            return None
        cap = cap_class or k[:1].isupper()
        resolved.append((_recase_label(t["label"], cap), _target_url(t)))
    if not resolved:
        return None
    if len(resolved) == 1:
        return _link(*resolved[0])
    words = {lbl.rsplit(" ", 1)[0] for lbl, _ in resolved if " " in lbl}
    if len(words) == 1 and all(" " in lbl for lbl, _ in resolved):
        word = next(iter(words))
        nums = [_link(lbl.rsplit(" ", 1)[1], url) for lbl, url in resolved]
        return f"{word}s {_join_oxford(nums)}"
    return _join_oxford([_link(lbl, url) for lbl, url in resolved])


def _cref_link(key, targets, cap=False):
    out = _render_refs(key, targets, cap_class=cap)
    return out if out is not None else ""


# formatting-only LaTeX commands (with an optional {arg}/star) — strip, keep text
_FMT_CMD_RE = re.compile(
    r"\\(?:raggedleft|arraybackslash|centering|cmidrule|hline|toprule|midrule|"
    r"bottomrule|newpage|clearpage|ifdefined|fi|small|footnotesize|normalsize|"
    r"vspace\*?|hspace\*?)\b(?:\{[^}]*\})?")


def _clean_rawtex(html, targets):
    """Clean `\\cmd…`{=latex} spans: map icons, keep content of wrappers, resolve
    leaked \\cref, strip formatting-only commands — but KEEP any real cell text
    (e.g. `\\arraybackslash 0`{=latex} → "0", not "")."""
    def sub(mo):
        c = mo.group(1)
        for cmd, g in _RAWTEX_ICONS.items():
            c = c.replace("\\" + cmd, g)
        c = re.sub(r"\\fbox\{(.*?)\}", r"\1", c)
        c = re.sub(r"\\mc\{[^}]*\}\{[^}]*\}\{(.*?)\}", r"\1", c)  # multicolumn
        c = re.sub(r"\\(?:textbf|textit|texttt|emph|textsf)\{(.*?)\}", r"\1", c)
        c = re.sub(r"\\([cC])ref\{([^}]*)\}",
                   lambda m: _cref_link(m.group(2), targets, cap=m.group(1) == "C"), c)
        c = _FMT_CMD_RE.sub("", c)
        return c.strip()
    return _RAWTEX_RE.sub(sub, html)


_MENU_RE = re.compile(r'<span class="menu">([^<]*)</span>')
# Eclipse debugger toolbar buttons referenced by token → icon (staged in media)
_ECLIPSE_ICONS = {
    "estepover": ("stepover", "Step Over"), "estepinto": ("stepinto", "Step Into"),
    "estepreturn": ("stepreturn", "Step Return"), "eresume": ("resume", "Resume"),
    "eterminate": ("terminate", "Terminate"),
    "enrc": ("new_con", "New Run Configuration"),
}


def _style_menus(html):
    """A .menu span like "Run, Debug Configurations" is a menu path; the commas
    are submenu delimiters → boxed segments separated by › arrows. A few tokens
    name Eclipse debugger buttons → render the toolbar icon instead."""
    def sub(mo):
        val = mo.group(1).strip()
        if val in _ECLIPSE_ICONS:
            icon, label = _ECLIPSE_ICONS[val]
            return (f'<img class="ebtn" src="{{% static \'parody_web/eclipse/'
                    f'{icon}.svg\' %}}" alt="{label}" title="{label}">')
        parts = [p.strip() for p in mo.group(1).split(",") if p.strip()]
        inner = '<span class="m-arrow">›</span>'.join(
            f'<span class="m-item">{p}</span>' for p in (parts or [mo.group(1)]))
        return f'<span class="menu">{inner}</span>'
    return _MENU_RE.sub(sub, html)


_INDEX_OPEN_RE = re.compile(r'<span ([^>]*\bclass="[^"]*\bindex\b[^"]*"[^>]*)>')


def _anchor_index_spans(html, prefix):
    """Give every .index span a stable id (+ aria-hidden, since the clipped term
    text is now in flow as a scroll target) so the subject index can deep-link to
    where each term actually appears, not just to the section. Idempotent."""
    n = [0]

    def sub(m):
        attrs = m.group(1)
        if "id=" in attrs:
            return m.group(0)
        n[0] += 1
        return f'<span id="{prefix}-{n[0]}" aria-hidden="true" {attrs}>'

    return _INDEX_OPEN_RE.sub(sub, html)


_TABLE_RE = re.compile(r"<table\b.*?</table>", re.S)


def _clean_tables(html):
    """Table cells often came from raw LaTeX un-processed: bare column-format
    commands, literal `code` backticks, and single-$ math. Clean within tables
    only (prose is untouched)."""
    def fix(mo):
        t = _FMT_CMD_RE.sub("", mo.group(0))
        t = re.sub(r"`([^`\n]+)`",
                   lambda m: "<code>" + m.group(1) + "</code>", t)
        t = re.sub(r"(?<!\$)\$(?!\$)([^$<\n]+?)\$(?!\$)",
                   lambda m: '<span class="math inline">\\(' + m.group(1)
                   + '\\)</span>', t)
        return t
    return _TABLE_RE.sub(fix, html)


# anchor type -> cross-reference label word (per-chapter numbered: "Table 3.1")
_TYPE_LABELS = {
    "figure": "Figure", "table": "Table", "equation": "Equation",
    "exercise": "Exercise", "example": "Example", "theorem": "Theorem",
    "definition": "Definition", "listing": "Listing", "algorithm": "Algorithm",
}


def _chapter_label(ch, idx_state):
    if ch.get("appendix"):
        idx_state["appendix"] += 1
        # A, B, … Z, AA, … (simple base-26)
        n = idx_state["appendix"]
        s = ""
        while n:
            n, r = divmod(n - 1, 26)
            s = chr(65 + r) + s
        return s
    idx_state["arabic"] += 1
    return str(idx_state["arabic"])


_FIGURE_TAG_RE = re.compile(r'<figure\b[^>]*\bid="([^"]+)"[^>]*\bclass="([^"]*)"')


def _subfig_structure(html):
    """Map each subfigure-float main id -> its ordered panel ids, by scanning the
    rendered html (<figure class="figure subfigures" id=main> wrapping
    <figure class="subfigure" id=panel>s). "subfigures" is matched before the
    "subfigure" substring."""
    children, cur = {}, None
    for m in _FIGURE_TAG_RE.finditer(html):
        fid, cls = m.group(1), m.group(2)
        classes = cls.split()
        if "subfigures" in classes:
            cur = fid
            children[fid] = []
        elif "subfigure" in classes and cur is not None:
            children[cur].append(fid)
    return children


_SUBTABLES_RE = re.compile(
    r'<figure\b[^>]*\bid="([^"]+)"[^>]*\bclass="subtables"[^>]*>(.*?)</figure>', re.S)
_TABLE_ID_RE = re.compile(r'<table\b[^>]*\bid="([^"]+)"')


def _subtable_structure(html):
    """Map each subtables-float main id -> its ordered panel <table> ids, by
    scanning the rendered html (<figure class="subtables" id=main> wrapping
    <div class="subtable"><table id=panel>…). The float holds no nested <figure>,
    so a non-greedy match to the next </figure> is safe."""
    return {m.group(1): _TABLE_ID_RE.findall(m.group(2))
            for m in _SUBTABLES_RE.finditer(html)}


_RIGHTS_FIG_RE = re.compile(r'<figure\b[^>]*\bdata-permission="permission"')
_RIGHTS_IMG_RE = re.compile(r'<img\b[^>]*\bdata-permission="permission"[^>]*>')
_FIG_DELIM_RE = re.compile(r'<figure\b|</figure>')
_IMG_RE = re.compile(r'<img\b[^>]*>')
_RIGHTS_PLACEHOLDER = ('<div class="rights-placeholder">Figure available in the '
                       'print and ebook editions.</div>')


def _gate_rights_figures(html):
    """Replace the image(s) of permission=permission figures with a print-only
    placeholder (keeping caption + number). Two carriers: subfigure floats tag the
    outer <figure data-permission> (replace every panel img, via a balanced scan);
    single figures tag the <img data-permission> itself."""
    out, pos = [], 0
    for m in _RIGHTS_FIG_RE.finditer(html):
        if m.start() < pos:
            continue  # already handled (nested inside a prior rights figure)
        depth, end = 0, len(html)
        for d in _FIG_DELIM_RE.finditer(html, m.start()):
            depth += 1 if d.group(0) == "<figure" else -1
            if depth == 0:
                end = d.end()
                break
        out.append(html[pos:m.start()])
        out.append(_IMG_RE.sub(_RIGHTS_PLACEHOLDER, html[m.start():end]))
        pos = end
    html = "".join(out) + html[pos:]
    # single figures: the <img> itself carries the flag
    return _RIGHTS_IMG_RE.sub(_RIGHTS_PLACEHOLDER, html)


def _section_kind(sec):
    html = sec.get("html") or ""
    if (sec.get("title") or "").strip().lower() == "problems":
        return "problems"
    if re.search(r'<h1\b[^>]*class="[^"]*\blab\b', html):
        return "lab"
    if sec.get("slug") == "lead-in" or not sec.get("anchors"):
        return "leadin"
    return "normal"


def number_artifact(data, references=None, edition_query=""):
    """Mutate `data` in place: set chapter['number'] / section['number'] and
    rewrite section['html'] with numbered headings/figures and resolved refs.
    `references` maps a bib key -> {"label","full"}; bibliography citations are
    linked and a per-section References list is appended. Returns the target map.

    `edition_query` (e.g. "?ed=ed1") is appended to every in-site cross-ref URL
    so links inside a non-default edition stay on that edition; it is "" for the
    default (and single-edition) artifact, which lives at the bare URLs."""
    references = references or {}
    targets = {}          # hash/id -> {"label":..., "url":...}
    heading_numbers = {}  # per-section: hash -> number string (for html rewrite)
    float_caps = {}       # per-section: float-id -> (label_word, number)
    table_caps = {}       # per-section: tbl-id -> number (caption prefix)
    subfig_caps = {}      # per-section: main-id -> (number, [(sub-id, letter), …])
    subtable_caps = {}    # per-section: main-tbl-id -> (number, [(sub-id, letter), …])
    listing_caps = {}     # per-section: lst-id -> (number, caption)
    idx_state = {"arabic": 0, "appendix": 0}
    lab_n = 0

    # ---- pass 1: assign numbers, build the target map ----
    for ch in data.get("chapters", []):
        cnum = _chapter_label(ch, idx_state)
        ch["number"] = cnum
        if ch.get("hash"):
            secs = ch.get("sections", [])
            ch_url = (f"/{ch['slug']}/{secs[0]['slug']}/{edition_query}"
                      if secs else None)
            targets[ch["hash"]] = {"label": f"Chapter {cnum}", "url": ch_url,
                                   "chapter": ch}
        sec_m = 0
        type_counters = {}  # per-chapter counters for figure/table/equation/…
        for sec in ch.get("sections", []):
            kind = _section_kind(sec)
            url = f"/{ch['slug']}/{sec['slug']}/{edition_query}"
            if kind == "normal":
                sec_m += 1
                secnum = f"{cnum}.{sec_m}"
                sec["number"] = secnum
            elif kind == "lab":
                lab_n += 1
                secnum = None
                # sentence case ("Lab exercise N") so a cross-ref recases only the
                # first letter — "Lab exercise 6" / "lab exercise 6", never the
                # mid-phrase "lab Exercise 6". (_recase_label toggles label[:1].)
                sec["number"] = f"Lab exercise {lab_n}"
            elif kind == "problems":
                secnum = None
                sec["number"] = ""
            else:  # leadin
                secnum = None
                sec["number"] = ""

            # headings (anchors are in document order): h1 = the section itself
            counters = {}
            for a in sec.get("anchors", []):
                if a.get("type") != "heading":
                    continue
                lvl = a.get("level", 1)
                h = a.get("hash")
                anchor_id = a.get("id", "")
                if lvl == 1:
                    label_num = secnum  # may be None (lab/problems/leadin)
                    if h:
                        if secnum:
                            targets[h] = {"label": f"Section {secnum}", "url": url}
                        elif sec["number"]:  # lab
                            targets[h] = {"label": sec["number"], "url": url}
                        else:
                            targets[h] = {"label": sec.get("title", ""), "url": url}
                    if label_num:
                        heading_numbers.setdefault(sec["slug"], {})[h] = label_num
                elif secnum:  # number subsections only inside numbered sections
                    counters[lvl] = counters.get(lvl, 0) + 1
                    for deeper in [x for x in counters if x > lvl]:
                        counters[deeper] = 0
                    parts = [secnum] + [str(counters[x]) for x in
                                        sorted(k for k in counters if k >= 2 and k <= lvl)]
                    sub = ".".join(parts)
                    if h:
                        targets[h] = {"label": f"Section {sub}",
                                      "url": f"{url}#{anchor_id}"}
                        heading_numbers.setdefault(sec["slug"], {})[h] = sub
                elif h:
                    # subsection inside an unnumbered section (a lab/problems
                    # section has no C.m number, so its subsections get none
                    # either). Still register the heading so refs to it land —
                    # labelled by its title (backticks are markdown, drop them).
                    title = (a.get("title") or "").replace("`", "")
                    targets[h] = {"label": title,
                                  "url": f"{url}#{anchor_id}"}

            # subfigure floats: ::: {.subfigures #fig:main} renders one outer
            # <figure class="figure subfigures"> wrapping <figure class="subfigure">
            # panels. The panels carry fig: ids/anchors too; they share the main's
            # number with a letter — (a), (b), … — so don't count them as figures.
            sf_children = _subfig_structure(sec.get("html") or "")
            sf_subids = {sid for kids in sf_children.values() for sid in kids}
            st_children = _subtable_structure(sec.get("html") or "")
            st_subids = {sid for kids in st_children.values() for sid in kids}

            # non-heading targets (figures, tables, equations, exercises, …),
            # numbered per chapter per type in anchor (document) order. The
            # registry keys on both id (fig:…/tbl:…) and 2-char hash (exercises).
            for a in sec.get("anchors", []):
                t = a.get("type")
                if t == "heading" or t not in _TYPE_LABELS:
                    continue
                if a.get("id") in sf_subids or a.get("id") in st_subids:
                    continue  # a sub-panel; numbered with its parent below
                type_counters[t] = type_counters.get(t, 0) + 1
                num = f"{cnum}.{type_counters[t]}"
                # equations are referenced with the number in parentheses,
                # matching cleveref's print convention: "equation (3.2)".
                num_disp = f"({num})" if t == "equation" else num
                entry = {"label": f"{_TYPE_LABELS[t]} {num_disp}",
                         "url": f"{url}#{a.get('id', '')}"}
                if a.get("id"):
                    targets[a["id"]] = entry
                if a.get("hash"):
                    targets[a["hash"]] = entry
                if t == "figure" and a.get("id") in sf_children:
                    # main of a subfigure float: letter its panels and record the
                    # caption injections for pass 2 (nested <figure>s break _FIG_RE)
                    lettered = []
                    for i, sid in enumerate(sf_children[a["id"]]):
                        letter = chr(97 + i)
                        # cross-refs read "Figure 3.1b" (letter appended); the
                        # panel's own sub-caption leads with "(b)" (see pass 2).
                        targets[sid] = {"label": f"Figure {num}{letter}",
                                        "url": f"{url}#{sid}"}
                        lettered.append((sid, letter))
                    subfig_caps.setdefault(sec["slug"], {})[a["id"]] = (num, lettered)
                elif t == "figure" and a.get("id"):
                    float_caps.setdefault(sec["slug"], {})[a["id"]] = ("Figure", num)
                elif t == "table" and a.get("id") in st_children:
                    # main of a sub-table float: letter its panels (Table C.n(a))
                    lettered = []
                    for i, sid in enumerate(st_children[a["id"]]):
                        letter = chr(97 + i)
                        targets[sid] = {"label": f"Table {num}{letter}",
                                        "url": f"{url}#{sid}"}
                        lettered.append((sid, letter))
                    subtable_caps.setdefault(sec["slug"], {})[a["id"]] = (num, lettered)
                elif t == "table" and a.get("id"):
                    table_caps.setdefault(sec["slug"], {})[a["id"]] = num

            # algorithms render as <figure id="al:.."|"alg:.."> (pseudocode SVGs)
            # and listings as <div id="lst:.." class="listing" data-caption="..">;
            # neither is in `anchors`, so scan the html in document order.
            sh = sec.get("html") or ""
            for fm in re.finditer(r'<figure\b[^>]*\bid="((?:al|alg):[^"]+)"', sh):
                type_counters["algorithm"] = type_counters.get("algorithm", 0) + 1
                num = f"{cnum}.{type_counters['algorithm']}"
                targets[fm.group(1)] = {"label": f"Algorithm {num}",
                                        "url": f"{url}#{fm.group(1)}"}
                float_caps.setdefault(sec["slug"], {})[fm.group(1)] = ("Algorithm", num)
            for lm in re.finditer(
                    r'<div\b[^>]*\bid="(lst:[^"]+)"[^>]*\bdata-caption="([^"]*)"', sh):
                type_counters["listing"] = type_counters.get("listing", 0) + 1
                num = f"{cnum}.{type_counters['listing']}"
                targets[lm.group(1)] = {"label": f"Listing {num}",
                                        "url": f"{url}#{lm.group(1)}"}
                listing_caps.setdefault(sec["slug"], {})[lm.group(1)] = (num, lm.group(2))

    # ---- pass 2: rewrite html (numbers in headings/figs, resolve hashrefs) ----
    for ch in data.get("chapters", []):
        for sec in ch.get("sections", []):
            html = sec.get("html") or ""
            if not html:
                continue
            html = _clean_rawtex(html, targets)
            html = _clean_tables(html)
            html = _fix_dollar_math(html)
            html = _style_menus(html)
            hn = heading_numbers.get(sec["slug"], {})
            labels = {"lab": sec["number"] if _section_kind(sec) == "lab" else None}

            def num_heading(mo):
                full, tag, h = mo.group(1), mo.group(2), mo.group("hash")
                if tag == "h1" and labels["lab"]:
                    return full + f'<span class="secnum">{labels["lab"]}:</span> '
                if h in hn:
                    return full + f'<span class="secnum">{hn[h]}</span> '
                return full
            html = _HEADING_RE.sub(num_heading, html)

            fc = float_caps.get(sec["slug"], {})
            if fc:
                def num_fig(mo):
                    fid = mo.group("id")
                    block = mo.group(0)
                    if fid in fc:
                        word, num = fc[fid]
                        block = _FIGCAP_RE.sub(
                            r'\1<span class="fignum">' + word + " " + num
                            + r':</span> ', block, count=1)
                    return block
                html = _FIG_RE.sub(num_fig, html)

                # a caption-less standalone figure renders as a bare <img id="fig:x">
                # (no <figure>/<figcaption> for num_fig to hit) — promote it to a
                # numbered <figure> so the ref lands and the number shows.
                for fid, (word, num) in fc.items():
                    if f'id="{fid}"' in html and f'<figure id="{fid}"' not in html:
                        def promote(mo, fid=fid, word=word, num=num):
                            img = re.sub(r'\s*\bid="[^"]*"', '', mo.group(0))
                            return (f'<figure id="{fid}" class="figure">{img}'
                                    f'<figcaption class="figure-caption">'
                                    f'<span class="fignum">{word} {num}:</span>'
                                    f'</figcaption></figure>')
                        html = re.sub(r'<img\b[^>]*\bid="' + re.escape(fid)
                                      + r'"[^>]*>', promote, html, count=1)

            # tables: "Table C.n:" prefix into the <caption> of <table id="tbl:…">
            for tid, num in table_caps.get(sec["slug"], {}).items():
                label = '<span class="fignum">Table ' + num + ':</span> '
                new = re.sub(
                    r'(<table\b[^>]*\bid="' + re.escape(tid)
                    + r'"[^>]*>\s*<caption[^>]*>)', r'\1' + label, html, count=1)
                if new == html:
                    # a table rendered as an image (<figure id="tbl:…"> … <figcaption>)
                    new = re.sub(
                        r'(<figure\b[^>]*\bid="' + re.escape(tid)
                        + r'"[^>]*>.*?<figcaption[^>]*>)', r'\1' + label,
                        html, count=1, flags=re.S)
                html = new

            # sub-table floats: shared "Table C.n:" in the main caption, "(a)" …
            # in each panel <table>'s own <caption>.
            for mid, (num, lettered) in subtable_caps.get(sec["slug"], {}).items():
                html = re.sub(
                    r'(<figure id="' + re.escape(mid) + r'" class="subtables"'
                    r'[^>]*>.*?<figcaption class="subtables-caption">)',
                    r'\1<span class="fignum">Table ' + num + ':</span> ',
                    html, count=1, flags=re.S)
                for sid, letter in lettered:
                    html = re.sub(
                        r'(<table\b[^>]*\bid="' + re.escape(sid)
                        + r'"[^>]*>\s*<caption[^>]*>)',
                        r'\1<span class="subfignum">(' + letter + ')</span> ',
                        html, count=1)

            # subfigure floats: inject the shared "Figure C.n:" into the main
            # caption and "(a)" … into each panel (done here, not via _FIG_RE,
            # because the nested <figure>s confuse its non-greedy match).
            for mid, (num, lettered) in subfig_caps.get(sec["slug"], {}).items():
                html = re.sub(
                    r'(<figure id="' + re.escape(mid) + r'" class="figure '
                    r'subfigures"[^>]*>.*?<figcaption class="subfigures-caption">)',
                    r'\1<span class="fignum">Figure ' + num + ':</span> ',
                    html, count=1, flags=re.S)
                for sid, letter in lettered:
                    # bound to the panel's OWN figcaption (stop at its </figure>)
                    # so a label-suppressed (tabular) panel with no figcaption
                    # doesn't pull the letter into a later panel's caption.
                    html = re.sub(
                        r'(<figure id="' + re.escape(sid) + r'" '
                        r'class="subfigure">(?:(?!</figure>).)*?<figcaption>)',
                        r'\1<span class="subfignum">(' + letter + ')</span> ',
                        html, count=1, flags=re.S)

            for lid, (lnum, cap) in listing_caps.get(sec["slug"], {}).items():
                cap_html = re.sub(r"`([^`]+)`", r"<code>\1</code>", cap)
                inject = (f'<div class="listing-caption"><span class="fignum">'
                          f'Listing {lnum}:</span> {cap_html}</div>')
                html = re.sub(r'(<div\b[^>]*\bid="' + re.escape(lid) + r'"[^>]*>)',
                              lambda mo, inj=inject: mo.group(1) + inj, html, count=1)

            def resolve(mo):
                cap = mo.group(1) == "Hashref"  # .Hashref capitalizes
                out = _render_refs(mo.group(2), targets, cap_class=cap)
                # leave unresolved refs (missing targets) as-is
                return out if out is not None else mo.group(0)
            html = _HASHREF_RE.sub(resolve, html)

            cited = []  # bib keys cited in this section, in order

            def resolve_cite(mo):
                keys = mo.group(1).split()
                parts = []
                for k in keys:
                    t = _lookup_target(k, targets)
                    if t:  # cross-reference written as [@fig:x]/[@Fig:x]/[@s4]
                        label = _recase_label(t["label"], k[:1].isupper())
                        parts.append(
                            f'<a class="xref" href="{t["url"] or "#"}">{label}</a>')
                    elif k in references:  # real bibliography citation
                        if k not in cited:
                            cited.append(k)
                        parts.append(f'<a class="cite" href="#ref-{k}">'
                                     f'{_esc(references[k]["label"])}</a>')
                    else:
                        return mo.group(0)  # unknown key → leave span as-is
                return ", ".join(parts)
            html = _CITE_RE.sub(resolve_cite, html)

            if cited:
                items = "".join(f'<li id="ref-{k}">{_esc(references[k]["full"])}</li>'
                                for k in cited)
                html += ('<section class="references"><h2>References</h2>'
                         f'<ol>{items}</ol></section>')

            # Rights-restricted figures (permission=permission, licensed art) are
            # shown on gated/preview pages but NOT on public ones — there the
            # image is swapped for a print-only placeholder (caption/number stay).
            if not sec.get("preview"):
                html = _gate_rights_figures(html)

            html = _anchor_index_spans(html, "ix-" + (sec.get("hash") or sec.get("slug") or ""))
            sec["html"] = html
    return targets
