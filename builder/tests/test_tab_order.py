"""Menu order (Mark 2026-10-26): drag, long press on a phone, Alt+arrow, saved per browser, quiet reset.

Runs the page's own reorder code in node with a tiny DOM, so the checks are about behaviour.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import unittest

PAGE = Path(__file__).resolve().parents[1] / "mac-mini-dashboard" / "index.html"
START = "// Mark 2026-10-26: menu items can be dragged into any order"
END = "applyTabOrder(readTabOrder());\n"

HARNESS = r"""
const ROUTES = ['work', 'growth', 'agents', 'platforms', 'documents', 'context', 'machines'];
const TAB_NAME_ROUTES = Object.freeze(ROUTES.slice());
const SLOT = 46;
const store = new Map(Object.entries(SAVED));
const localStorage = {getItem: k => store.has(k) ? store.get(k) : null, setItem: (k, v) => store.set(k, String(v)), removeItem: k => store.delete(k)};
const listeners = {};
function setTabNameStatus() {}
function pill(route) {
  const label = {dataset: {tabLabel: route}, textContent: route};
  return {route, label, classList: {add() {}, remove() {}}, style: {}, parentElement: null, offsetLeft: 0, offsetWidth: 220, offsetHeight: 40,
    get offsetTop() { return nav.items.indexOf(this) * SLOT; },
    querySelector: () => label, closest(sel) { return sel === '.nav-pill' ? this : null; },
    get nextElementSibling() { return nav.items[nav.items.indexOf(this) + 1] || null; },
    before(...items) { items.forEach(i => nav.remove(i)); nav.items.splice(nav.items.indexOf(this), 0, ...items); },
    after(...items) { items.forEach(i => nav.remove(i)); nav.items.splice(nav.items.indexOf(this) + 1, 0, ...items); },
    setPointerCapture() {}, focus() {}, getBoundingClientRect() { return {}; }, addEventListener() {}};
}
const nav = {items: [], classList: {add() {}, remove() {}},
  remove(item) { const i = this.items.indexOf(item); if (i >= 0) this.items.splice(i, 1); item.parentElement = this; },
  append(item) { this.remove(item); this.items.push(item); },
  querySelectorAll: () => nav.items.slice(),
  addEventListener(type, fn) { listeners[type] = listeners[type] || []; listeners[type].push(fn); }};
