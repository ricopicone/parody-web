"""Number a parody artifact (chapters, sections, subsections, figures) and
resolve its cross-references, at import time.

The artifact ships unnumbered: headings carry stable short hashes (``data-h`` /
``anchors``) and cross-references are ``<span class="hashref">TARGET</span>``
where TARGET is a heading hash (2 chars), a chapter hash, or a ``fig:``/``tbl:``
… id. Print gets numbering from LaTeX; the web build does not, so we compute it
here and rewrite the stored html:

* chapters → ``1, 2, …`` (arabic) or ``A, B, …`` (appendix)
* sections → ``C.m`` — except "Problems" (unnumbered) and labs ("Lab exercise N",
  N = the chapter number, not a running count of lab sections)
* subsections → ``C.m.k[.j]`` within numbered sections
* figures → ``Figure C.k`` (per chapter), captions prefixed
* exercises → ``Problem C.n`` (own per-chapter counter) and lab problems →
  ``Problem LC.n`` (their own separate per-chapter counter), each with a
  run-in heading injected into the box (see ``_rewrite_exercise_box``);
  cross-refs read "problem"/"lab problem" per the book's crefnames
* ``hashref`` spans → links showing the target's label ("Section 3.2", "Figure 3.1", …)

Conventions (Problems/labs numbered per-chapter on separate counters, section
titles unnumbered) match the book's print layout. Targets it can't resolve
(tbl:/eq:/… for now) are left as-is.
"""
import re
from html import escape as _esc
from html.parser import HTMLParser

_HEADING_RE = re.compile(r'<h(?P<level>[1-6])\b(?P<attrs>[^>]*)>')
_ATTR_ID_RE = re.compile(r'\bid="([^"]*)"')
_ATTR_HASH_RE = re.compile(r'\bdata-h="([^"]*)"')
# How deep a heading number goes, counting from the section: 1 = subsection
# (C.m.k), 2 = subsubsection (C.m.k.j). Below that headings go unnumbered,
# matching the print class's \setsecnumdepth{subsubsection} (#576).
_MAX_HEADING_DEPTH = 2
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

# Further-reading boxes (::: {.freadinglist}) list recommended sources as
# [key]{.plaincite post="…"} spans, which pandoc renders as
# <span class="plaincite" data-post="…">key</span> (some carry data-postpost
# instead). Resolve each key against the bibliography (Author (Year), linked) and
# append its note, exactly as the print build's \textcite[…][post]{key} does, then
# lay the whole box out as a titled bulleted list (one <li> per source).
# _FREADING_BOX_RE matches the whole box; _PLAINCITE_RE matches one entry span.
_PLAINCITE_RE = re.compile(
    r'<span class="(?:[^"]*\s)?plaincite(?:\s[^"]*)?"((?:\s+[\w-]+="[^"]*")*)\s*>'
    r'([^<]*)</span>')
_PLAINCITE_NOTE_RE = re.compile(r'data-post(?:post)?="([^"]*)"')
_FREADING_BOX_RE = re.compile(
    r'(<div\b(?=[^>]*\bclass="(?:[^"]*\s)?freadinglist(?:\s[^"]*)?")[^>]*>)'
    r'.*?</div>', re.S)


def _dashes(s):
    """em/en-dash literal --- / -- in a post-note, matching print typography."""
    return s.replace("---", "—").replace("--", "–")

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


# MathJax renders inline math into an <mjx-container>, which is an atomic
# inline box — and a line may break between an atomic inline and the text after
# it. So a sentence ending in math would strand its full stop at the start of
# the next line ("… the resistance R\n. The current …"), and the same for the
# comma in a list of symbols. There is no CSS for this: white-space controls
# breaks INSIDE an element, not the one after it, and the punctuation is a
# separate text node with no element to hold.
#
# U+2060 WORD JOINER is a zero-width character that forbids a break at its
# position. Sliding one between the math and the punctuation binds them.
# (U+FEFF, the other zero-width no-break character, is deprecated for this and
# was measured NOT to prevent the break.)
_MATH_PUNCT_RE = re.compile(
    r'(<span class="math inline">(?:(?!</span>).)*</span>)([.,;:!?)\]}])', re.S)
_WORD_JOINER = "⁠"


def _bind_math_punctuation(html):
    """Stop a line break stranding punctuation that follows inline math."""
    return _MATH_PUNCT_RE.sub(rf'\1{_WORD_JOINER}\2', html)


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
    if not t:
        # environment refs carry a type prefix the target id may lack:
        # definitions/theorems/comments are anchored on their bare id
        # (::: {#magnitude-criterion .definition}) but referenced as
        # [def:magnitude-criterion]{.hashref}. Strip the prefix and retry.
        m = re.match(r'(?:def|thm|cmt):(.+)$', tgt, re.I)
        if m:
            t = targets.get(m.group(1))
    if not t and "ex" in tgt.split(":"):
        # xsim namespaces labels declared inside an exercise/solution; 'ex' shows
        # up as a segment whether the label leads with a type
        # (fig:ex:fsm1:sol:fig:state-transition-diagram) or not
        # (ex:fsm1:tab:state-transition). The rendered float keeps only the leaf
        # id; a LaTeX 'tab:' leaf is pandoc-crossref's 'tbl:'.
        segs = tgt.split(":")
        if len(segs) >= 2:
            leaf_type = "tbl" if segs[-2] == "tab" else segs[-2]
            t = targets.get(f"{leaf_type}:{segs[-1]}")
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


def _alpha_num(s):
    """A, B, … Z, AA, … -> 1, 2, … (appendix chapter letters), base-26."""
    n = 0
    for ch in s:
        n = n * 26 + (ord(ch) - 64)
    return n


_NUM_COMP_RE = re.compile(r"(\d+)([a-z]*)")
# a lab problem's chapter component ("L4" in "L4.1") — only the leading part
# of a dotted number ever takes this form.
_NUM_LAB_RE = re.compile(r"L(\d+)")


