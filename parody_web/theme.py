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


def validate_theme(theme):
    """Raise ImproperlyConfigured unless `theme` is a well-formed override dict."""
    if not theme:
        return
    if not isinstance(theme, dict):
        raise ImproperlyConfigured("PARODY_WEB_THEME must be a dict")
    for mode, tokens in theme.items():
        if mode not in _MODES:
            raise ImproperlyConfigured(
                f"PARODY_WEB_THEME: unknown mode {mode!r} (expected light/dark)")
        if not isinstance(tokens, dict):
            raise ImproperlyConfigured(f"PARODY_WEB_THEME[{mode!r}] must be a dict")
        for token, value in tokens.items():
            if token not in ALLOWED_THEME_TOKENS:
                raise ImproperlyConfigured(
                    f"PARODY_WEB_THEME: {token!r} is not an overridable token "
                    f"(allowed: {', '.join(sorted(ALLOWED_THEME_TOKENS))})")
            _check_value(token, value)


def theme_css(theme):
    """CSS overriding the default tokens, or "" when nothing is configured."""
    validate_theme(theme)
    if not theme:
        return ""
    out = []
    for mode, selector in _MODES.items():
        tokens = theme.get(mode) or {}
        if tokens:
            decls = "".join(f"--{k}:{v};" for k, v in sorted(tokens.items()))
            out.append(f"{selector}{{{decls}}}")
    return "".join(out)
