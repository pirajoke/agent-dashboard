"""The page background follows the light/dark switch on every screen width.

CI has no browser, so this resolves the stylesheet cascade the way the browser does for the
one property that matters here: which `body` background wins at a given width and theme, and
what colour its custom properties resolve to. It reads the rules, not their formatting.
"""
from __future__ import annotations

from pathlib import Path
import re
import unittest


PAGE = Path(__file__).resolve().parents[1] / "mac-mini-dashboard" / "index.html"
PHONE, DESKTOP = 390, 1440
# (data-theme on <html>, system prefers dark): the saved choice wins over the system theme.
THEMES = {
    "light": ("light", True),
    "dark": ("dark", False),
    "system dark": (None, True),
    "system light": (None, False),
}


def _style_rules(css: str, media: tuple[str, ...] = ()):
    """Yield (media conditions, selector, declarations) in source order."""
    pos = 0
    while True:
        open_at = css.find("{", pos)
        if open_at < 0:
            return
        prelude = css[pos:open_at].strip()
        depth, end = 1, open_at + 1
        while depth:
            depth += {"{": 1, "}": -1}.get(css[end], 0)
            end += 1
        body = css[open_at + 1:end - 1]
        if prelude.startswith("@media"):
            yield from _style_rules(body, media + (prelude[len("@media"):].strip(),))
        elif not prelude.startswith("@"):
            yield media, prelude, body
        pos = end


def _media_matches(query: str, width: int, prefers_dark: bool) -> bool:
    def feature(part: str) -> bool:
        part = part.strip().strip("()").strip()
        if part in ("screen", "all"):
            return True
        name, _, value = (piece.strip() for piece in part.partition(":"))
        if name == "max-width":
            return width <= int(value.removesuffix("px"))
        if name == "min-width":
            return width >= int(value.removesuffix("px"))
        if name == "prefers-color-scheme":
            return (value == "dark") == prefers_dark
        return False  # print, reduced motion, hover…: not the default phone/desktop view

    return any(all(feature(p) for p in alt.split(" and ")) for alt in query.split(","))


def _root_matches(selector: str, theme: str | None) -> int:
    """Specificity of a :root selector that applies to <html data-theme=theme>, else 0."""
    attr = re.fullmatch(r':root(?:\[data-theme="(\w+)"\]|:not\(\[data-theme="(\w+)"\]\))?', selector)
    if not attr:
        return 0
    is_value, not_value = attr.groups()
    if is_value is not None and is_value != theme:
        return 0
    if not_value is not None and not_value == theme:
        return 0
    return 2 if (is_value or not_value) else 1


def _declarations(body: str) -> list[tuple[str, str]]:
    pairs = []
    for line in body.split(";"):
        name, sep, value = line.partition(":")
        if sep:
            pairs.append((name.strip(), value.replace("!important", "").strip()))
    return pairs


def computed_background(html: str, width: int, theme: str | None, prefers_dark: bool) -> tuple[str, str]:
    """The colour the body background resolves to, and the theme's --mm-background."""
    css = re.sub(r"/\*.*?\*/", "", html.split("<style>", 1)[1].split("</style>", 1)[0], flags=re.S)
    variables: dict[str, tuple[int, int, str]] = {}
    background = None
    for order, (media, selector, body) in enumerate(_style_rules(css)):
        if not all(_media_matches(query, width, prefers_dark) for query in media):
            continue
        selectors = [s.strip() for s in selector.split(",")]
        for name, value in _declarations(body):
            if name.startswith("--"):
                specificity = max(_root_matches(s, theme) for s in selectors)
                if specificity and (specificity, order) >= variables.get(name, (0, -1, ""))[:2]:
                    variables[name] = (specificity, order, value)
            elif "body" in selectors and name in ("background", "background-color"):
                background = value
    assert background is not None, "no body background rule applies"

    def resolve(value: str) -> str:
        for _ in range(10):
            resolved = re.sub(r"var\((--[\w-]+)\)", lambda m: variables[m.group(1)][2], value)
            if resolved == value:
                return resolved.lower()
            value = resolved
        raise AssertionError("custom properties do not resolve")

    return resolve(background), resolve("var(--mm-background)")


class PageThemeTest(unittest.TestCase):
    html = PAGE.read_text(encoding="utf-8")

    def test_page_background_follows_the_theme_on_phone_and_desktop(self):
        # Mark 2026-10-14: one light/dark switch for the whole page. On a phone the page background
        # shows behind every tab, so it has to follow the switch there too (it stayed light, #82).
        for width in (PHONE, DESKTOP):
            seen = {}
            for label, (theme, prefers_dark) in THEMES.items():
                with self.subTest(width=width, theme=label):
                    background, theme_background = computed_background(self.html, width, theme, prefers_dark)
                    self.assertEqual(background, theme_background)
                    seen[label] = background
            self.assertEqual(seen["light"], seen["system light"])
            self.assertEqual(seen["dark"], seen["system dark"])
            self.assertNotEqual(seen["light"], seen["dark"], f"width {width}px")

    def test_saved_light_choice_beats_a_dark_system(self):
        light, _ = computed_background(self.html, PHONE, "light", True)
        self.assertEqual(light, computed_background(self.html, PHONE, None, False)[0])


if __name__ == "__main__":
    unittest.main()