def _num_components(s):
    """Parse a reference number ("(9.7)", "3.2.1", "B.4", "8.10a", "L4.1") into a
    list of comparable components, or None if it isn't a clean dotted number.
    Each component is (kind, int, letter): kind 0 = numeric ("7"→(0,7,""),
    "10a"→(0,10,"a")), kind 1 = an appendix letter ("B"→(1,2,"")), kind 2 = a
    lab problem's chapter ("L4"→(2,4,""), leading component only). Kind 2's
    distinct tag keeps lab numbers in their own sort domain — a differing kind
    fails _consecutive's same-kind check and mismatches the shared prefix that
    _compress_refs groups a run by, so "L4.1" and "4.1" never compress into one
    range even though their digits collide. The tuples otherwise sort in
    reading order and let _consecutive test adjacency."""
    comps = []
    parts = s.strip("() ").split(".")
    for i, p in enumerate(parts):
        m = _NUM_COMP_RE.fullmatch(p)
        if m:
            comps.append((0, int(m.group(1)), m.group(2)))
            continue
        lm = _NUM_LAB_RE.fullmatch(p) if i == 0 else None
        if lm:
            comps.append((2, int(lm.group(1)), ""))
        elif p.isalpha() and p.isupper():
            comps.append((1, _alpha_num(p), ""))
        else:
            return None
    return comps or None


def _consecutive(a, b):
    """True if number b immediately follows a (same prefix; last component +1, or
    the same number with the next letter — 8.10a→8.10b)."""
    if not a or not b or len(a) != len(b) or a[:-1] != b[:-1]:
        return False
    (ka, na, la), (kb, nb, lb) = a[-1], b[-1]
    if ka != kb:
        return False
    if la == lb:
        return nb == na + 1
    return na == nb and len(la) == len(lb) == 1 and ord(lb) == ord(la) + 1


def _compress_refs(items):
    """Render a list of (number_string, url) cross-refs the way cleveref's
    sort&compress does: sort by number, then collapse each run of 3+ consecutive
    into "first to last" (runs of 1–2 are listed); join with an Oxford "and".
    e.g. (9.7),(9.8),(9.9) -> "(9.7) to (9.9)"; (2.4),(2.5) -> "(2.4) and (2.5)".
    If any number doesn't parse cleanly the list is left in document order and
    only listed (no sort/compress)."""
    keyed = [(_num_components(n), n, u) for n, u in items]
    if all(k is not None for k, _, _ in keyed):
        keyed.sort(key=lambda x: x[0])
    elements, i = [], 0
    while i < len(keyed):
        j = i
        while (j + 1 < len(keyed) and keyed[j][0] is not None
               and _consecutive(keyed[j][0], keyed[j + 1][0])):
            j += 1
        if j - i >= 2:  # a run of 3+ -> a "first to last" range
            elements.append(_link(keyed[i][1], keyed[i][2]) + " to "
                            + _link(keyed[j][1], keyed[j][2]))
        else:
            elements += [_link(n, u) for _k, n, u in keyed[i:j + 1]]
        i = j + 1
    return _join_oxford(elements)


def _render_refs(tgt, targets, cap_class=False):
    """Resolve a cross-ref target, which may be a comma-separated list of keys
    ([4n,us,rq]{.hashref} → "chapters 2, 3, and 4", each number linked). When the
    targets share a label word the word is factored out and pluralized; otherwise
    the full labels are listed. Returns None if any key is unresolved (the caller
    then leaves the span as-is rather than rendering a half-broken ref).

    Case follows the reference site (task #296): cap_class is set when the span
    asked to capitalize (a .Hashref / \\Cref), and an upper-case key letter
    (Fig:, S4) also capitalizes — otherwise the label is lower-cased."""
    keys = [k.strip() for k in tgt.split(",") if k.strip()]
    if not keys:
        return None
    resolved = []
    for k in keys:
        t = _lookup_target(k, targets)
        if not t:
            return None
        resolved.append((t, k))

    def _one(t, k):
        # titled targets (infoboxes labelled by their proper-noun title) keep
        # their case verbatim — don't lower-case "Control System Design Problem"
        # the way a numbered "Figure 3.1" first letter is recased (task #296).
        if t.get("titled"):
            return t["label"]
        return _recase_label(t["label"], cap_class or k[:1].isupper())

    if len(resolved) == 1:
        t, k = resolved[0]
        return _link(_one(t, k), _target_url(t))

    # multiple refs that share a label word (all equations, all sections, …):
    # factor the word out, pluralize it, and sort&compress the numbers like the
    # print build's cleveref — "equations (9.7) to (9.9)", "sections 2.1 and 2.2".
    raws = [t["label"] for t, _ in resolved]
    words = {r.rsplit(" ", 1)[0] for r in raws if " " in r}
    if (not any(t.get("titled") for t, _ in resolved)
            and len(words) == 1 and all(" " in r for r in raws)):
        # the whole group takes one case (the reference site's), like \cref
        cap = cap_class or keys[0][:1].isupper()
        word = _recase_label(next(iter(words)), cap)
        items = [(t["label"].rsplit(" ", 1)[1], _target_url(t)) for t, _ in resolved]
        return f"{word}s {_compress_refs(items)}"
    # mixed kinds (or titled): list the full labels, each cased by its own key
    return _join_oxford([_link(_one(t, k), _target_url(t)) for t, k in resolved])


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
# "exercise" is listed only so the loop's `t not in _TYPE_LABELS` membership
# guard admits it; its dedicated branch above always `continue`s before this
# map's value is ever read, so None (rather than a live-looking "Problem")
# makes that unreachability honest — lab and non-lab problems get their label
# ("Problem"/"Lab problem") built in that branch instead.
_TYPE_LABELS = {
    "figure": "Figure", "table": "Table", "equation": "Equation",
    "exercise": None, "example": "Example", "theorem": "Theorem",
    "definition": "Definition", "comment": "Comment",
    "listing": "Listing", "algorithm": "Algorithm",
}

#: Boxed environments that show their number in the box's own header rather
#: than only in the cross-refs pointing at it (see _rewrite_env_boxes).
#: Examples and exercises are numbered too but carry the label in a
#: presentation of their own (.example-label / .problem-label), and infoboxes
#: are referenced by title and never numbered at all.
_ENV_LABELLED = frozenset({"definition", "theorem", "comment"})


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


