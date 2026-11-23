"""The books' maths vocabulary: every custom macro MathJax has to know.

ONE list with two readers, which is the reason it is Python and not a literal
in a template:

- the page: `base.html` writes it into `window.MathJax.tex.macros` through
  the `{% mathjax_macros %}` tag, so the book's maths typesets on the web;
- read-along: `parody_web_readaloud.speech.SreMath` hands it to the Node
  helper, whose MathJax turns each expression into the MathML SRE speaks, and
  into the SVG a blank reveals.

They were two lists once, in effect: the page had this set and read-along had
none, so every \\bm in a voiced section was read aloud as "backslash B M" —
while the same equation on the page looked perfect. An undefined macro is not
an error in either place: MathJax typesets (or speaks) the macro's own name
and carries on, so the only thing that keeps the two in step is that there is
one list.

Values are MathJax's own macro format: a string for a macro without
arguments, `[body, n]` for one taking `n`. Each body is braced so it groups
the way a LaTeX \\newcommand does. Print has its own seam (a book's
`print.preamble`), so a macro used on both sides still has to be declared on
both.
"""

import json

MACROS = {
    # numbering injects \tag{C.n} for equation numbers; \label is mapped to a
    # no-op so any raw \label left in a multi-label aligned block (kept by the
    # build so each row can be \tag-ged) never breaks typesetting.
    "label": ["", 1],
    "bm": ["{\\boldsymbol{#1}}", 1],
    "mat": ["{\\boldsymbol{#1}}", 1],
    "vec": ["{\\boldsymbol{#1}}", 1],
    "bnot": ["{\\overline{#1}}", 1],
    # Paired delimiters. An undefined macro is NOT a red error in this
    # configuration — MathJax typesets the macro NAME into the sentence, so
    # System Dynamics read "the magnitude \abs H(j\omega)" on the live site
    # and nothing anywhere said so. The math notes use \norm the same way.
    "abs": ["{\\left\\lvert #1 \\right\\rvert}", 1],
    "norm": ["{\\left\\lVert #1 \\right\\rVert}", 1],
    # Probability and statistics operators, one mandatory argument, bracketed:
    # \E{X} sets E[X]. The book's LaTeX declares them with xparse so a starred
    # form drops the brackets; nothing in any book uses the star, so these
    # take the plain form. Silent-failure class again — Probability read
    # "EX" and "VarX" on the page.
    "E": ["{\\operatorname{E}\\left[#1\\right]}", 1],
    "Var": ["{\\operatorname{Var}\\left[#1\\right]}", 1],
    "Cov": ["{\\operatorname{Cov}\\left[#1\\right]}", 1],
    "Cor": ["{\\operatorname{Cor}\\left[#1\\right]}", 1],
    "Skew": ["{\\operatorname{Skew}\\left[#1\\right]}", 1],
    "Kurt": ["{\\operatorname{Kurt}\\left[#1\\right]}", 1],
    "bigcdot": "{\\cdot}",
    "band": ["{#1\\cdot #2}", 2],
    "bor": ["{#1+#2}", 2],
    "bnand": ["{#1\\mathbin{\\mathrm{nand}}#2}", 2],
    "bnor": ["{#1\\mathbin{\\mathrm{nor}}#2}", 2],
    "bxor": ["{#1\\mathbin{\\mathrm{xor}}#2}", 2],
    "bxnor": ["{#1\\mathbin{\\mathrm{xnor}}#2}", 2],
    "sgn": "{\\operatorname{sgn}}",
    "atantwo": "{\\operatorname{atan}_2}",
    "arctantwo": "{\\operatorname{arctan}_2}",
    "arctanh": "{\\operatorname{arctanh}}",
    "adj": "{\\operatorname{adj}}",
    "Div": "{\\operatorname{div}}",
    "curl": "{\\operatorname{curl}}",
    "grad": "{\\operatorname{grad}}",
    "diff": "{d}",
    "Diff": ["{d^{#1}}", 1],
    "argmax": "{\\operatorname*{argmax}}",
    "argmin": "{\\operatorname*{argmin}}",
    "parallelsum": "{\\mathbin{\\|}}",
}


def macros_js():
    """`MACROS` as a JavaScript object literal, safe inside a <script>.

    JSON is valid JavaScript. `<`, `>` and `&` are escaped the way Django's
    json_script escapes them, so no body can ever close the script element it
    sits in; inside a JS string the escapes read back as the same characters.
    """
    text = json.dumps(MACROS, ensure_ascii=False)
    return (text.replace("<", "\\u003C").replace(">", "\\u003E")
            .replace("&", "\\u0026"))
