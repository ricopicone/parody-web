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

_HEADING_RE = re.compile(r'(<(h[1-6])\b[^>]*\bdata-h="(?P<hash>[^"]+)"[^>]*>)')
_FIG_RE = re.compile(r'<figure\b[^>]*\bid="(?P<id>fig:[^"]+)"[^>]*>(?P<rest>.*?)</figure>',
                     re.S)
_FIGCAP_RE = re.compile(r'(<figcaption[^>]*>)', re.S)
_HASHREF_RE = re.compile(r'<span class="hashref">([^<]*)</span>')

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


def number_artifact(data):
    """Mutate `data` in place: set chapter['number'] / section['number'] and
    rewrite section['html'] with numbered headings/figures and resolved refs.
    Returns the hash→{label,url} map (handy for tests)."""
    targets = {}          # hash/id -> {"label":..., "url":...}
    heading_numbers = {}  # per-section: hash -> number string (for html rewrite)
    fig_numbers = {}      # per-section: fig-id -> number string
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
                    fig_numbers.setdefault(sec["slug"], {})[a["id"]] = num

    # ---- pass 2: rewrite html (numbers in headings/figs, resolve hashrefs) ----
    for ch in data.get("chapters", []):
        for sec in ch.get("sections", []):
            html = sec.get("html") or ""
            if not html:
                continue
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

            fn = fig_numbers.get(sec["slug"], {})
            if fn:
                def num_fig(mo):
                    fid = mo.group("id")
                    block = mo.group(0)
                    if fid in fn:
                        block = _FIGCAP_RE.sub(
                            r'\1<span class="fignum">Figure ' + fn[fid] + r':</span> ',
                            block, count=1)
                    return block
                html = _FIG_RE.sub(num_fig, html)

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

            sec["html"] = html
    return targets