_SUBEQ_RE = re.compile(
    r'<div\b[^>]*\bclass="subequations"[^>]*>.*?</div>', re.S)
_SUBEQ_ID_RE = re.compile(r'<div\b[^>]*\bid="(eq:[^"]+)"[^>]*\bclass="subequations"'
                          r'|<div\b[^>]*\bclass="subequations"[^>]*\bid="(eq:[^"]+)"')
_SUBEQ_MATH_RE = re.compile(r'<span class="math display">(.*?)</span>', re.S)
_SUBEQ_ENV_RE = re.compile(
    r'\\begin\{(align\*?|aligned|gather\*?|flalign\*?)\}(.*?)\\end\{\1\}', re.S)
_SUBEQ_SKIP_RE = re.compile(r'\\nonumber|\\notag')
_SUBEQ_LABEL_RE = re.compile(r'\\label\{(eq:[^}]+)\}')

# MathJax forbids \tag inside the INNER alignment environments (aligned,
# gathered) — it raises "\tag not allowed in aligned environment". pandoc emits
# whatever environment the source markdown used, and the rtc source uses the
# inner \begin{aligned}; so a \tag dropped into a numbered row (or one the author
# wrote, e.g. \tag{KVL}) chokes MathJax. A standalone \[\begin{aligned}…\end{…}\]
# is equivalent to the top-level \begin{align}…\end{align}, which DOES permit
# \tag and — with MathJax tags:'none' — still numbers only the \tag-ged rows. So
# whenever such a block carries a \tag, promote the inner environment to its
# outer twin (and drop the now-redundant \[ \] display delimiters).
_PROMOTE_ENV = {"aligned": "align", "gathered": "gather"}
_TAGGED_ALIGNED_RE = re.compile(
    r'\\\[\s*\\begin\{(aligned|gathered)\}(.*?)\\end\{\1\}\s*\\\]', re.S)


# A numbered equation's scroll target is a trailing <span id="eq:..."></span>
# the build appends AFTER the math span; relocate it to just before the math (see
# call site) so a cross-ref scrolls to the equation rather than just past it.
_ANCHOR_AFTER_MATH_RE = re.compile(
    r'(<span class="math display">(?:(?!</span>).)*</span>)'
    r'((?:\s*<span id="eq:[^"]+"></span>)+)', re.S)


def _relocate_eq_anchors(mo):
    """Move the trailing eq-anchor span(s) to immediately before their math span
    and tag them .eqanchor (for scroll-margin + the :target highlight)."""
    math, trailing = mo.group(1), mo.group(2)
    ids = re.findall(r'<span id="(eq:[^"]+)"></span>', trailing)
    moved = "".join(f'<span class="eqanchor" id="{i}"></span>' for i in ids)
    return moved + math


def _promote_tagged_aligned(body):
    r"""Promote a standalone \[\begin{aligned}…\end{aligned}\] (or {gathered})
    that contains a \tag to the tag-permitting top-level \begin{align}…\end{align}
    (or {gather}). Blocks without a \tag, and aligned envs nested inside other
    math (e.g. a \left\{…\right. cases group), are left untouched."""
    def repl(mo):
        if r"\tag" not in mo.group(2):
            return mo.group(0)
        env = _PROMOTE_ENV[mo.group(1)]
        return r"\begin{" + env + "}" + mo.group(2) + r"\end{" + env + "}"
    return _TAGGED_ALIGNED_RE.sub(repl, body)


def _subeq_align(block):
    r"""Parse the aligned math inside a subequations <div>. Returns
    (parts, numbered) where parts = re.split(r'(\\)', inner) of the alignment
    environment's body, and numbered is [(part_index, letter, label_id|None), …]
    — one entry per NUMBERED row (skipping \nonumber/\notag and blank rows), in
    order, lettered a, b, c…. Returns (None, []) if there is no aligned math."""
    mm = _SUBEQ_MATH_RE.search(block)
    if not mm:
        return None, []
    env = _SUBEQ_ENV_RE.search(mm.group(1))
    if not env:
        return None, []
    parts = re.split(r'(\\\\)', env.group(2))
    numbered, i = [], 0
    for k in range(0, len(parts), 2):
        row = parts[k]
        if not row.strip() or _SUBEQ_SKIP_RE.search(row):
            continue
        lab = _SUBEQ_LABEL_RE.search(row)
        numbered.append((k, chr(97 + i), lab.group(1) if lab else None))
        i += 1
    return parts, numbered


def _subeq_structure(html):
    """Map each <div class="subequations" id="eq:P"> to its labelled rows as
    [(sub_id, letter), …] (only rows that carry a \\label are cross-referenceable;
    unlabelled rows are still lettered and \\tag-ged, just never pointed at)."""
    out = {}
    for m in _SUBEQ_RE.finditer(html):
        block = m.group(0)
        idm = _SUBEQ_ID_RE.search(block)
        if not idm:
            continue
        pid = idm.group(1) or idm.group(2)
        _, numbered = _subeq_align(block)
        out[pid] = [(lab, letter) for _k, letter, lab in numbered if lab]
    return out


def _number_subeq_div(block, num):
    r"""Inject \tag{N a}, \tag{N b}, … into each numbered row of a subequations
    block's aligned math (dropping the now-redundant \label), so MathJax prints
    one lettered number per row exactly like the print book's subequations."""
    parts, numbered = _subeq_align(block)
    if not numbered:
        return block
    mm = _SUBEQ_MATH_RE.search(block)
    inner_old = _SUBEQ_ENV_RE.search(mm.group(1)).group(2)
    for k, letter, _lab in numbered:
        row = _SUBEQ_LABEL_RE.sub("", parts[k])
        trail = row[len(row.rstrip()):]
        parts[k] = row.rstrip() + r" \tag{" + num + letter + "}" + trail
    new_math = mm.group(0).replace(inner_old, "".join(parts), 1)
    return block[:mm.start()] + new_math + block[mm.end():]


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


