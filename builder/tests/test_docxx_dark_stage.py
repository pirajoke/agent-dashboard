"""Check the real stage palette, including translucent labels over gradient stops."""
from pathlib import Path
import re
import unittest

HTML = Path(__file__).resolve().parents[1] / 'mac-mini-dashboard/index.html'


def declarations(css, selector):
    result = {}
    # Exact selectors only: mobile geometry rules may repeat these selectors.
    pattern = r'(?<![\w.:-])' + re.escape(selector) + r'\s*\{([^{}]*)\}'
    for body in re.findall(pattern, css):
        result.update((key.strip(), value.strip()) for key, value in
                      re.findall(r'([\w-]+)\s*:\s*([^;]+)', body))
    return result


def resolve(value, tokens):
    for _ in range(12):
        expanded = re.sub(r'var\((--[\w-]+)\)', lambda m: tokens[m[1]], value)
        if expanded == value:
            return value
        value = expanded
    raise AssertionError('CSS variable cycle')


def colors(value):
    result = []
    for match in re.finditer(r'#[\da-fA-F]{6}\b|rgba?\([^()]+\)', value):
        color = match[0]
        if color.startswith('#'):
            result.append(tuple(int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)) + (1,))
        else:
            parts = [float(x) for x in re.findall(r'[\d.]+', color)]
            result.append(tuple(x / 255 for x in parts[:3]) + (parts[3] if len(parts) > 3 else 1,))
    if not result:
        raise AssertionError('No supported color in ' + value)
    return result


def over(foreground, background):
    return tuple(foreground[i] * foreground[3] + background[i] * (1 - foreground[3])
                 for i in range(3)) + (1,)


def luminance(color):
    linear = [x / 12.92 if x <= .04045 else ((x + .055) / 1.055) ** 2.4 for x in color[:3]]
    return sum(x * weight for x, weight in zip(linear, (.2126, .7152, .0722)))


def contrast(a, b):
    light, dark = sorted((luminance(a), luminance(b)), reverse=True)
    return (light + .05) / (dark + .05)


class DocxxDarkStageTests(unittest.TestCase):
    def palette(self, theme):
        css = HTML.read_text().split('<style>', 1)[1].split('</style>', 1)[0]
        tokens = declarations(css, ':root')
        if theme == 'dark':
            tokens.update(declarations(css, ':root[data-theme="dark"]'))
        return css, tokens

    def test_stage_background_matches_selected_theme(self):
        for theme in ('light', 'dark'):
            css, tokens = self.palette(theme)
            stops = colors(resolve(declarations(css, '.docxx-stage')['background'], tokens))
            for index, color in enumerate(stops):
                with self.subTest(theme=theme, stop=index):
                    if theme == 'dark':
                        self.assertLess(luminance(color), .1, 'Dark mode must not show a bright cream canvas')
                    else:
                        self.assertGreater(luminance(color), .7, 'Light mode must keep its light canvas')

    def test_label_title_and_subtitle_are_readable_in_both_themes(self):
        for theme in ('light', 'dark'):
            css, tokens = self.palette(theme)
            stage = colors(resolve(declarations(css, '.docxx-stage')['background'], tokens))
            label = declarations(css, '.docxx-stage-label')
            background = colors(resolve(label['background'], tokens))[0]
            for selector in ('.docxx-stage-label', '.docxx-stage-label small'):
                ink = colors(resolve(declarations(css, selector)['color'], tokens))[0]
                for index, stop in enumerate(stage):
                    ratio = contrast(ink, over(background, stop))
                    with self.subTest(theme=theme, selector=selector, stop=index):
                        self.assertGreaterEqual(ratio, 4.5, 'Small stage text must meet 4.5:1 contrast')
