"""Saying cross-references the way they are printed.

A raw artifact carries references unresolved — `[@eq:v_plus_minus]` in a
citation span, or a bare `.hashref` span — because numbering runs at import,
not at build. Read aloud as-is, the reader hears the LABEL: "such that eq is
approximately true".

The obvious fix, running `parody_web.numbering.number_artifact` and reading its
output, was tried twice and corrupted the section in production both times
(see the `readalong-numbering-corrupts-only-in-production` note). So this takes
the one thing from that pass that is safe to take — the map of keys to printed
labels — and rewrites nothing else. The html read aloud stays the html that was
built.
"""

import copy
import re

# `<span class="citation" data-cites="eq:foo">[@eq:foo]</span>`
_CITATION = re.compile(
    r'<span[^>]*class="[^"]*\bcitation\b[^"]*"[^>]*'
    r'data-cites="([^"]+)"[^>]*>.*?</span>',
    re.DOTALL)
# `<span class="hashref">eq:foo</span>`
_HASHREF = re.compile(
    r'<span[^>]*class="[^"]*\bhashref\b[^"]*"[^>]*>(.*?)</span>',
    re.DOTALL)
_TAGS = re.compile(r"<[^>]+>")


def label_map(data):
    """key -> printed label ("Equation (4.1)"), from a THROWAWAY numbered copy.

    The copy is the whole point: `number_artifact` mutates in place and its
    rewritten html is what has twice corrupted production. Only the returned
    target map is used, and the caller's data is never touched.
    """
    targets = _number(copy.deepcopy(data))
    return {key: (value or {}).get("label") or ""
            for key, value in (targets or {}).items()}


def _number(data):
    from parody_web.numbering import number_artifact

    return number_artifact(data)


def _speak(keys, labels):
    """"Equation (4.1) and Figure 4.12a" for however many keys were cited."""
    said = []
    for key in re.split(r"[;,\s]+", keys.strip()):
        key = key.lstrip("@").strip()
        if not key:
            continue
        label = labels.get(key)
        if not label:
            return None                # unknown: leave the text as authored
        said.append(label)
    if not said:
        return None
    if len(said) == 1:
        return said[0]
    return ", ".join(said[:-1]) + " and " + said[-1]


def resolve_refs(html, labels):
    """Replace reference spans with the text a reader would see.

    Text only — no links, no anchors, no numbering of anything else. An
    unresolvable key keeps whatever was authored, so a missing target costs
    that one reference and nothing around it.
    """
    if not html or not labels:
        return html

    def citation(match):
        said = _speak(match.group(1), labels)
        return said if said else match.group(0)

    def hashref(match):
        said = _speak(_TAGS.sub("", match.group(1)), labels)
        return said if said else match.group(0)

    return _HASHREF.sub(hashref, _CITATION.sub(citation, html))