# The exercise box comes from parody's filter.lua as Tailwind markup, because
# homepage-django renders those class names for real. The book site wants what
# print gives: a run-in "Problem N.n" heading over the statement. So rewrite the
# box here — normalize the wrapper's classes, swap the <h3>Exercise</h3> header
# block for a .problem-label, and rename the Tailwind body wrapper. pandoc wraps
# long tags across lines, so every part below matches newlines too.
def _rewrite_exercise_box(html, eid, label, is_lab):
    """Rewrite one exercise div (matched by `eid`) into its web presentation.

    The legacy header's <h3> carries a title when the source exercise had a
    title= attribute (filter.lua defaults it to the literal "Exercise" when
    absent). That default is discarded, but a real title survives, appended
    after the number rather than dropped (task #499 F2)."""
    pat = re.compile(
        r'(<div\b(?=[^>]*\bdata-env-type="exercise")[^>]*\bid="'
        + re.escape(eid) + r'"[^>]*>)'
        r'(?:\s*<section\b[^>]*>\s*<h3\b[^>]*>(?P<h3>[^<]*)</h3>\s*</section>)?'
        r'(?P<bodytag>\s*<div\b[^>]*\bclass="px-4 py-3 text-sm text-gray-700"[^>]*>)?')

    def rep(mo):
        cls = "exercise lab" if is_lab else "exercise"
        open_tag = re.sub(r'\bclass="[^"]*"', f'class="{cls}"', mo.group(1),
                          count=1)
        # collapse the newlines pandoc wrapped into the opening tag
        open_tag = re.sub(r'\s+', " ", open_tag)
        body = '<div class="problem-body">' if mo.group('bodytag') else ""
        title = (mo.group('h3') or "").strip()
        title_html = (f' <span class="problem-title">{title}</span>'
                      if title and title != "Exercise" else "")
        return (open_tag + f'<div class="problem-label">{label}{title_html}'
                '</div>' + body)

    return pat.sub(rep, html, count=1)


# The remaining boxed environments — definitions, theorems, comments, infoboxes
# and anything filter.lua adds later — arrive as the same Tailwind markup the
# exercise box does: a wrapper div, a header <section> holding an <h3>, and a
# body div. On homepage-django those utility classes resolve; here they are
# inert, so until task #565 every one of these rendered as undecorated prose.
# Swap the header for a semantic .env-head and let content.css draw the box.
#
# Two environments are excluded because they already have a web presentation of
# their own: .example (corner brackets) and .exercise (a run-in "Problem N.n"
# heading). Everything else is matched by the presence of data-env-type, so a
# new environment in filter.lua is boxed without a change here or in the CSS.
_ENV_BOX_RE = re.compile(
    r'(?P<open><div\b(?=[^>]*(?:\bdata-env-type="(?!example"|exercise")[^"]*"'
    r'|\bclass="(?:[^"]*\s)?infobox(?:\s[^"]*)?"))[^>]*>)'
    r'(?:\s*<section\b[^>]*>\s*<h3\b[^>]*>(?P<title>.*?)</h3>\s*</section>)?',
    re.S)
_ENV_TYPE_RE = re.compile(r'\bdata-env-type="([^"]*)"')
_ENV_ID_RE = re.compile(r'\bid="([^"]*)"')


def _rewrite_env_boxes(html, caps):
    """Give each boxed environment a semantic header the site can style.

    `caps` maps a box's id to the label its cross-refs use ("Theorem 4.1"), so
    the header agrees with the link that brought the reader there — before this
    the box read a bare "Theorem" while the reference said "Theorem 4.1". A box
    absent from `caps` simply gets no number: infoboxes are referenced by title
    and never numbered, and an environment written without an #id has nothing
    to reference and so never got a number to show.

    filter.lua defaults the header to the environment's own name when the
    author set no title=, so a title equal to the type word is that default and
    gives way to the number; a real title survives beside it. A box with
    neither (an untitled infobox) loses the header rather than drawing an empty
    band.
    """
    def rep(mo):
        open_tag = mo.group("open")
        m = _ENV_TYPE_RE.search(open_tag)
        env = m.group(1) if m else "infobox"
        m = _ENV_ID_RE.search(open_tag)
        label = caps.get(m.group(1)) if m else None
        title = re.sub(r"\s+", " ", mo.group("title") or "").strip()
        if title.casefold() == env.casefold():
            # filter.lua's default header: the environment's own name. It is
            # redundant beside a number, but where there is none (a definition
            # written without an #id is never referenced and so never numbered)
            # it is the only label the box has — promote it to one.
            label, title = label or title, ""
        head = ""
        if label:
            head += f'<span class="env-num">{label}</span>'
        if title:
            head += f'<span class="env-title">{title}</span>'
        return open_tag + (f'<div class="env-head">{head}</div>' if head else "")

    return _ENV_BOX_RE.sub(rep, html)


def _label_example_box(html, eid, label):
    """Give one example box its "Example N.n" label, replacing the header band.

    Task #318 added the label but left filter.lua's Tailwind header in place,
    so every example on the site drew its own type word twice: the injected
    "Example 1.1" and then a bare "Example" below it, rendered as a plain <h3>
    because none of the utility classes on it resolve here. Consume that header
    the way the exercise and boxed-environment rewrites do, keeping an author's
    title= (which the header is the only carrier of) beside the number.
    """
    pat = re.compile(
        r'(?P<open><div\b(?=[^>]*\bclass="(?:[^"]*\s)?example(?:\s[^"]*)?")'
        r'[^>]*\bid="' + re.escape(eid) + r'"[^>]*>)'
        r'(?:\s*<section\b[^>]*>\s*<h3\b[^>]*>(?P<title>.*?)</h3>\s*</section>)?',
        re.S)

    def rep(mo):
        title = re.sub(r"\s+", " ", mo.group("title") or "").strip()
        # filter.lua defaults the header to the literal "Example"; that is the
        # number's job here, so only a real title survives
        extra = (f' <span class="example-title">{title}</span>'
                 if title and title.casefold() != "example" else "")
        return (mo.group("open")
                + f'<div class="example-label">{label}{extra}</div>')

    return pat.sub(rep, html, count=1)


