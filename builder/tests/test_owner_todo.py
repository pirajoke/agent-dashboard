"""«Ждёт тебя» in MAIN MANAGER (Mark 2026-10-22): an owner-only list he edits on the site."""
from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dashboard_builder.owner_todo import SEED_ITEMS, StoreUnavailable, change_items, load_items

BUILDER = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("dashboard_owner_todo_test", BUILDER / "dashboard-server-m4.py")
SERVER = importlib.util.module_from_spec(spec)
spec.loader.exec_module(SERVER)
PAGE = (BUILDER / "mac-mini-dashboard" / "index.html").read_text()


def ids(*values):
    return iter(values).__next__


class OwnerTodoStoreTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "nested" / "owner-todo.json"

    def test_seed_until_first_change_then_the_file(self):
        self.assertEqual([item["id"] for item in load_items(self.path)["items"]], [item["id"] for item in SEED_ITEMS])
        change_items(self.path, {"action": "done", "id": "t-00000001"})
        items = load_items(self.path)["items"]
        self.assertTrue(items[0]["done"])
        self.assertEqual(len(items), len(SEED_ITEMS))
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_add_edit_done_undo_delete(self):
        change_items(self.path, {"action": "delete", "id": "t-00000004"})
        record = change_items(self.path, {"action": "add", "text": "  Позвонить   в банк ", "note": ""},
                              new_id=ids("t-0000000a"))
        self.assertEqual(record["items"][0], {"id": "t-0000000a", "text": "Позвонить в банк", "done": False,
                                              "created_at": record["updated_at"]})
        change_items(self.path, {"action": "edit", "id": "t-0000000a", "text": "Позвонить", "note": "до пятницы"})
        change_items(self.path, {"action": "done", "id": "t-0000000a"})
        item = load_items(self.path)["items"][0]
        self.assertEqual((item["text"], item["note"], item["done"]), ("Позвонить", "до пятницы", True))
        self.assertIn("done_at", item)
        change_items(self.path, {"action": "undo", "id": "t-0000000a"})
        self.assertNotIn("done_at", load_items(self.path)["items"][0])
        change_items(self.path, {"action": "delete", "id": "t-0000000a"})
        self.assertNotIn("t-0000000a", [entry["id"] for entry in load_items(self.path)["items"]])

    def test_bad_input_is_refused(self):
        for payload, error in (({"action": "add", "text": ""}, ValueError), ({"action": "add", "text": "x" * 201}, ValueError),
                               ({"action": "add", "text": "a\x07b"}, ValueError), ({"action": "nope", "id": "t-00000001"}, ValueError),
                               ({"action": "done", "id": "../x"}, ValueError), ({"action": "done", "id": "t-0000ffff"}, LookupError),
                               ([], ValueError)):
            with self.assertRaises(error):
                change_items(self.path, payload)

    def test_a_damaged_file_is_never_overwritten(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{broken")
        with self.assertRaises(StoreUnavailable):
            change_items(self.path, {"action": "add", "text": "x"})
        self.assertEqual(self.path.read_text(), "{broken")


class OwnerTodoEndpointTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "owner-todo.json"

    def call(self, method, body=None, *, token="fixture-owner", origin=None, host="localhost:9999"):
        handler = SERVER.Handler.__new__(SERVER.Handler)
        handler.path, handler.command = "/api/owner-todo", method
        data = json.dumps(body or {}).encode()
        handler.headers = {"Host": host, "Content-Length": str(len(data)), "Content-Type": "application/json"}
        if token is not None:
            handler.headers["X-Dashboard-Run-Token"] = token
        if origin is not None:
            handler.headers["Origin"] = origin
        handler.rfile = io.BytesIO(data)
        output = {}
        handler._json_response = lambda status, payload: output.update(status=status, payload=payload)
        with (patch.object(SERVER, "OWNER_TODO_FILE", self.path),
              patch.object(SERVER, "_dashboard_run_token", return_value="fixture-owner"),
              patch.object(SERVER.Handler, "_cloudflare_access_owner", return_value=False)):
            getattr(handler, f"do_{method}")()
        return output

    def test_owner_reads_and_writes(self):
        read = self.call("GET")
        self.assertEqual((read["status"], read["payload"]["state"]), (200, "ready"))
        saved = self.call("POST", {"action": "add", "text": "Купить ИБП"}, origin="http://localhost:9999")
        self.assertEqual(saved["status"], 200)
        self.assertEqual(saved["payload"]["items"][0]["text"], "Купить ИБП")
        self.assertEqual(self.call("POST", {"action": "done", "id": "t-0000ffff"})["status"], 404)
        self.assertEqual(self.call("POST", {"action": "add", "text": ""})["status"], 400)

    def test_anonymous_and_cross_origin_get_nothing(self):
        for host in ("localhost:9999", "command.meshly.fr"):
            anonymous = self.call("GET", token=None, host=host)
            self.assertEqual((anonymous["status"], anonymous["payload"]["items"]), (401, []))
            self.assertEqual(self.call("GET", token="wrong", host=host)["status"], 401)
            self.assertEqual(self.call("POST", {"action": "add", "text": "x"}, token=None, host=host)["status"], 401)
        self.assertEqual(self.call("POST", {"action": "add", "text": "x"}, origin="https://evil.example")["status"], 403)
        self.assertFalse(self.path.exists())

    def test_nothing_of_the_list_is_in_the_public_page(self):
        for item in SEED_ITEMS:
            self.assertNotIn(item["text"], PAGE)
        self.assertIn('id="mm-owner-todo"', PAGE)
        self.assertIn('id="mm-health"', PAGE)

    def test_closed_items_open_in_a_window_with_undo(self):
        # Mark 2026-10-23 ticked two items by mistake and could not find them again.
        self.assertIn('id="todo-done-dialog"', PAGE)
        self.assertIn("action: 'undo'", PAGE)
        self.assertIn("'↩ Вернуть'", PAGE)
        # The window lives outside the views, so it opens on every MAIN MANAGER tab.
        self.assertLess(PAGE.index('id="todo-done-dialog"'), PAGE.index('data-mm-panel="map"'))
        # Losing owner access empties and closes the windows, not only the lists on the page.
        render = PAGE[PAGE.index("function mmRenderOwnerTodo("):PAGE.index("function mmRenderTodoDone(")]
        self.assertIn("mmCloseTodoDone();", render)
        self.assertIn("getElementById('todo-done-list')?.replaceChildren()", render)
        projects = PAGE[PAGE.index("function mmRenderOwnerProjects("):PAGE.index("let mmOwnerProjectCards")]
        self.assertIn("getElementById('owner-project-body')?.replaceChildren()", projects)

    def test_home_is_one_grid_of_tiles(self):
        # Mark 2026-10-26: «пересобери его полностью». The week, his tasks, the projects and «Личное»
        # are tiles in one grid; the summary opens in a window from the week tile. No history block.
        home = PAGE[PAGE.index('id="mm-home"'):PAGE.index('data-mm-panel="project"')]
        for host in ('id="mm-week"', 'id="mm-owner-todo"', 'data-mm-panel="map"', 'id="mm-owner-projects"'):
            self.assertIn(host, home)
        self.assertNotIn('id="mm-summary"', home)
        self.assertIn('id="mm-summary"', PAGE[PAGE.index('id="mm-summary-dialog"'):])
        self.assertNotIn('id="mm-history"', PAGE)
        self.assertNotIn('mm-fold', PAGE)
        # His own «Ждёт тебя» list loads with the page again.
        opener = PAGE[PAGE.index("function openMainManager("):]
        self.assertIn("mmLoadOwnerTodo();", opener[:opener.index("\n}\n")])
        # «Личное» shows the card's status only: no task counter, no «Видно только тебе».
        self.assertNotIn('открытых задач:', PAGE)
        self.assertNotIn('Видно только тебе', PAGE)

    def test_summary_is_owner_only_and_has_three_periods(self):
        render = PAGE[PAGE.index("function mmRenderSummary("):PAGE.index("function mmInitSummary(")]
        self.assertIn("if (!data?.owner_view", render)
        self.assertIn("host.replaceChildren()", render)
        for label in ("'День', 1", "'Неделя', 7", "'Месяц', 30"):
            self.assertIn(label, PAGE)

    def test_services_turned_off_on_purpose_never_show_red(self):
        start = PAGE.index("const MM_HEALTH_TURNED_OFF")
        block = PAGE[start:PAGE.index("]);", start)]
        for label in ("homebrew.mxcl.ollama", "com.pirajoke.tag-website", "com.pirajoke.obsidian-tg-bot"):
            self.assertIn(label, block)
        self.assertIn("MM_HEALTH_TURNED_OFF.has(service.label)", PAGE)


if __name__ == "__main__":
    unittest.main()
