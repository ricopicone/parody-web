"""Per-book theme overrides.

parody-web ships one opinionated default look; a deployment retints it for its
own book through a settings dict rather than by forking a stylesheet:

    PARODY_WEB_THEME = {"light": {"accent": "#b3261e"},
                        "dark":  {"accent": "#ff8a80"}}

Each key names a design token from tokens.css (without the leading ``--``) and
is rendered into a ``:root`` block. Only whitelisted token names are accepted,
and only colour- or font-stack-shaped values: a settings dict must never become
a route for arbitrary CSS. Validation runs at startup (see apps.py) so a
malformed theme fails loudly on boot rather than silently at first render.

A deployment serving several books (see books.py) keys the same dict by book
slug instead, so the shelf isn't all one colour:

    PARODY_WEB_THEME = {"electronics":  {"light": {"accent": "#b3261e"}},
                        "mechatronics": {"light": {"accent": "#1e5fb3"}}}

``light`` and ``dark`` are the only legal mode names, so a top-level key that is
neither means the dict is keyed by slug. The two forms cannot be mixed.
"""
import re

from django.core.exceptions import ImproperlyConfigured

#: Tokens a deployment may override. Deliberately a small surface — the layout
#: and type *scale* are the design; only its colouring and faces are themeable.
ALLOWED_THEME_TOKENS = frozenset({
    "accent", "accent-ink", "accent-soft", "accent-wash",
    "paper", "paper-sunk", "ink", "ink-muted",
    "font-display", "font-body",
})

_HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
# a font stack: quoted family names and/or bare generics, comma separated
_FONT = re.compile(r'^(?:"[\w \-]+"|[a-z\-]+)(?:\s*,\s*(?:"[\w \-]+"|[a-z\-]+))*$')

_MODES = {"light": ":root", "dark": ':root[data-theme="dark"]'}


def _check_value(token, value):
    if not isinstance(value, str):
        raise ImproperlyConfigured(
            f"PARODY_WEB_THEME: {token!r} must be a string, "
            f"got {type(value).__name__}")
    ok = _FONT.match(value) if token.startswith("font-") else _HEX.match(value)
    if not ok:
        raise ImproperlyConfigured(
            f"PARODY_WEB_THEME: {value!r} is not a valid value for {token!r} "
            f"(expected {'a font stack' if token.startswith('font-') else 'a hex colour'})")


def is_keyed(theme):
    """Whether `theme` is keyed by book slug rather than by light/dark mode."""
    return (bool(theme) and isinstance(theme, dict)
            and not (set(theme) & set(_MODES)))


def _validate_modes(theme, where):
    """Validate one book's worth of overrides: light/dark → tokens."""
    for mode, tokens in theme.items():
        if mode not in _MODES:
            raise ImproperlyConfigured(
                f"PARODY_WEB_THEME{where}: unknown mode {mode!r} "
                f"(expected light/dark)")
        if not isinstance(tokens, dict):
            raise ImproperlyConfigured(
                f"PARODY_WEB_THEME{where}[{mode!r}] must be a dict")
        for token, value in tokens.items():
            if token not in ALLOWED_THEME_TOKENS:
                raise ImproperlyConfigured(
                    f"PARODY_WEB_THEME: {token!r} is not an overridable token "
                    f"(allowed: {', '.join(sorted(ALLOWED_THEME_TOKENS))})")
            _check_value(token, value)


def validate_theme(theme):
    """Raise ImproperlyConfigured unless `theme` is a well-formed override dict,
    in either the single-book or the slug-keyed form."""
    if not theme:
        return
    if not isinstance(theme, dict):
        raise ImproperlyConfigured("PARODY_WEB_THEME must be a dict")
    if not is_keyed(theme):
        # A mode key is present, so this is the single-book form — and then
        # every key has to be a mode: a stray slug alongside them is the mixed
        # form, which has no sensible reading.
        _validate_modes(theme, "")
        return
    for slug, book_theme in theme.items():
        if not isinstance(book_theme, dict):
            raise ImproperlyConfigured(
                f"PARODY_WEB_THEME[{slug!r}] must be a dict")
        if is_keyed(book_theme):
            raise ImproperlyConfigured(
                f"PARODY_WEB_THEME[{slug!r}] has no light/dark modes — the "
                f"per-book and single-book forms cannot be mixed")
        _validate_modes(book_theme, f"[{slug!r}]")


def theme_for(theme, slug):
    """One book's overrides: `theme` itself in the single-book form, else the
    entry for `slug` (empty when the setting names no theme for it)."""
    if not theme:
        return {}
    if not is_keyed(theme):
        return theme
    return theme.get(slug) or {}


def theme_css(theme, slug=None):
    """CSS overriding the default tokens, or "" when nothing is configured."""
    validate_theme(theme)
    theme = theme_for(theme, slug)
    if not theme:
        return ""
    out = []
    for mode, selector in _MODES.items():
        tokens = theme.get(mode) or {}
        if tokens:
            decls = "".join(f"--{k}:{v};" for k, v in sorted(tokens.items()))
            out.append(f"{selector}{{{decls}}}")
    return "".join(out)
