from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import unittest


BUILDER_DIR = Path(__file__).resolve().parents[1]
DASHBOARD_PATH = BUILDER_DIR / "mac-mini-dashboard" / "index.html"
SERVER_PATH = BUILDER_DIR / "dashboard-server-m4.py"


class CommandCenterUnifiedTabsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = DASHBOARD_PATH.read_text(encoding="utf-8")
        cls.server = SERVER_PATH.read_text(encoding="utf-8")

    def _js_function(self, name: str) -> str:
        match = re.search(
            rf"function {re.escape(name)}\([^)]*\)\s*\{{([\s\S]*?)\n\}}",
            self.html,
        )
        self.assertIsNotNone(match, f"missing JavaScript function {name}")
        return match.group(1)

    def _platform_handler(self, event_name: str) -> str | None:
        match = re.search(
            rf"platformDirectory\.addEventListener\(\s*['\"]{event_name}['\"]"
            r"\s*,\s*([A-Za-z_$][\w$]*)",
            self.html,
        )
        return match.group(1) if match else None

    def _css(self, selector: str) -> str:
        match = re.search(rf"{re.escape(selector)}\s*\{{([^}}]*)\}}", self.html)
        return match.group(1) if match else ""

    def test_ac_1_mac_mini_endpoint_contract_uses_proxy_for_served_pages(self):
        endpoint_contract = re.search(
            r"(const IS_FILE_DASHBOARD = .*?"
            r"const MAC_MINI_API = .*?;)",
            self.html,
            re.DOTALL,
        )
        self.assertIsNotNone(
            endpoint_contract,
            "the dashboard must expose one deterministic Mac mini endpoint contract",
        )
        action_contract = re.search(
            r"(async function miniAction\([^)]*\)\s*\{[\s\S]*?\n\})",
            self.html,
        )
        self.assertIsNotNone(action_contract, "missing Mac mini service action handler")

        cases = (
            ("http://localhost:7777/", "http://localhost:7777"),
            ("http://127.0.0.1:7777/", "http://127.0.0.1:7777"),
            ("https://command.meshly.fr/", "https://command.meshly.fr"),
            (
                "file:///dashboard/index.html",
                "http://100.77.209.73:8880",
            ),
        )

        for page_url, expected_base in cases:
            with self.subTest(page_url=page_url):
                javascript = "\n".join(
                    (
                        "const window = { location: new URL("
                        + json.dumps(page_url)
                        + ") };",
                        endpoint_contract.group(1),
                        "const calls = [];",
                        "const fetch = async (url, options) => "
                        "calls.push([url, options.method]);",
                        "const setTimeout = () => 0;",
                        "const refreshMini = () => {};",
                        action_contract.group(1),
                        "miniAction('health-gateway', 'start').then(() => "
                        "process.stdout.write(JSON.stringify({"
                        "read: `${MAC_MINI_API}/api/all`, action: calls[0]})));",
                    )
                )
                result = subprocess.run(
                    ["node", "-e", javascript],
                    check=True,
                    capture_output=True,
                    text=True,
                )

                self.assertEqual(
                    json.loads(result.stdout),
                    {
                        "read": f"{expected_base}/api/all",
                        "action": [
                            f"{expected_base}/api/service/health-gateway/start",
                            "POST",
                        ],
                    },
                    "served pages must send Mac mini reads and actions through "
                    "their same-origin dashboard proxy; file dashboards retain "
                    "the direct Tailscale endpoint",
                )

    def test_ac_3_platform_cards_reorder_by_long_press_and_keyboard_locally(self):
        platform_ids = re.findall(
            r'<article\b[^>]*\bdata-platform-id="([^"]+)"',
            self.html,
        )
        self.assertEqual(len(platform_ids), 12)
        self.assertEqual(len(set(platform_ids)), len(platform_ids))

        storage_ref = (
            r"(?:PLATFORM_[A-Z_]*ORDER[A-Z_]*|"
            r"['\"]command-center\.platform-order['\"])"
        )
        directory_binding = re.search(
            r"(?:const|let)\s+([A-Za-z_$][\w$]*)\s*=\s*document\."
            r"(?:querySelector\(\s*['\"]\.platform-directory['\"]\s*\)|"
            r"getElementById\(\s*['\"]platform-directory['\"]\s*\))",
            self.html,
        )
        directory_name = directory_binding.group(1) if directory_binding else None
        directory_events = ""
        if directory_name:
            directory_events = "\n".join(
                re.findall(
                    rf"{re.escape(directory_name)}\.addEventListener\([^;]+;",
                    self.html,
                )
            )

        cards_are_focusable = all(
            re.search(
                rf'<article\b[^>]*\bdata-platform-id="{re.escape(platform_id)}"'
                r'[^>]*\btabindex="0"',
                self.html,
            )
            for platform_id in platform_ids
        )
        keyboard_controls = bool(
            re.search(r"data-platform-move=(?:['\"])(?:previous|next)", self.html)
        )
        contracts = {
            "a localStorage key for the platform order": bool(
                re.search(r"command-center\.platform-order", self.html)
                and re.search(rf"localStorage\.getItem\(\s*{storage_ref}", self.html)
                and re.search(rf"localStorage\.setItem\(\s*{storage_ref}", self.html)
            ),
            "a long-press pointer lifecycle on the platform directory": bool(
                directory_name
                and all(
                    f"'{event}'" in directory_events or f'"{event}"' in directory_events
                    for event in ("pointerdown", "pointermove", "pointerup", "pointercancel")
                )
                and re.search(r"PLATFORM_[A-Z_]*LONG_PRESS[A-Z_]*\s*=\s*\d+", self.html)
            ),
            "keyboard-operable card movement": bool(
                keyboard_controls
                or (
                    directory_name
                    and ("'keydown'" in directory_events or '"keydown"' in directory_events)
                    and "ArrowUp" in directory_events
                    and "ArrowDown" in directory_events
                    and cards_are_focusable
                )
            ),
            # The resource GET is independent of order. Inspect only the actual
            # reorder implementation here, then execute both persistence paths below.
            "no platform-order HTTP persistence": re.search(
                r"\b(?:fetch|XMLHttpRequest|sendBeacon|WebSocket)\b",
                self.html[self.html.index("// Platform order is local-only."):
                          self.html.index("// Light or dark for the whole Command Center")],
            )
            is None
            and re.search(
                r"['\"]/api/[^'\"]*(?:platform.?order|tab.?name)",
                self.server,
                re.IGNORECASE,
            )
            is None,
        }
        missing = [description for description, present in contracts.items() if not present]
        self.assertEqual(
            missing,
            [],
            "platform cards need persistent, local-only pointer and keyboard reordering",
        )
        self._assert_platform_reorder_persistence_is_local()

    def _assert_platform_reorder_persistence_is_local(self):
        """Execute keyboard and drag commits, proving writes stay in localStorage."""
        names = ("platformCards", "platformGroupOf", "platformGroupCards", "readPlatformOrder",
                 "renumberPlatforms", "savePlatformOrder",
                 "announcePlatformOrder", "movePlatformByKey", "commitPlatformLongPress")
        functions = "\n".join("function " + name + "(" + (
            "event, directions" if name == "movePlatformByKey" else
            "event" if name == "commitPlatformLongPress" else
            "card" if name in ("platformGroupOf", "platformGroupCards") else
            "card, prefix = 'Перемещено:'" if name == "announcePlatformOrder" else ""
        ) + ") {" + self._js_function(name) + "\n}" for name in names)
        javascript = r'''
const stored=new Map(), writes=[], network=[];
const localStorage={getItem:k=>stored.get(k)||null,setItem:(k,v)=>{writes.push([k,v]);stored.set(k,v);}};
const fetch=(...args)=>{network.push(['fetch',...args]);return Promise.resolve({ok:true});};
function XMLHttpRequest(){network.push(['xhr']);}
const navigator={sendBeacon:(...args)=>network.push(['beacon',...args])};
const PLATFORM_ORDER_STORAGE_KEY='command-center.platform-order.v1';
const PLATFORM_CANONICAL_IDS=['financial','mydictionary','health'];
let cards=PLATFORM_CANONICAL_IDS.map(id=>({dataset:{platformId:id,platformName:id},number:{},
classList:{remove(){}},removeAttribute(){},querySelector(){return this.number;},
before(card){const from=cards.indexOf(card);cards.splice(from,1);cards.splice(cards.indexOf(this),0,card);},
after(card){const from=cards.indexOf(card);cards.splice(from,1);cards.splice(cards.indexOf(this)+1,0,card);}}));
const platformDirectory={querySelectorAll:()=>cards,contains:()=>true};
const status={textContent:''};const document={getElementById:()=>status};
let platformPointerState=null, platformSuppressClickUntil=0;
function clearPlatformLongPressTimer(){}function settlePlatformCard(){}function releasePlatformPointerCapture(){}
function arrangePlatformGroups(){}function savePlatformGroup(){network.push(['group']);}
''' + functions + r'''
// Mark 2026-10-20 removed the arrow buttons: ↑ on a focused card moves it, like a drag.
const keyboardCard=cards[1];keyboardCard.classList.contains=()=>true;keyboardCard.focus=()=>{};
movePlatformByKey({key:'ArrowUp',target:keyboardCard,preventDefault(){}},{ArrowUp:'previous',ArrowDown:'next'});
const keyboard=JSON.parse(stored.get(PLATFORM_ORDER_STORAGE_KEY));
const initialOrder=cards.map(c=>c.dataset.platformId);cards=[cards[2],cards[0],cards[1]];
platformPointerState={pointerId:9,active:true,changed:true,card:cards[0],initialOrder,startGroup:'product'};
commitPlatformLongPress({pointerId:9,cancelable:true,preventDefault(){}});
const dragged=JSON.parse(stored.get(PLATFORM_ORDER_STORAGE_KEY));
process.stdout.write(JSON.stringify({keyboard,dragged,restored:readPlatformOrder(),writes,network}));
'''
        result = subprocess.run(["node", "-e", javascript], check=True, capture_output=True, text=True)
        out = json.loads(result.stdout)
        self.assertEqual(out["keyboard"], ["mydictionary", "financial", "health"])
        self.assertEqual(out["dragged"], ["health", "mydictionary", "financial"])
        self.assertEqual(out["restored"], out["dragged"])
        self.assertEqual(len(out["writes"]), 2)
        self.assertTrue(all(key == "command-center.platform-order.v1" for key, _ in out["writes"]))
        self.assertEqual(out["network"], [], "Order persistence must never leave this browser")

    def test_ec_3_mobile_long_press_preserves_scroll_then_cancels_active_touch(self):
        move_handler = self._platform_handler("pointermove")
        move_source = self._js_function(move_handler) if move_handler else ""
        contracts = {
            "pan-y before activation": re.search(
                r"touch-action\s*:\s*pan-y", self._css(".platform-entry")
            )
            is not None,
            "touch-action none while reordering": re.search(
                r"touch-action\s*:\s*none", self._css(".platform-entry.is-reordering")
            )
            is not None,
            "a non-passive active-move cancellation path": bool(
                re.search(
                    r"platformDirectory\.addEventListener\(\s*['\"]pointermove['\"]"
                    r"[\s\S]{0,160}?passive\s*:\s*false",
                    self.html,
                )
                and "state.active" in move_source
                and "preventDefault()" in move_source
            ),
        }
        missing = [description for description, present in contracts.items() if not present]
        self.assertEqual(
            missing,
            [],
            "touch gestures must scroll normally before activation and cancel scrolling once held",
        )

    def test_ec_4_cancelled_platform_gestures_restore_the_snapshot_without_saving(self):
        begin_source = self._js_function("beginPlatformLongPress")
        move_source = self._js_function("movePlatformLongPress")
        pointerup_handler = self._platform_handler("pointerup")
        cancel_handler = self._platform_handler("pointercancel")
        cancel_source = self._js_function(cancel_handler) if cancel_handler else ""

        cleanup = all(
            contract in cancel_source
            for contract in (
                "classList.remove('is-reordering')",
                "removeAttribute('aria-grabbed')",
                "platformPointerState = null",
            )
        )
        contracts = {
            "an initial-order snapshot": bool(
                re.search(r"(?:initialOrder|originalOrder|orderSnapshot)\s*:", begin_source)
                and re.search(r"platformCards\(\)\.map\(", begin_source)
            ),
            "no persistence during pointermove": "savePlatformOrder(" not in move_source,
            "a distinct commit-only pointerup handler": bool(
                pointerup_handler and cancel_handler and pointerup_handler != cancel_handler
            ),
            "pointercancel rollback and UI cleanup": bool(
                re.search(
                    r"applyPlatformOrder\(\s*state\."
                    r"(?:initialOrder|originalOrder|orderSnapshot)\s*\)",
                    cancel_source,
                )
                and cleanup
            ),
            "lost pointer capture rollback": bool(
                cancel_handler
                and re.search(
                    rf"platformDirectory\.addEventListener\(\s*['\"]lostpointercapture['\"]"
                    rf"\s*,\s*{re.escape(cancel_handler)}\b",
                    self.html,
                )
            ),
            "window blur rollback": bool(
                cancel_handler
                and re.search(
                    rf"window\.addEventListener\(\s*['\"]blur['\"]"
                    rf"\s*,\s*{re.escape(cancel_handler)}\b",
                    self.html,
                )
            ),
            "hidden-page rollback": bool(
                cancel_handler
                and re.search(
                    rf"visibilitychange[\s\S]{{0,500}}?document\.hidden"
                    rf"[\s\S]{{0,220}}?{re.escape(cancel_handler)}\(",
                    self.html,
                )
            ),
        }
        missing = [description for description, present in contracts.items() if not present]
        self.assertEqual(
            missing,
            [],
            "only pointerup may commit; every interrupted gesture must roll back and clean up",
        )

    def test_err_1_failed_long_press_save_warns_visit_only_instead_of_moved(self):
        pointerup_handler = self._platform_handler("pointerup")
        pointerup_source = self._js_function(pointerup_handler) if pointerup_handler else ""
        saved = re.search(
            r"(?:const|let)\s+([A-Za-z_$][\w$]*)\s*=\s*savePlatformOrder\(\)",
            pointerup_source,
        )
        save_result = saved.group(1) if saved else None
        self.assertTrue(
            save_result
            and re.search(
                rf"{re.escape(save_result)}\s*\?\s*['\"]Перемещено:['\"]\s*:\s*"
                r"['\"]Перемещено до перезагрузки",
                pointerup_source,
            )
            and not re.search(
                r"announcePlatformOrder\(\s*state\.card\s*\)\s*;",
                pointerup_source,
            ),
            "a failed long-press save must announce visit-only state, never unconditional Moved",
        )

    def test_reg_1_active_mobile_hold_uses_non_passive_touchmove_cancellation(self):
        touchmove_listener = re.search(
            r"(?:platformDirectory|document|window)\.addEventListener\(\s*"
            r"['\"]touchmove['\"]\s*,\s*([A-Za-z_$][\w$]*)\s*,\s*"
            r"\{[^}]*\bpassive\s*:\s*false",
            self.html,
        )
        handler_source = (
            self._js_function(touchmove_listener.group(1))
            if touchmove_listener
            else ""
        )

        self.assertTrue(
            touchmove_listener
            and re.search(r"\bactive\b", handler_source)
            and re.search(r"\.preventDefault\(\)", handler_source),
            "changing touch-action after pointerdown and cancelling pointermove is not a "
            "valid mobile scroll lock; an explicitly non-passive touchmove handler must "
            "prevent default only after the stationary long press becomes active",
        )

    def test_reg_2_long_press_does_not_cancel_itself_by_transferring_capture(self):
        begin_source = self._js_function("beginPlatformLongPress")
        lost_handler = self._platform_handler("lostpointercapture")
        lost_source = self._js_function(lost_handler) if lost_handler else ""

        directory_capture_transfer = bool(
            re.search(r"\bplatformDirectory\.setPointerCapture\(", begin_source)
        )
        original_target_capture = bool(
            re.search(
                r"(?:state\.)?(?:pointerDownTarget|pointerTarget|captureTarget|downTarget)"
                r"\.setPointerCapture\(",
                begin_source,
            )
        )
        internal_transfer_is_distinguished = bool(
            re.search(
                r"(?:internal|transfer|captureTarget|pointerTarget|downTarget|event\.target)",
                lost_source,
                re.IGNORECASE,
            )
            and re.search(r"\b(?:return|ignore)\b", lost_source)
        )

        self.assertTrue(
            not directory_capture_transfer
            or original_target_capture
            or internal_transfer_is_distinguished,
            "activation must retain the original pointerdown capture target, or explicitly "
            "ignore the bubbling lostpointercapture caused by an intentional transfer",
        )

    def test_reg_3_release_outside_before_activation_clears_the_pending_timer(self):
        def global_pointer_handler(event_name: str) -> str | None:
            match = re.search(
                rf"(?:window|document)\.addEventListener\(\s*['\"]{event_name}['\"]"
                r"\s*,\s*([A-Za-z_$][\w$]*)",
                self.html,
            )
            return match.group(1) if match else None

        pointerup_handler = global_pointer_handler("pointerup")
        pointercancel_handler = global_pointer_handler("pointercancel")
        global_handlers = tuple(
            handler for handler in (pointerup_handler, pointercancel_handler) if handler
        )
        global_cleanup = (
            len(global_handlers) == 2
            and all(
                "clearPlatformLongPressTimer()" in self._js_function(handler)
                and "platformPointerState = null" in self._js_function(handler)
                for handler in global_handlers
            )
        )

        pointerleave = re.search(
            r"platformDirectory\.addEventListener\(\s*['\"]pointerleave['\"]"
            r"\s*,\s*([A-Za-z_$][\w$]*)",
            self.html,
        )
        leave_cleanup = False
        if pointerleave:
            leave_source = self._js_function(pointerleave.group(1))
            leave_cleanup = (
                "clearPlatformLongPressTimer()" in leave_source
                and "platformPointerState = null" in leave_source
                and re.search(r"\bactive\b", leave_source) is not None
            )

        self.assertTrue(
            global_cleanup or leave_cleanup,
            "pointerup/pointercancel outside the directory (or pointerleave before activation) "
            "must clear the 500 ms timer so it cannot start a phantom reorder",
        )

    def test_reg_4_tab_name_sanitizer_removes_visually_blank_default_ignorables(self):
        sanitizer = self._js_function("sanitizeTabName")
        javascript = "\n".join(
            (
                "const TAB_NAME_MAX_CODE_POINTS = 32;",
                "function sanitizeTabName(value) {" + sanitizer + "\n}",
                "const values = [",
                "  '\\u034F', '\\u00AD', '\\u180E',",
                "  '\\u034F\\u00AD\\u180E\\u200B\\u2060\\uFEFF',",
                "  '  \\u034FVisible\\u00AD name\\u180E  ',",
                "];",
                "process.stdout.write(JSON.stringify(values.map(sanitizeTabName)));",
            )
        )
        result = subprocess.run(
            ["node", "-e", javascript],
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertEqual(
            json.loads(result.stdout),
            ["", "", "", "", "Visible name"],
            "CGJ, soft hyphen, and Mongolian vowel separator are visually blank "
            "default-ignorables and must not bypass blank fallback or duplicate checks",
        )

    def test_reg_5_early_local_storage_read_cannot_abort_preferences_bootstrap(self):
        current_run = re.search(
            r"(?:let|var)\s+currentJarvisRunId\s*=\s*([^;]+);",
            self.html,
        )
        self.assertIsNotNone(current_run, "missing current JARVIS run bootstrap")
        initializer = current_run.group(1).strip()

        direct_unguarded_read = re.search(
            r"(?:window\.)?localStorage\.getItem\(", initializer
        )
        helper_call = re.fullmatch(r"([A-Za-z_$][\w$]*)\([^;]*\)(?:\s*\|\|\s*['\"]{2})?", initializer)
        guarded_helper = False
        if helper_call:
            helper_source = self._js_function(helper_call.group(1))
            guarded_helper = all(
                token in helper_source
                for token in ("localStorage", "getItem", "try", "catch")
            )

        declaration_end = current_run.end()
        nearby_bootstrap = self.html[max(0, current_run.start() - 500):declaration_end + 500]
        guarded_assignment = bool(
            re.search(
                r"(?:let|var)\s+currentJarvisRunId\s*=\s*['\"]{2}\s*;"
                r"[\s\S]{0,300}?try\s*\{[\s\S]{0,240}?currentJarvisRunId\s*="
                r"[\s\S]{0,160}?(?:window\.)?localStorage\.getItem\("
                r"[\s\S]{0,240}?\}\s*catch\b",
                nearby_bootstrap,
            )
        )

        self.assertTrue(
            (not direct_unguarded_read and guarded_helper) or guarded_assignment,
            "the early current-run localStorage read must fail closed to an empty value; "
            "storage-denied/file-origin sessions must still reach tab and platform preferences",
        )

    def test_reg_6_live_reorder_uses_stable_capture_and_filters_transfer_loss(self):
        begin_source = self._js_function("beginPlatformLongPress")
        move_source = self._js_function("movePlatformLongPress")
        lost_handler = self._platform_handler("lostpointercapture")
        lost_source = self._js_function(lost_handler) if lost_handler else ""

        live_dom_reorder = re.search(
            r"\.(?:before|after)\(\s*state\.card\s*\)",
            move_source,
        ) is not None
        stable_capture_target = bool(
            re.search(
                r"\bplatformDirectory\.setPointerCapture\(\s*state\.pointerId\s*\)",
                begin_source,
            )
            or (
                re.search(
                    r"\b(?:captureTarget|pointerTarget)\s*:\s*platformDirectory\b",
                    begin_source,
                )
                and re.search(
                    r"state\.(?:captureTarget|pointerTarget)\.setPointerCapture\(",
                    begin_source,
                )
            )
        )
        ignores_old_descendant_transfer = bool(
            re.search(
                r"if\s*\([^)]*event(?:\?\.)?\.target[^)]*(?:"
                r"!==\s*(?:state\.)?(?:captureTarget|platformDirectory)|"
                r"===\s*state\.(?:pointerTarget|downTarget))[^)]*\)"
                r"\s*(?:\{\s*)?return\b",
                lost_source,
            )
        )
        genuine_capture_loss_rolls_back = bool(
            lost_handler
            and (
                re.search(r"\bcancelPlatformLongPress\(\s*event\s*\)", lost_source)
                or (
                    "applyPlatformOrder(state.initialOrder)" in lost_source
                    and "platformPointerState = null" in lost_source
                )
            )
        )

        self.assertTrue(
            genuine_capture_loss_rolls_back
            and (
                not live_dom_reorder
                or (stable_capture_target and ignores_old_descendant_transfer)
            ),
            "live pointermove reordering must capture on a stable connected ancestor and "
            "ignore the intentional lostpointercapture from the old card descendant, while "
            "a genuine capture loss must still cancel and restore the order; alternatively, "
            "defer DOM movement until pointerup",
        )

    def test_reg_7_storage_denial_cannot_abort_the_synchronous_init_chain(self):
        init_block_match = re.search(
            r"//\s*[^\n]*Init[^\n]*\n([\s\S]*?)\nsetInterval\(",
            self.html,
        )
        self.assertIsNotNone(init_block_match, "missing synchronous dashboard init block")
        init_block = init_block_match.group(1)
        ordered_initializers = (
            "initJarvisHud",
            "initJarvisBudget",
            "initJarvisRunPanel",
            "initPixelAgentsView",
            "initPixelAgentsPin",
            "initDragDrop",
        )
        positions = [init_block.find(f"{name}();") for name in ordered_initializers]
        self.assertTrue(
            all(position >= 0 for position in positions)
            and positions == sorted(positions),
            "the storage-sensitive initializers and later UI initializers must remain in "
            "the synchronous load chain",
        )

        # These are the storage-bearing functions reached synchronously from that chain.
        # A function may instead delegate to a guarded helper, in which case it has no direct
        # localStorage access and remains valid under this contract.
        synchronous_storage_functions = (
            "applyJarvisHudState",
            "initJarvisHud",
            "initJarvisBudget",
            "initJarvisRunTokenFromHash",
            "loadPixelAgentsView",
            "initPixelAgentsPin",
            "restoreLayout",
        )
        storage_call = re.compile(
            r"(?:window\.)?localStorage\.(?:getItem|setItem|removeItem)\("
        )

        def direct_storage_is_guarded(function_name: str) -> bool:
            source = self._js_function(function_name)
            accesses = list(storage_call.finditer(source))
            if not accesses:
                return True
            guarded_ranges = [
                (match.start(1), match.end(1))
                for match in re.finditer(
                    r"try\s*\{([\s\S]*?)\}\s*catch(?:\s*\([^)]*\))?\s*\{",
                    source,
                )
            ]
            return all(
                any(start <= access.start() < end for start, end in guarded_ranges)
                for access in accesses
            )

        unsafe = [
            name
            for name in synchronous_storage_functions
            if not direct_storage_is_guarded(name)
        ]
        self.assertEqual(
            unsafe,
            [],
            "storage get/set/remove may throw (Safari private mode, denied storage, file "
            "origin); every synchronous initializer must contain the failure or use a "
            "guarded helper so later initJarvisBudget/initPixelAgentsPin/initDragDrop calls "
            "remain reachable",
        )

    def test_ac_4_top_level_tab_names_rename_safely_persist_and_reset(self):
        nav_match = re.search(
            r'<nav class="nav-pills cc-main-nav"[^>]*>(.*?)</nav>',
            self.html,
            re.DOTALL,
        )
        self.assertIsNotNone(nav_match)
        nav = nav_match.group(1)
        # Mark 2026-10-14: «По дням» (today) is gone, MAIN MANAGER is the first tab.
        routes = ("work", "growth", "agents", "architecture", "platforms", "documents", "context", "machines")

        for route in routes:
            with self.subTest(route=route):
                button = re.search(
                    rf"<button\b(?=[^>]*\baria-controls=\"section-{route}\")"
                    rf"(?=[^>]*\bonclick=\"showSection\('{route}'\)\")[^>]*>",
                    nav,
                )
                self.assertIsNotNone(
                    button,
                    f"renaming must not change the stable {route!r} section route",
                )

        label_routes = tuple(
            re.findall(r'data-tab-label="([^"]+)"', nav)
        )
        storage_ref = (
            r"(?:TAB_[A-Z_]*NAME[A-Z_]*|"
            r"['\"]command-center\.tab-names['\"])"
        )
        contracts = {
            "one text-only label target per stable route": label_routes == routes,
            "localStorage restore and save": bool(
                re.search(r"command-center\.tab-names", self.html)
                and re.search(rf"localStorage\.getItem\(\s*{storage_ref}", self.html)
                and re.search(rf"localStorage\.setItem\(\s*{storage_ref}", self.html)
            ),
            "an inline text editor": bool(
                "tab-name-editor" in self.html
                and re.search(
                    r"document\.createElement\(\s*['\"]input['\"]\s*\)",
                    self.html,
                )
            ),
            "a user-driven rename control": bool(
                re.search(r"\bdata-tab-rename(?:=|\b)", self.html)
                or (
                    re.search(r"addEventListener\(\s*['\"]dblclick['\"]", self.html)
                    and "F2" in self.html
                )
            ),
            "a user-visible reset control": bool(
                re.search(
                    r"<(?:button|input)\b[^>]*(?:\bid=\"reset-tab-names\"|"
                    r"\bdata-tab-names-reset(?:=|\b))",
                    self.html,
                )
                and re.search(rf"localStorage\.removeItem\(\s*{storage_ref}", self.html)
            ),
            "safe text-only rendering": bool(
                re.search(
                    r"querySelector(?:All)?\([^)]*data-tab-label[^)]*\)"
                    r"[\s\S]{0,1600}?\.textContent\s*=",
                    self.html,
                )
                and not re.search(
                    r"querySelector(?:All)?\([^)]*data-tab-label[^)]*\)"
                    r"[\s\S]{0,1600}?\.innerHTML\s*=",
                    self.html,
                )
            ),
        }
        missing = [description for description, present in contracts.items() if not present]
        self.assertEqual(
            missing,
            [],
            "top-level names need inline rename, persistence, reset, and text-only rendering",
        )


if __name__ == "__main__":
    unittest.main()