def _roman(n):
    """1 -> i, 4 -> iv, … (lower case; the caller upper-cases for <ol type="I">)."""
    out, rest = "", n
    for value, sym in ((1000, "m"), (900, "cm"), (500, "d"), (400, "cd"),
                       (100, "c"), (90, "xc"), (50, "l"), (40, "xl"),
                       (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")):
        while rest >= value:
            out, rest = out + sym, rest - value
    return out


def _alpha_marker(n):
    """1 -> a, 26 -> z, 27 -> aa (how browsers continue <ol type="a"> past z)."""
    out = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        out = chr(97 + rem) + out
    return out


def _list_marker(n, list_type):
    """The marker a browser draws for the nth item of an <ol type=list_type>."""
    if n < 1:
        return str(n)
    if list_type == "a":
        return _alpha_marker(n)
    if list_type == "A":
        return _alpha_marker(n).upper()
    if list_type == "i":
        return _roman(n)
    if list_type == "I":
        return _roman(n).upper()
    return str(n)          # "1", and anything unrecognised


class _ListItemAnchorFinder(HTMLParser):
    """Collect `it:`-prefixed anchor ids and the list marker each one sits under.

    The number a reference must name is the one the reader sees, so it comes off
    the rendered list rather than the source: `<ol start="3">` (pandoc splits a
    list wherever a paragraph interrupts it) and `<ol type>` both count. A
    regex can't do this — an `<li>` may contain a whole nested list, whose items
    must not be counted against the outer one — hence a real parser.

    Anchors outside any list, and anchors in a `<ul>` (no marker to name), are
    left out: no target is registered and the reference stays unresolved, which
    is honest about there being no number rather than inventing one.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.found = {}   # id -> marker string
        self._lists = []  # stack of [ordered, type, next_number, current_marker]

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("ol", "ul"):
            try:
                start = int(a.get("start", 1))
            except ValueError:
                start = 1
            self._lists.append([tag == "ol", a.get("type", "1"), start, None])
        elif tag == "li" and self._lists:
            cur = self._lists[-1]
            cur[3] = _list_marker(cur[2], cur[1]) if cur[0] else None
            cur[2] += 1
        if (a.get("id", "").startswith("it:") and self._lists
                and self._lists[-1][3] is not None):
            self.found.setdefault(a["id"], self._lists[-1][3])

    def handle_endtag(self, tag):
        if tag in ("ol", "ul") and self._lists:
            self._lists.pop()


def _find_list_item_anchors(html):
    """id -> marker for every `it:` anchor in a numbered list item (task #574)."""
    if "it:" not in html:
        return {}
    p = _ListItemAnchorFinder()
    try:
        p.feed(html)
        p.close()
    except Exception:
        # Artifact html is pandoc's, but a malformed fragment must not take the
        # whole numbering pass down — the refs just stay unresolved.
        return p.found
    return p.found


def section_own_heading(html, sec_hash):
    """The section's own title heading in `html`, as a match, or None.

    Usually that is an <h1> the markdown opened with. But a section may instead
    be written as a ``##`` carrying the section's own id — rtc's "The Eclipse
    workspace and hello-world" is one — and then the heading is an <h2> whose
    short hash IS the section's. The hash is what identifies it: a subsection
    has its own, so an equal hash can only be the section itself.
    """
    for mo in _HEADING_RE.finditer(html or ""):
        attrs = mo.group("attrs")
        if not _ATTR_ID_RE.search(attrs) and not _ATTR_HASH_RE.search(attrs):
            continue
        if mo.group("level") == "1":
            return mo
        h = _ATTR_HASH_RE.search(attrs)
        if sec_hash and h and h.group(1) == sec_hash:
            return mo
    return None


def _heading_sequence(html, sec_hash=""):
    """(depth, hash, id) per content heading in `html`, in document order.

    Depth 0 is the section's own title (see `section_own_heading`); depth 1 is
    a subsection, depth 2 a subsubsection. Depth is the tag level less one,
    except that the section's own heading is depth 0 whatever level it was
    written at — so a section authored as a ## takes C.m, and the ## and ###
    under it still read as C.m.k and C.m.k.j.

    A *content* heading is one the reader can address: it carries an id, a
    data-h, or both. That is what separates it from the class-only <h3>
    filter.lua builds as a boxed environment's title band (see filter.lua's
    definition/example/exercise handlers, whose markup is frozen). Reading the
    html rather than the ``anchors`` list is the point: an author who writes a
    plain ``### Determining $R_e$`` gets no anchor, and numbering off anchors
    alone left such headings unnumbered *and* mis-numbered their siblings,
    because they never advanced the counters (#576).
    """
    own = section_own_heading(html, sec_hash)
    seq = []
    for mo in _HEADING_RE.finditer(html or ""):
        attrs = mo.group("attrs")
        hid = _ATTR_ID_RE.search(attrs)
        h = _ATTR_HASH_RE.search(attrs)
        if not hid and not h:
            continue
        depth = 0 if own and mo.start() == own.start() \
            else max(1, int(mo.group("level")) - 1)
        seq.append((depth, h.group(1) if h else None,
                    hid.group(1) if hid else None))
    return seq


def _number_headings(seq, secnum):
    """Running heading numbers for one section: {hash-or-id -> "C.m.k"}.

    Every handle a heading answers to is keyed to the same string, so the
    number it displays and the number a cross-reference to it quotes are the
    one value, computed once.
    """
    numbers = {}
    counters = {}
    for depth, h, hid in seq:
        if depth == 0:
            num = secnum          # the section's own title
        elif not secnum or depth > _MAX_HEADING_DEPTH:
            # Subsections of an unnumbered section (a lab, "Problems") have no
            # C.m to hang off; deeper than subsubsection we stop by choice.
            continue
        else:
            counters[depth] = counters.get(depth, 0) + 1
            for deeper in [d for d in counters if d > depth]:
                counters[deeper] = 0
            num = ".".join([secnum] + [str(counters[d]) for d in sorted(counters)
                                       if d <= depth])
        if num:
            for key in (h, hid):
                if key:
                    numbers[key] = num
    return numbers


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
    eq_caps = {}          # per-section: eq-id -> number (shown right of the math)
    subeq_caps = {}       # per-section: subequations parent-id -> group number N
    example_caps = {}     # per-section: example div-id -> number N.n (label inject)
    problem_caps = {}     # per-section: exercise div-id -> (heading label, is_lab)
    env_caps = {}         # per-section: boxed-env div-id -> "Theorem 4.1"
    # chapter_start: the number the first (non-appendix) chapter takes. The
    # artifact omits it at the default of 1; RTC sets 0 ("Chapter 0").
    # _chapter_label pre-increments "arabic", so seed it one below the start.
    # Section/figure/equation numbers all read cnum, so they inherit it (0.1,
    # Figure 0.4, …). Appendix chapters (lettered) are unaffected.
    idx_state = {"arabic": int(data.get("chapter_start", 1)) - 1, "appendix": 0}

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
                secnum = None
                # The lab number is the CHAPTER number: the book titles these
                # sections "Lab 0" … "Lab 8", and their problems are numbered
                # L<chapter>.<n>. Sentence case ("Lab exercise N") so a cross-ref
                # recases only the first letter — "Lab exercise 6" /
                # "lab exercise 6", never the mid-phrase "lab Exercise 6".
                # (_recase_label toggles label[:1].)
                sec["number"] = f"Lab exercise {cnum}"
            elif kind == "problems":
                secnum = None
                sec["number"] = ""
            else:  # leadin
                secnum = None
                sec["number"] = ""

            # Number every heading the reader actually sees, off the html.
            hseq = _heading_sequence(sec.get("html") or "", sec.get("hash") or "")
            if not hseq:
                # Nothing to read — a stub section, or a consumer that stores
                # the anchors without the html. The anchor list is in document
                # order and carries the markdown's own levels, so it serves.
                hseq = [(0 if a.get("is_section") or a.get("level", 1) == 1
                         else a.get("level", 1) - 1,
                         a.get("hash"), a.get("id"))
                        for a in sec.get("anchors", [])
                        if a.get("type") == "heading"]
            hnums = _number_headings(hseq, secnum)
            if hnums:
                # Keyed by chapter AND section: section slugs repeat across
                # chapters ("summary", "problems"), and unlike a float id a
                # pandoc auto-id is only unique within its own file, so a
                # section-slug key would hand one chapter's numbers to another.
                heading_numbers[(ch["slug"], sec["slug"])] = hnums

            # headings (anchors are in document order): h1 = the section itself
            for a in sec.get("anchors", []):
                if a.get("type") != "heading":
                    continue
                lvl = a.get("level", 1)
                # The writer synthesizes the section's own cross-reference anchor
                # when no heading already carries the frontmatter id, and marks it
                # is_section — "a section-level anchor, not an internal heading".
                # It declares level 2 to match the ## it stands in for, so reading
                # the level alone counted it as the first subsection: it took
                # C.m.1 and pushed every real ## down one (#573). Honour the flag,
                # and the section is the section.
                if a.get("is_section"):
                    lvl = 1
                h = a.get("hash")
                anchor_id = a.get("id", "")

                # register under BOTH the 2-char hash and the heading's own id,
                # exactly as figures/tables/equations/infoboxes do below. Headings
                # used to be hash-only, so a ref written with the id
                # ([@sec:character-codes], [sec:foo]{.hashref}) found no target and
                # fell through raw even though the heading was right there (#500).
                def register(entry, h=h, anchor_id=anchor_id):
                    if h:
                        targets[h] = entry
                    if anchor_id:
                        targets[anchor_id] = entry

                if lvl == 1:
                    if secnum:
                        register({"label": f"Section {secnum}", "url": url})
                    elif sec["number"]:  # lab
                        register({"label": sec["number"], "url": url})
                    else:
                        register({"label": sec.get("title", ""), "url": url})
                elif hnums.get(h) or hnums.get(anchor_id):
                    sub = hnums.get(h) or hnums.get(anchor_id)
                    register({"label": f"Section {sub}",
                              "url": f"{url}#{anchor_id}"})
                else:
                    # A subsection inside an unnumbered section (a lab/problems
                    # section has no C.m number, so its subsections get none
                    # either), or one below the numbered depth. Still register
                    # the heading so refs to it land — labelled by its title
                    # (backticks are markdown, drop them).
                    title = (a.get("title") or "").replace("`", "")
                    register({"label": title, "url": f"{url}#{anchor_id}"})

            # subfigure floats: ::: {.subfigures #fig:main} renders one outer
            # <figure class="figure subfigures"> wrapping <figure class="subfigure">
            # panels. The panels carry fig: ids/anchors too; they share the main's
            # number with a letter — (a), (b), … — so don't count them as figures.
            sf_children = _subfig_structure(sec.get("html") or "")
            sf_subids = {sid for kids in sf_children.values() for sid in kids}
            st_children = _subtable_structure(sec.get("html") or "")
            st_subids = {sid for kids in st_children.values() for sid in kids}

            # subequations groups: one parent number, lettered rows (3.5a, 3.5b).
            # The parent counts as one equation (in document order); the labelled
            # rows share its number with a letter, so don't count them separately.
            subeq_children = _subeq_structure(sec.get("html") or "")
            subeq_subids = {sid for subs in subeq_children.values()
                            for sid, _ in subs}

            # non-heading targets (figures, tables, equations, exercises, …),
            # numbered per chapter per type in anchor (document) order. The
            # registry keys on both id (fig:…/tbl:…) and 2-char hash (exercises).
            for a in sec.get("anchors", []):
                t = a.get("type")
                if t == "infobox":
                    # infoboxes aren't numbered; they're referenced by their
                    # title ("Control System Design Problem"). The title is kept
                    # verbatim on cross-refs (titled=True; see _render_refs).
                    entry = {"label": a.get("title") or "",
                             "url": f"{url}#{a.get('id', '')}", "titled": True}
                    if a.get("id"):
                        targets[a["id"]] = entry
                    if a.get("hash"):
                        targets[a["hash"]] = entry
                    continue
                if t == "heading" or t not in _TYPE_LABELS:
                    continue
                if t == "exercise":
                    # Problems and lab problems run on separate per-chapter
                    # counters, exactly as the book does: `exercise` is
                    # `within = chapter` ("Problem 3.2") and `lab` counts
                    # L\thechapter.\arabic{labexercise} ("Problem L4.1").
                    # Headings read "Problem" for both (exercise-name = Problem);
                    # cross-refs read "problem" / "lab problem" (the crefnames).
                    is_lab = bool(a.get("lab"))
                    key = "labexercise" if is_lab else "exercise"
                    type_counters[key] = type_counters.get(key, 0) + 1
                    num = (f"L{cnum}.{type_counters[key]}" if is_lab
                           else f"{cnum}.{type_counters[key]}")
                    word = "Lab problem" if is_lab else "Problem"
                    entry = {"label": f"{word} {num}",
                             "url": f"{url}#{a.get('id', '')}"}
                    if a.get("id"):
                        targets[a["id"]] = entry
                    if a.get("hash"):
                        targets[a["hash"]] = entry
                    if a.get("id"):
                        # pass 2 injects this as the box's run-in heading and
                        # needs is_lab to set the wrapper's class
                        problem_caps.setdefault(sec["slug"], {})[a["id"]] = \
                            (f"Problem {num}", is_lab)
                    continue
                if (a.get("id") in sf_subids or a.get("id") in st_subids
                        or a.get("id") in subeq_subids):
                    continue  # a sub-panel / subequation row; numbered below
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
                if t in _ENV_LABELLED and a.get("id"):
                    # pass 2 shows this in the box's own header band, so the
                    # header and the cross-ref that links to it agree
                    env_caps.setdefault(sec["slug"], {})[a["id"]] = entry["label"]
                if t == "example" and a.get("id"):
                    # record the number so pass 2 can inject an "Example N.n"
                    # label into the boxed environment (the web mirrors the
                    # print book's boxed-example title).
                    example_caps.setdefault(sec["slug"], {})[a["id"]] = num
                if t == "equation" and a.get("id") in subeq_children:
                    # a subequations group: the parent keeps the bare number "(N)";
                    # each labelled row is "(N a)" and is rendered (and \tag-ged) in
                    # pass 2. Record N for the pass-2 row tagging.
                    subeq_caps.setdefault(sec["slug"], {})[a["id"]] = num
                    for sub_id, letter in subeq_children[a["id"]]:
                        targets[sub_id] = {
                            "label": f"Equation ({num}{letter})",
                            "url": f"{url}#{sub_id}"}
                elif t == "equation" and a.get("id"):
                    # plain numbered equation: pass 2 shows the number as a \tag.
                    eq_caps.setdefault(sec["slug"], {})[a["id"]] = num
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
            # numbered-list items ([]{#it:..} inside an enumerate) are likewise
            # absent from `anchors`: the number is a property of the rendered
            # list, so read it back off the html. "item N" and the number itself
            # both match the print build, where cleveref types these `enumi`.
            # Nothing is injected into the page — the anchor is already there,
            # and the list draws its own markers.
            for anchor_id, marker in _find_list_item_anchors(sh).items():
                targets[anchor_id] = {"label": f"Item {marker}",
                                      "url": f"{url}#{anchor_id}"}

    # ---- pass 2: rewrite html (numbers in headings/figs, resolve hashrefs) ----
    for ch in data.get("chapters", []):
        for sec in ch.get("sections", []):
            # Problem and solution bodies are lifted out of `html` by the build,
            # so the rewrite below never sees them and a cross-reference written
            # inside an exercise printed its own label on the page. Resolve them
            # here — above the empty-html guard, because extracting the problems
            # can leave a section with buckets and almost no prose.
            #
            # Hashrefs only, deliberately: resolve_cite below also appends to
            # `cited`, which builds the per-section References list, and running
            # it here would credit a section with citations not in its prose.
            def _resolve_bucket_ref(mo):
                out = _render_refs(mo.group(2), targets,
                                   cap_class=mo.group(1) == "Hashref")
                return out if out is not None else mo.group(0)

            for bucket in ("problems", "solutions"):
                entries = sec.get(bucket)
                if not isinstance(entries, dict):
                    continue
                for entry in entries.values():
                    if isinstance(entry, dict) and entry.get("content"):
                        entry["content"] = _HASHREF_RE.sub(
                            _resolve_bucket_ref, entry["content"])

            html = sec.get("html") or ""
            if not html:
                continue
            html = _clean_rawtex(html, targets)
            html = _clean_tables(html)
            html = _fix_dollar_math(html)
            # after _fix_dollar_math, so $x$. gets bound too
            html = _bind_math_punctuation(html)
            html = _style_menus(html)
            hn = heading_numbers.get((ch["slug"], sec["slug"]), {})
            labels = {"lab": sec["number"] if _section_kind(sec) == "lab" else None}

            def num_heading(mo):
                full, attrs = mo.group(0), mo.group("attrs")
                hid = _ATTR_ID_RE.search(attrs)
                h = _ATTR_HASH_RE.search(attrs)
                if not hid and not h:
                    return full  # an environment box's title band
                if mo.group("level") == "1" and labels["lab"]:
                    return full + f'<span class="secnum">{labels["lab"]}:</span> '
                num = (h and hn.get(h.group(1))) or (hid and hn.get(hid.group(1)))
                if num:
                    return full + f'<span class="secnum">{num}</span> '
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

            # example environments (::: {.example …}): the box itself is CSS
            # (corner brackets + a faint divider before .example-solution);
            # here we add the visible number, mirroring the print book's box
            # title.
            for eid, enum in example_caps.get(sec["slug"], {}).items():
                html = _label_example_box(html, eid, f"Example {enum}")

            # exercises/lab problems: rewrite the filter's Tailwind box into the
            # web's run-in "Problem N.n" heading (see _rewrite_exercise_box).
            for eid, (label, is_lab) in problem_caps.get(sec["slug"], {}).items():
                html = _rewrite_exercise_box(html, eid, label, is_lab)

            # every other boxed environment (definition/theorem/comment/infobox
            # and any later addition): a semantic header content.css can draw.
            # Runs unconditionally — an untitled, unnumbered infobox still needs
            # its empty Tailwind header band removed.
            html = _rewrite_env_boxes(html, env_caps.get(sec["slug"], {}))

            # subequations groups: \tag every row "N a", "N b", … then stash the
            # whole <div> behind a placeholder so the single/multi-label tagger
            # below can't touch its math (its rows are already numbered).
            subeq_stash = []
            sq_nums = subeq_caps.get(sec["slug"], {})
            if sq_nums:
                def _stash_subeq(mo):
                    block = mo.group(0)
                    idm = _SUBEQ_ID_RE.search(block)
                    pid = (idm.group(1) or idm.group(2)) if idm else None
                    if pid in sq_nums:
                        block = _number_subeq_div(block, sq_nums[pid])
                    subeq_stash.append(block)
                    return f"\x00SUBEQ{len(subeq_stash) - 1}\x00"
                html = _SUBEQ_RE.sub(_stash_subeq, html)

            # numbered display equations: show the number as a MathJax \tag, which
            # right-aligns it (vertically centred, and one PER row in an aligned
            # block) exactly like the printed book. Two carriers reach us from the
            # build (see artifact.py):
            #   • single equation — <span class="math display">\[ … \]</span> then a
            #     trailing <span id="eq:ID"></span>: drop one \tag before the \].
            #   • multi-label aligned block — the raw \label{eq:ID}s are kept inside
            #     the math (one per numbered row, plus a trailing anchor each): swap
            #     each \label for the matching \tag so every row gets its number.
            # Trailing anchors stay put as scroll / cross-ref targets. \label is a
            # no-op macro in the MathJax config, so an unmatched one never chokes.
            eq_nums = eq_caps.get(sec["slug"], {})
            if eq_nums:
                def _tag_math(mo):
                    body, anchors = mo.group(1), mo.group(2)
                    if r"\label{eq:" in body:
                        body = re.sub(
                            r'\\label\{(eq:[^}]+)\}',
                            lambda m: (r"\tag{" + eq_nums[m.group(1)] + "}"
                                       if m.group(1) in eq_nums else ""),
                            body)
                    else:
                        ids = re.findall(r'<span id="(eq:[^"]+)"></span>', anchors)
                        if len(ids) == 1 and ids[0] in eq_nums:
                            close = body.rfind(r"\]")
                            if close != -1:
                                body = (body[:close] + r"\tag{" + eq_nums[ids[0]]
                                        + "}" + body[close:])
                    return '<span class="math display">' + body + "</span>" + anchors
                html = re.sub(
                    r'<span class="math display">((?:(?!</span>).)*)</span>'
                    r'((?:\s*<span id="eq:[^"]+"></span>)*)',
                    _tag_math, html, flags=re.S)

            if subeq_stash:  # restore the numbered subequations <div>s
                html = re.sub(r'\x00SUBEQ(\d+)\x00',
                              lambda m: subeq_stash[int(m.group(1))], html)

            # every \tag we injected (and any the author wrote, e.g. \tag{KVL})
            # must sit in a tag-permitting environment: promote inner
            # aligned/gathered blocks. Runs for every section — author tags need
            # this even where no equation is numbered — and only rewrites math
            # spans whose block actually carries a \tag.
            html = re.sub(
                r'(<span class="math display">)((?:(?!</span>).)*)(</span>)',
                lambda m: m.group(1) + _promote_tagged_aligned(m.group(2))
                + m.group(3), html, flags=re.S)

            # the build emits an equation's scroll/cross-ref anchor as a trailing
            # <span id="eq:..."></span> AFTER the math, so jumping to it lands just
            # PAST the equation (it ends up above the viewport). Move each anchor to
            # immediately BEFORE its equation and tag it .eqanchor, so a cross-ref
            # scrolls TO the equation (with scroll-margin breathing room + a :target
            # highlight; see base.html). Multi-row blocks keep one anchor per row,
            # all relocated ahead of the block.
            html = _ANCHOR_AFTER_MATH_RE.sub(_relocate_eq_anchors, html)

            def resolve(mo):
                cap = mo.group(1) == "Hashref"  # .Hashref capitalizes
                out = _render_refs(mo.group(2), targets, cap_class=cap)
                # leave unresolved refs (missing targets) as-is
                return out if out is not None else mo.group(0)
            html = _HASHREF_RE.sub(resolve, html)

            cited = []  # bib keys cited in this section, in order

            def resolve_cite(mo):
                keys = mo.group(1).split()
                # a citation made entirely of cross-ref keys ([@eq:a;@eq:b;@eq:c])
                # renders grouped + sort&compressed, exactly like \cref{a,b,c}
                # ("equations (9.7) to (9.9)") rather than a repeated-word list.
                if keys and all(_lookup_target(k, targets) for k in keys):
                    grouped = _render_refs(",".join(keys), targets)
                    if grouped is not None:
                        return grouped
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

            # .plaincite entry → its linked "Author (Year)" label (registered for
            # the References list, like a normal citation) plus any note(s). Unknown
            # keys fall back to the bare key so nothing silently vanishes.
            def resolve_plaincite(mo):
                k = mo.group(2).strip()
                notes = [_dashes(n) for n in _PLAINCITE_NOTE_RE.findall(mo.group(1))
                         if n.strip()]
                if k in references:
                    if k not in cited:
                        cited.append(k)
                    out = (f'<a class="cite" href="#ref-{k}">'
                           f'{_esc(references[k]["label"])}</a>')
                else:
                    out = _esc(k)
                return out + ("".join(f', {n}' for n in notes))
            # lay each further-reading box out as a titled bulleted list, one item
            # per source (the source is a comma-run; print's freadinglist env adds
            # the title and biblatex the bullets).
            def render_freading(mo):
                items = "".join(f'<li>{resolve_plaincite(m)}</li>'
                                for m in _PLAINCITE_RE.finditer(mo.group(0)))
                body = f'<ul>{items}</ul>' if items else ''
                return (mo.group(1)
                        + '<div class="freading-label">Further Reading</div>'
                        + body + '</div>')
            html = _FREADING_BOX_RE.sub(render_freading, html)
            # any stray .plaincite outside a box still resolves (inline).
            html = _PLAINCITE_RE.sub(resolve_plaincite, html)

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
