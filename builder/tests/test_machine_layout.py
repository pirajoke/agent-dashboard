"""Order and archive of the computers on «Техника» (Mark 2026-11-03: «сделай drag drop и archive desarchive»)."""
from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from dashboard_builder.machine_layout import load_layout, save_layout, validate_layout

BUILDER = Path(__file__).resolve().parents[1]
PAGE = BUILDER / "mac-mini-dashboard" / "index.html"
spec = importlib.util.spec_from_file_location("dashboard_machine_layout_test", BUILDER / "dashboard-server-m4.py")
SERVER = importlib.util.module_from_spec(spec)
spec.loader.exec_module(SERVER)


class MachineLayoutStoreTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "nested" / "machine-layout.json"

    def test_round_trip_and_private_file(self):
        record = save_layout(self.path, {"order": ["pro", "mac-mini", "air"], "archived": ["air"]})
        self.assertEqual(record["order"], ["pro", "mac-mini", "air"])
        self.assertEqual(load_layout(self.path)["archived"], ["air"])
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_missing_computers_keep_their_place_and_broken_store_means_shipped_order(self):
        self.assertEqual(validate_layout({"order": ["pro"]})["order"], ["pro", "mac-mini", "air"])
        self.assertEqual(load_layout(self.path)["order"], ["mac-mini", "air", "pro"])
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{oops")
        self.assertEqual(load_layout(self.path), {"order": ["mac-mini", "air", "pro"], "archived": [], "updated_at": None})

    def test_one_computer_always_stays_and_bad_input_is_refused(self):
        for bad in ([], {"order": "pro"}, {"order": ["imac"]}, {"order": ["pro", "pro"]},
                    {"archived": ["mac-mini", "air", "pro"]}, {"order": [], "extra": 1}, {"archived": [1]}):
            with self.subTest(bad=str(bad)), self.assertRaises(ValueError):
                validate_layout(bad)


class MachineLayoutEndpointTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "machine-layout.json"

    def call(self, method, body=None, *, token="fixture-owner", origin=None, content_type="application/json", raw=None):
        handler = SERVER.Handler.__new__(SERVER.Handler)
        handler.path, handler.command = "/api/machine-layout", method
        data = raw if raw is not None else json.dumps(body or {}).encode()
        handler.headers = {"Host": "localhost:9999", "Content-Length": str(len(data)), "Content-Type": content_type}
        if token is not None:
            handler.headers["X-Dashboard-Run-Token"] = token
        if origin is not None:
            handler.headers["Origin"] = origin
        handler.rfile = io.BytesIO(data)
        output = {}
        handler._json_response = lambda status, payload: output.update(status=status, payload=payload)
        with (patch.object(SERVER, "MACHINE_LAYOUT_FILE", self.path),
              patch.object(SERVER, "_dashboard_run_token", return_value="fixture-owner"),
              patch.object(SERVER.Handler, "_cloudflare_access_owner", return_value=False)):
            getattr(handler, f"do_{method}")()
        return output

    def test_owner_saves_and_every_device_reads_the_same(self):
        saved = self.call("POST", {"order": ["pro", "mac-mini", "air"], "archived": ["air"]}, origin="http://localhost:9999")
        self.assertEqual(saved["status"], 200)
        read = self.call("GET")
        self.assertEqual((read["status"], read["payload"]["order"], read["payload"]["archived"]),
                         (200, ["pro", "mac-mini", "air"], ["air"]))

    def test_anonymous_cross_origin_or_bad_body_cannot_write_or_read(self):
        body = {"order": ["pro"], "archived": []}
        for kwargs, status in (
            ({"token": None}, 401), ({"token": "wrong"}, 401), ({"origin": "https://foreign.invalid"}, 403),
            ({"content_type": "text/plain"}, 415), ({"raw": b"{oops"}, 400),
        ):
            with self.subTest(kwargs=str(kwargs)):
                self.assertEqual(self.call("POST", body, **kwargs)["status"], status)
                self.assertFalse(self.path.exists())
        self.assertEqual(self.call("POST", {"archived": ["mac-mini", "air", "pro"]})["status"], 400)
        self.assertEqual(self.call("GET", token=None)["status"], 401)


START = "// Mark 2026-11-03: «сделай drag drop и archive desarchive» on «Техника»."
END = "loadMachineLayout();\n"

HARNESS = r"""
const IDS = ['mac-mini', 'air', 'pro'];
const store = new Map();
const localStorage = {getItem: k => store.has(k) ? store.get(k) : null, setItem: (k, v) => store.set(k, String(v))};
const listeners = {};
const posts = [];
const IS_FILE_DASHBOARD = false, DASHBOARD_API = '';
function jarvisRunHeaders() { return {}; }
function fetch(url, init) { if (init && init.method === 'POST') posts.push(JSON.parse(init.body)); return Promise.resolve({ok: false}); }
let selectedMachine = 'air';
const shown = [];
function showSection(name) { shown.push(name); selectedMachine = name; }
const tabOrderReducedMotion = {matches: true};
const TAB_ORDER_LONG_PRESS_MS = 380, TAB_ORDER_MOVE_SLOP = 8;
const W = 100;
function el(extra) { return Object.assign({hidden: false, textContent: '', dataset: {}, style: {}, attrs: {},
  classList: {set: new Set(), add(...c) { c.forEach(x => this.set.add(x)); }, remove(...c) { c.forEach(x => this.set.delete(x)); },
    toggle(c, on) { on ? this.set.add(c) : this.set.delete(c); }, contains(c) { return this.set.has(c); }},
  setAttribute(k, v) { this.attrs[k] = v; }, addEventListener(type, fn) { (this.l = this.l || {})[type] = fn; },
  append() {}, replaceChildren(...items) { this.children = items; }}, extra); }
const nav = el({items: [],
  remove(item) { const i = this.items.indexOf(item); if (i >= 0) this.items.splice(i, 1); },
  append(...items) { items.forEach(i => { this.remove(i); this.items.push(i); }); },
  querySelectorAll: () => nav.items.slice(),
  querySelector(sel) { const id = /data-machine="([^"]+)"/.exec(sel)[1]; const b = nav.items.find(i => i.dataset.machine === id); return b && b.nameEl; },
  addEventListener(type, fn) { (listeners[type] = listeners[type] || []).push(fn); }});
function pill(id) {
  const b = el({dataset: {machine: id}, nameEl: {textContent: id}, offsetWidth: W,
    get offsetLeft() { return nav.items.filter(i => !i.hidden).indexOf(this) * W; },
    closest(sel) { return sel.startsWith('.nav-pill') ? this : null; },
    before(...items) { items.forEach(i => nav.remove(i)); nav.items.splice(nav.items.indexOf(this), 0, ...items); },
    after(...items) { items.forEach(i => nav.remove(i)); nav.items.splice(nav.items.indexOf(this) + 1, 0, ...items); },
    setPointerCapture() {}, focus() {}});
  return b;
}
IDS.forEach(id => nav.append(pill(id)));
const archiveButton = el({getBoundingClientRect: () => ({left: 400, right: 480, top: 0, bottom: 40})});
const machinesSection = el({}); machinesSection.classList.add('active');
const byId = {'machine-archive': el({}), 'machine-archive-open': archiveButton, 'machine-archive-count': el({}),
  'machine-archive-dialog': el({open: false, close() {}}), 'machine-archive-close': el({}), 'machine-order-status': el({}),
  'machine-archive-status': el({}), 'machine-archive-list': el({}), 'machine-active-list': el({}), 'section-machines': machinesSection};
const document = {querySelector: () => nav, getElementById: id => byId[id], createElement: () => el({})};
const navigator = {};
const timers = [];
function setTimeout(fn) { timers.push(fn); return timers.length; }
function clearTimeout(id) { if (id) timers[id - 1] = null; }
function runTimers() { while (timers.length) { const fn = timers.shift(); if (fn) fn(); } }
function fire(type, props) { const e = {preventDefault() {}, stopPropagation() {}, ...props}; (listeners[type] || []).forEach(fn => fn(e)); return e; }
const visible = () => nav.items.filter(i => !i.hidden).map(i => i.dataset.machine).join(',');
const find = id => nav.items.find(i => i.dataset.machine === id);
store.set('command-center.machine-layout.v1', JSON.stringify({order: ['pro', 'mac-mini', 'air'], archived: []}));
CODE
const out = {cached: visible()};
// Mouse: drag Mac mini (place 2) to the front.
fire('pointerdown', {target: find('mac-mini'), pointerType: 'mouse', button: 0, pointerId: 1, clientX: 150, clientY: 20});
fire('pointermove', {pointerId: 1, buttons: 1, clientX: 60, clientY: 20});
fire('pointermove', {pointerId: 1, buttons: 1, clientX: 20, clientY: 20});
fire('pointerup', {pointerId: 1});
out.dragged = visible();
// Phone: long press on the open MacBook Air, then drop it on «Архив».
fire('pointerdown', {target: find('air'), pointerType: 'touch', pointerId: 2, clientX: 250, clientY: 20});
runTimers();
fire('pointermove', {pointerId: 2, clientX: 440, clientY: 20});
out.dropTarget = archiveButton.classList.contains('is-drop-target');
fire('pointerup', {pointerId: 2});
out.archived = visible();
out.count = byId['machine-archive-count'].textContent;
out.switchedTo = shown.slice(-1)[0];
// A finger that moves before the long press scrolls instead.
fire('pointerdown', {target: find('pro'), pointerType: 'touch', pointerId: 3, clientX: 150, clientY: 20});
fire('pointermove', {pointerId: 3, clientX: 10, clientY: 20});
runTimers();
fire('pointerup', {pointerId: 3});
out.scrolled = visible();
// The last computer on the page cannot go to the archive.
out.refusedLast = [setMachineArchived('pro', true), setMachineArchived('mac-mini', true)];
out.afterRefuse = visible();
setMachineArchived('air', false);
out.restored = visible();
out.lastPost = posts[posts.length - 1];
console.log(JSON.stringify(out));
"""


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class MachineSwitcherBehaviourTests(unittest.TestCase):
    def test_drag_long_press_archive_and_restore(self):
        source = PAGE.read_text()
        start = source.index(START)
        code = source[start:source.index(END, start) + len(END)]
        result = subprocess.run(["node", "-e", HARNESS.replace("CODE", code)], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        out = json.loads(result.stdout)
        self.assertEqual(out["cached"], "pro,mac-mini,air")
        self.assertEqual(out["dragged"], "mac-mini,pro,air")
        self.assertTrue(out["dropTarget"])
        self.assertEqual((out["archived"], out["count"], out["switchedTo"]), ("mac-mini,pro", "1", "mac-mini"))
        self.assertEqual(out["scrolled"], "mac-mini,pro")
        self.assertEqual((out["refusedLast"], out["afterRefuse"]), ([True, False], "mac-mini"))
        self.assertEqual(out["restored"], "mac-mini,air")
        self.assertEqual(out["lastPost"], {"order": ["mac-mini", "pro", "air"], "archived": ["pro"]})


if __name__ == "__main__":
    unittest.main()
