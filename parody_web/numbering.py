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
_HASHREF_RE = re.compile(r'<span class="hashref">([^<]*)</span>')
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


def _cref_link(key, targets):
    t = targets.get(key)
    return f'<a class="xref" href="{t["url"] or "#"}">{t["label"]}</a>' if t else ""


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
        c = re.sub(r"\\[cC]ref\{([^}]*)\}",
                   lambda m: _cref_link(m.group(1), targets), c)
        c = _FMT_CMD_RE.sub("", c)
        return c.strip()
    return _RAWTEX_RE.sub(sub, html)


_MENU_RE = re.compile(r'<span class="menu">([^<]*)</span>')
# Eclipse debugger toolbar buttons referenced by token → icon (staged in media)
_ECLIPSE_ICONS = {
    "estepover": ("stepover", "Step Over"), "estepinto": ("stepinto", "Step Into"),
    "estepreturn": ("stepreturn", "Step Return"), "eresume": ("resume", "Resume"),
    "eterminate": ("terminate", "Terminate"),
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


def _section_kind(sec):
    html = sec.get("html") or ""
    if (sec.get("title") or "").strip().lower() == "problems":
        return "problems"
    if re.search(r'<h1\b[^>]*class="[^"]*\blab\b', html):
        return "lab"
    if sec.get("slug") == "lead-in" or not sec.get("anchors"):
        return "leadin"
    return "normal"


def number_artifact(data, references=None):
    """Mutate `data` in place: set chapter['number'] / section['number'] and
    rewrite section['html'] with numbered headings/figures and resolved refs.
    `references` maps a bib key -> {"label","full"}; bibliography citations are
    linked and a per-section References list is appended. Returns the target map."""
    references = references or {}
    targets = {}          # hash/id -> {"label":..., "url":...}
    heading_numbers = {}  # per-section: hash -> number string (for html rewrite)
    float_caps = {}       # per-section: float-id -> (label_word, number)
    listing_caps = {}     # per-section: lst-id -> (number, caption)
    idx_state = {"arabic": 0, "appendix": 0}
    lab_n = 0

    # ---- pass 1: assign numbers, build the target map ----
    for ch in data.get("chapters", []):
        cnum = _chapter_label(ch, idx_state)
        ch["number"] = cnum
        if ch.get("hash"):
            targets[ch["hash"]] = {"label": f"Chapter {cnum}", "url": None,
                                   "chapter": ch}
        sec_m = 0
        type_counters = {}  # per-chapter counters for figure/table/equation/…
        for sec in ch.get("sections", []):
            kind = _section_kind(sec)
            url = f"/{ch['slug']}/{sec['slug']}/"
            if kind == "normal":
                sec_m += 1
                secnum = f"{cnum}.{sec_m}"
                sec["number"] = secnum
            elif kind == "lab":
                lab_n += 1
                secnum = None
                sec["number"] = f"Lab Exercise {lab_n}"
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

            # non-heading targets (figures, tables, equations, exercises, …),
            # numbered per chapter per type in anchor (document) order. The
            # registry keys on both id (fig:…/tbl:…) and 2-char hash (exercises).
            for a in sec.get("anchors", []):
                t = a.get("type")
                if t == "heading" or t not in _TYPE_LABELS:
                    continue
                type_counters[t] = type_counters.get(t, 0) + 1
                num = f"{cnum}.{type_counters[t]}"
                entry = {"label": f"{_TYPE_LABELS[t]} {num}",
                         "url": f"{url}#{a.get('id', '')}"}
                if a.get("id"):
                    targets[a["id"]] = entry
                if a.get("hash"):
                    targets[a["hash"]] = entry
                if t == "figure" and a.get("id"):
                    float_caps.setdefault(sec["slug"], {})[a["id"]] = ("Figure", num)

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

            for lid, (lnum, cap) in listing_caps.get(sec["slug"], {}).items():
                cap_html = re.sub(r"`([^`]+)`", r"<code>\1</code>", cap)
                inject = (f'<div class="listing-caption"><span class="fignum">'
                          f'Listing {lnum}:</span> {cap_html}</div>')
                html = re.sub(r'(<div\b[^>]*\bid="' + re.escape(lid) + r'"[^>]*>)',
                              lambda mo, inj=inject: mo.group(1) + inj, html, count=1)

            def resolve(mo):
                tgt = mo.group(1)
                t = targets.get(tgt)
                if not t and tgt[:1].isupper():  # sentence-start "Fig:"/"Tbl:"
                    t = targets.get(tgt[:1].lower() + tgt[1:])
                if not t:
                    return mo.group(0)  # leave unresolved refs (missing targets) as-is
                url = t["url"]
                if url is None and t.get("chapter"):  # chapter ref → first section
                    secs = t["chapter"].get("sections", [])
                    url = f"/{t['chapter']['slug']}/{secs[0]['slug']}/" if secs else "#"
                return f'<a class="xref" href="{url or "#"}">{t["label"]}</a>'
            html = _HASHREF_RE.sub(resolve, html)

            cited = []  # bib keys cited in this section, in order

            def resolve_cite(mo):
                keys = mo.group(1).split()
                parts = []
                for k in keys:
                    t = targets.get(k)
                    if t:  # cross-reference written as [@fig:x]/[@tbl:x]
                        parts.append(
                            f'<a class="xref" href="{t["url"] or "#"}">{t["label"]}</a>')
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

            sec["html"] = html
    return targets