ROUTES.forEach(r => nav.append(pill(r)));
const resetButton = {hidden: true, addEventListener(type, fn) { this.click = fn; }};
const orderStatus = {textContent: ''};
const document = {querySelector: () => nav, getElementById: id => id === 'reset-tab-order' ? resetButton : orderStatus};
const window = {matchMedia: () => ({matches: true})};
const navigator = {};
function getComputedStyle() { return {flexDirection: 'column'}; }
const timers = [];
function setTimeout(fn) { timers.push(fn); return timers.length; }
function clearTimeout(id) { if (id) timers[id - 1] = null; }
function runTimers() { while (timers.length) { const fn = timers.shift(); if (fn) fn(); } }
function fire(type, props) {
  const event = {preventDefault() { this.prevented = true; }, stopPropagation() { this.stopped = true; }, ...props};
  (listeners[type] || []).forEach(fn => fn(event));
  return event;
}
const order = () => nav.items.map(i => i.route).join(',');
const find = r => nav.items.find(i => i.route === r);
CODE
const out = {loaded: order(), resetHidden: resetButton.hidden};
// Mouse: press on Техника, drag it up two places, let go.
let t = find('machines');
// A press let go outside the menu before the drag began must not turn into a drag on the way back.
fire('pointerdown', {target: t, pointerType: 'mouse', button: 0, pointerId: 1, clientX: 50, clientY: 300});
fire('pointermove', {target: t, pointerId: 1, buttons: 0, clientX: 50, clientY: 300 - 2 * SLOT});
out.releasedOutside = order();
fire('pointerdown', {target: t, pointerType: 'mouse', button: 0, pointerId: 1, clientX: 50, clientY: 300});
fire('pointermove', {target: t, pointerId: 1, buttons: 1, clientX: 50, clientY: 300 - 2 * SLOT});
fire('pointerup', {target: t, pointerId: 1});
const swallowed = fire('click', {target: t});
out.mouse = order();
out.saved = store.get('command-center.tab-order.v1') || null;
out.clickAfterDragSwallowed = Boolean(swallowed.stopped);
out.status = orderStatus.textContent;
// Touch: a finger that moves before the long press is a scroll, nothing moves.
t = find('growth');
fire('pointerdown', {target: t, pointerType: 'touch', pointerId: 2, clientX: 50, clientY: 50});
fire('pointermove', {target: t, pointerId: 2, buttons: 1, clientX: 50, clientY: 50 + 3 * SLOT});
fire('pointerup', {target: t, pointerId: 2});
runTimers();
out.swipe = order();
// Touch: hold, then drag down three places.
fire('pointerdown', {target: t, pointerType: 'touch', pointerId: 3, clientX: 50, clientY: 50});
timers.shift()();
const held = fire('touchmove', {});
fire('pointermove', {target: t, pointerId: 3, buttons: 1, clientX: 50, clientY: 50 + 3 * SLOT + 10});
fire('pointerup', {target: t, pointerId: 3});
out.longPress = order();
out.scrollBlocked = Boolean(held.prevented);
// Keyboard: Alt+ArrowUp on Агенты.
const key = fire('keydown', {target: find('agents'), altKey: true, key: 'ArrowUp'});
out.keyboard = order();
out.keyHandled = Boolean(key.prevented);
out.resetShown = !resetButton.hidden;
resetButton.click();
out.reset = order();
out.savedAfterReset = store.get('command-center.tab-order.v1') || null;
out.resetHiddenAgain = resetButton.hidden;
process.stdout.write(JSON.stringify(out));
"""


def run(saved: dict[str, str]) -> dict:
    page = PAGE.read_text(encoding="utf-8")
    start = page.index(START)
    end = page.index(END, start) + len(END)
    harness = HARNESS.replace("SAVED", json.dumps(saved)).replace("CODE", page[start:end])
    result = subprocess.run(["node", "-e", harness], capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise AssertionError(result.stderr[-2000:])
    return json.loads(result.stdout)


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class TabOrderTest(unittest.TestCase):
    def test_drag_long_press_keyboard_and_reset(self):
        data = run({})
        self.assertEqual(data["loaded"], "work,growth,agents,platforms,documents,context,machines")
        self.assertTrue(data["resetHidden"])
        self.assertEqual(data["releasedOutside"], data["loaded"])
        self.assertEqual(data["mouse"], "work,growth,agents,platforms,machines,documents,context")
        self.assertEqual(json.loads(data["saved"]), data["mouse"].split(","))
        self.assertTrue(data["clickAfterDragSwallowed"], "dropping an item must not open its tab")
        self.assertEqual(data["status"], "machines: место 5 из 7")
        self.assertEqual(data["swipe"], data["mouse"], "a quick swipe on a phone must not move anything")
        self.assertEqual(data["longPress"], "work,agents,platforms,machines,growth,documents,context")
        self.assertTrue(data["scrollBlocked"])
        self.assertEqual(data["keyboard"], "agents,work,platforms,machines,growth,documents,context")
        self.assertTrue(data["keyHandled"])
        self.assertTrue(data["resetShown"])
        self.assertEqual(data["reset"], "work,growth,agents,platforms,documents,context,machines")
        self.assertIsNone(data["savedAfterReset"])
        self.assertTrue(data["resetHiddenAgain"])

    def test_saved_order_is_cleaned(self):
        saved = {"command-center.tab-order.v1": json.dumps(["machines", "bogus", "work", "machines", 3])}
        self.assertEqual(run(saved)["loaded"], "machines,work,growth,agents,platforms,documents,context")
        self.assertEqual(run({"command-center.tab-order.v1": "{not json"})["loaded"],
                         "work,growth,agents,platforms,documents,context,machines")


if __name__ == "__main__":
    unittest.main()
