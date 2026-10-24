from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
import re
import unittest
from urllib.parse import urlsplit


DASHBOARD_PATH = (
    Path(__file__).resolve().parents[1] / "mac-mini-dashboard" / "index.html"
)

EXPECTED_PLATFORMS = {
    "financial": (
        "JobRadar",
        (
            "https://command.meshly.fr/job-radar/",
            "https://t.me/JobsRadarS_bot",
        ),
    ),
    "mydictionary": (
        "Lexi",
        (
            "https://mydictionary.meshly.fr/admin",
            "https://t.me/my_dictionnary_tg_bot",
        ),
    ),
    "health": ("Health OS", ("https://health.meshly.fr/",)),
    "ai-singularity": (
        "AI Singularity",
        ("https://singularity.meshly.fr/",),
    ),
    "context-news": (
        "Context News France",
        ("https://t.me/contextnews_bot",),
    ),
    "accountable": (
        "Accountable OS",
        ("https://accountable.meshly.fr/",),
    ),
    "jarvis": ("JARVIS", ("https://t.me/max_jarvis_hoian_bot",)),
    "property-os": ("Property OS", ("https://properties.meshly.fr/",)),
    "pixel-agents": ("Pixel Agents", ("https://pixel-agents.meshly.fr/",)),
    "closeness-mirror": ("Зеркало Контакта", ("http://127.0.0.1:3051",)),
    "sushi-parisien": ("Sushi Parisien", ("https://sushi-parisien.meshly.fr/",)),
    "n8n": ("n8n", ("http://127.0.0.1:5678",)),
}


class _CommandCenterParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.nav_targets: dict[str, str] = {}
        self.platform_section_count = 0
        self.platforms: dict[str, dict[str, object]] = {}
        self._nav_target: str | None = None
        self._nav_text: list[str] = []
        self._platform_id: str | None = None
        self._platform_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = (attributes.get("class") or "").split()

        onclick = attributes.get("onclick") or ""
        nav_target = re.fullmatch(r"showSection\(['\"]([^'\"]+)['\"]\)", onclick)
        if tag == "button" and "nav-pill" in classes and nav_target:
            self._nav_target = nav_target.group(1)
            self._nav_text = []

        if attributes.get("id") == "section-platforms":
            self.platform_section_count += 1

        platform_id = attributes.get("data-platform-id")
        if platform_id is not None:
            self._platform_id = platform_id
            self._platform_depth = 1
            self.platforms[platform_id] = {
                "name": attributes.get("data-platform-name"),
                "links": [],
            }
        elif self._platform_id is not None:
            self._platform_depth += 1

        if tag == "a" and self._platform_id is not None:
            links = self.platforms[self._platform_id]["links"]
            assert isinstance(links, list)
            links.append(attributes)

    def handle_data(self, data: str) -> None:
        if self._nav_target is not None:
            self._nav_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "button" and self._nav_target is not None:
            self.nav_targets[self._nav_target] = " ".join(
                "".join(self._nav_text).split()
            )
            self._nav_target = None
            self._nav_text = []

        if self._platform_id is not None:
            self._platform_depth -= 1
            if self._platform_depth == 0:
                self._platform_id = None


class CommandCenterPlatformsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = DASHBOARD_PATH.read_text(encoding="utf-8")
        cls.parser = _CommandCenterParser()
        cls.parser.feed(cls.html)

    def test_historical_command_center_identity_is_preserved(self):
        # Mark 2026-10-14: one design for every tab, in Russian.
        self.assertIn("Привет, Максим", self.html)
        for target, label in (
            ("mac-mini", "Mac Mini"),
            ("air", "Air"),
            ("pro", "Pro"),
            ("agents", "Агенты"),
        ):
            self.assertIn(target, self.parser.nav_targets)
            self.assertIn(label, self.parser.nav_targets[target])

    def test_platforms_is_a_reachable_top_level_surface(self):
        self.assertEqual(self.parser.platform_section_count, 1)
        self.assertIn("platforms", self.parser.nav_targets)
        self.assertIn("Платформы", self.parser.nav_targets["platforms"])

        initial_guard = re.search(
            r"\[([^\]]+)\]\.includes\(INITIAL_SECTION\)",
            self.html,
        )
        self.assertIsNotNone(initial_guard, "INITIAL_SECTION needs a safe allowlist")
        allowed = re.findall(r"['\"]([^'\"]+)['\"]", initial_guard.group(1))
        self.assertIn("platforms", allowed)

    def test_platform_directory_has_exact_registry_and_safe_destinations(self):
        self.assertEqual(set(self.parser.platforms), set(EXPECTED_PLATFORMS))

        for platform_id, (expected_name, expected_hrefs) in EXPECTED_PLATFORMS.items():
            with self.subTest(platform=platform_id):
                platform = self.parser.platforms[platform_id]
                self.assertEqual(platform["name"], expected_name)
                links = platform["links"]
                assert isinstance(links, list)
                self.assertEqual(
                    tuple(link.get("href") for link in links),
                    expected_hrefs,
                )
                for link in links:
                    self.assertEqual(link.get("target"), "_blank")
                    self.assertEqual(
                        set((link.get("rel") or "").split()),
                        {"noopener", "noreferrer"},
                    )

                    href = link.get("href") or ""
                    parsed = urlsplit(href)
                    self.assertIsNone(parsed.username)
                    self.assertIsNone(parsed.password)
                    self.assertEqual(parsed.query, "")
                    self.assertEqual(parsed.fragment, "")
                    self.assertNotIn("51.255.36.141", href)
                    self.assertNotRegex(
                        href,
                        r"(?i)(?:file:|/Users/|/home/|/srv/)",
                    )
                    if parsed.hostname == "127.0.0.1":
                        self.assertEqual(parsed.scheme, "http")
                    else:
                        self.assertEqual(parsed.scheme, "https")
                        self.assertIn(
                            parsed.hostname,
                            {"t.me", "command.meshly.fr", "health.meshly.fr", "properties.meshly.fr", "pixel-agents.meshly.fr", "mydictionary.meshly.fr", "singularity.meshly.fr", "accountable.meshly.fr", "sushi-parisien.meshly.fr"},
                        )

    def test_ac_1_accountable_copy_describes_french_micro_bnc(self):
        card = re.search(r'<article[^>]*data-platform-id="accountable"[\s\S]*?</article>', self.html)
        self.assertIsNotNone(card)
        self.assertRegex(card.group(), r"(?i)micro[ -]?BNC")
        self.assertRegex(card.group(), r"(?i)франц|France|French")
        self.assertNotIn("личной ответственности", card.group())

    def test_ac_4_each_existing_platform_has_owner_resource_area(self):
        cards = re.findall(r'<article[^>]*data-platform-id="([^"]+)"([\s\S]*?)</article>', self.html)
        self.assertEqual(len(cards), 12)
        for platform_id, card in cards:
            with self.subTest(platform=platform_id):
                self.assertRegex(card, r'class="[^"]*platform-resources')
                self.assertRegex(card, r'aria-live="polite"|role="status"')
        self.assertIn("/api/platform-resources", self.html)

    def test_platform_directory_is_responsive_keyboard_safe_and_motion_safe(self):
        self.assertTrue(
            'class="platform-directory"' in self.html,
            "Platforms needs the platform-directory layout hook",
        )
        self.assertTrue(
            re.search(
                r"@media\s*\([^)]*max-width[^)]*\)[\s\S]*?\.platform-directory",
                self.html,
            )
            is not None,
            "platform-directory needs a responsive breakpoint",
        )
        self.assertTrue(
            re.search(r"\.platform-link:focus-visible\s*\{", self.html) is not None,
            "platform links need a visible keyboard focus treatment",
        )
        self.assertTrue(
            re.search(
                r"@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{"
                r"[\s\S]*?\.platform-link",
                self.html,
            )
            is not None,
            "platform link motion needs a reduced-motion override",
        )


    def test_archive_buttons_move_cards_and_choice_survives_reload(self):
        """Mark 2026-10-20: «эти проекты в архив» + «добавь маленькую кнопочку архива».

        Runs the shipped archive and order functions against a small DOM: the
        default archive, an archive and a restore through the cards' own
        buttons, and the same layout rebuilt from localStorage after a reload.
        """
        import json
        import shutil
        import subprocess

        node = shutil.which("node")
        self.assertIsNotNone(node, "Node runtime required for the archive behaviour test")
        start = self.html.index("// Platform order is local-only.")
        end = self.html.index("applyPlatformArchive();\napplyPlatformOrder(readPlatformOrder());")
        order_and_archive = self.html[start:end]
        # The order block binds the live directory; the fake DOM below supplies it instead.
        order_and_archive = re.sub(
            r"const platformDirectory = document\.querySelector\('\.platform-directory'\);",
            "const platformDirectory = document.platformDirectory;",
            order_and_archive,
        )
        order_and_archive = re.sub(
            r"const platformArchiveList = document\.getElementById\('platform-archive-list'\);",
            "const platformArchiveList = document.platformArchiveList;",
            order_and_archive,
        )
        ids = list(EXPECTED_PLATFORMS)
        setup = r"""
const IDS = __IDS__;
class El {
  constructor(tag, cls='') { this.tagName=tag; this.className=cls; this.children=[]; this.parent=null; this.dataset={}; this.attrs={}; this.hidden=false; this.textContent=''; }
  get classes() { return this.className.split(/\s+/); }
  matches(sel) { return sel.startsWith('.') && this.classes.includes(sel.slice(1)); }
  appendChild(node) { if (node.parent) node.parent.removeChild(node); node.parent=this; this.children.push(node); return node; }
  removeChild(node) { this.children.splice(this.children.indexOf(node), 1); node.parent=null; }
  insertBefore(node, ref) { if (!ref) return this.appendChild(node); if (node.parent) node.parent.removeChild(node); node.parent=this; this.children.splice(this.children.indexOf(ref), 0, node); return node; }
  all() { return this.children.flatMap(c => [c, ...c.all()]); }
  querySelectorAll(sel) { return this.all().filter(n => n.matches(sel)); }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  contains(node) { for (let n=node; n; n=n.parent) if (n===this) return true; return false; }
  closest(sel) { for (let n=this; n; n=n.parent) if (n.matches && n.matches(sel)) return n; return null; }
  setAttribute(k, v) { this.attrs[k]=String(v); }
  removeAttribute(k) { delete this.attrs[k]; }
  getAttribute(k) { return this.attrs[k] ?? null; }
  focus() { focused=this; }
  set innerHTML(v) { this._html=v; }
}
let focused=null;
const stored=new Map();
const localStorage={getItem:k=>stored.has(k)?stored.get(k):null,setItem:(k,v)=>stored.set(k,String(v))};
function page() {
  const directory=new El('div','platform-directory');
  IDS.forEach(id => { const card=new El('article','platform-entry'); card.dataset.platformId=id; card.dataset.platformName=id;
    card.appendChild(new El('span','platform-index')); directory.appendChild(card); });
  const archiveList=new El('div','platform-directory platform-archive-list'); archiveList.hidden=true;
  const byId={'platform-archive':new El('div'),'platform-archive-count':new El('span'),'platforms-badge':new El('span'),
    'platform-order-status':new El('p'),'platform-archive-open':new El('button')};
  return {directory, archiveList, byId};
}
function boot(p) {
  const document={platformDirectory:p.directory, platformArchiveList:p.archiveList,
    getElementById:id=>p.byId[id]||null, createElement:tag=>new El(tag)};
  const window={setTimeout:()=>0};
  const fn = new Function('document','localStorage','window','navigator', __CODE__ + `
    applyPlatformArchive(); applyPlatformOrder(readPlatformOrder());
    return {togglePlatformArchive, platformCards};`);
  return fn(document, localStorage, window, {});
}
function snapshot(p) {
  return {main:p.directory.children.map(c=>c.dataset.platformId+':'+c.querySelector('.platform-index').textContent),
    archive:p.archiveList.children.map(c=>c.dataset.platformId),
    count:p.byId['platform-archive-count'].textContent, badge:p.byId['platforms-badge'].textContent,
    archiveHidden:p.byId['platform-archive'].hidden};
}
function click(api, p, id) {
  const card=[...p.directory.children, ...p.archiveList.children].find(c=>c.dataset.platformId===id);
  const button=card.querySelector('.platform-archive-toggle');
  api.togglePlatformArchive({target:button});
  return {label:button.getAttribute('aria-label'), type:button.type, tabindex:card.getAttribute('tabindex'), focused:focused===button ? 'button' : focused===p.byId['platform-archive-open'] ? 'archive-open' : 'other'};
}
let p=page(); let api=boot(p);
const initial=snapshot(p);
const restored=click(api,p,'n8n');
const archived=click(api,p,'pixel-agents');
const afterClicks=snapshot(p);
p=page(); api=boot(p);
process.stdout.write(JSON.stringify({initial, restored, archived, afterClicks, reloaded:snapshot(p)}));
"""
        script = setup.replace("__IDS__", json.dumps(ids)).replace("__CODE__", json.dumps(order_and_archive))
        run = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=15)
        self.assertEqual(run.returncode, 0, run.stderr)
        out = json.loads(run.stdout)

        default_archive = ["closeness-mirror", "sushi-parisien", "n8n"]
        self.assertEqual(out["initial"]["archive"], default_archive)
        self.assertEqual(
            out["initial"]["main"],
            [f"{pid}:{n:02d}" for n, pid in enumerate([i for i in ids if i not in default_archive], 1)],
        )
        self.assertEqual((out["initial"]["count"], out["initial"]["badge"]), ("3", "9"))
        self.assertFalse(out["initial"]["archiveHidden"])

        # Native <button>s, so Enter and Space work; focus follows the card or the archive button.
        self.assertEqual(out["restored"], {"label": "n8n: в архив", "type": "button", "tabindex": "0", "focused": "button"})
        self.assertEqual(out["archived"]["label"], "pixel-agents: вернуть из архива")
        # ↑/↓ reorder only the board, so an archived card stops being a keyboard reorder stop.
        self.assertIsNone(out["archived"]["tabindex"])
        self.assertEqual(out["archived"]["focused"], "archive-open")

        self.assertEqual(out["afterClicks"]["archive"], ["pixel-agents", "closeness-mirror", "sushi-parisien"])
        self.assertEqual(out["afterClicks"]["main"][-1], "n8n:09")
        self.assertEqual(out["reloaded"], out["afterClicks"])


class OwnerResourcesBrowserTests(unittest.TestCase):
    """AC-4/6, EC-2/4: execute the installed JS with a small synthetic DOM.

    The marker-delimited block owns ccRenderPlatformResources(payload) and
    ccLoadPlatformResources(). Its DOM boundary is data-platform-resources=id.
    """
    def run_js(self, action):
        import json
        import shutil
        import subprocess
        html = DASHBOARD_PATH.read_text(encoding="utf-8")
        match = re.search(r"// ── Platform resources ──([\s\S]*?)// ── End Platform resources ──", html)
        self.assertIsNotNone(match, "RED: installed UI lacks owner resource load/render boundary")
        node = shutil.which("node") or str(Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node")
        self.assertTrue(Path(node).exists(), "Node runtime required for real browser-function tests")
        setup = r'''
const vm = require('vm');
const esc = text => String(text).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
class Node {
  constructor(tag='div') { this.tagName=tag; this.children=[]; this.dataset={}; this.attrs={}; this._html=''; this.hidden=false; this.className=''; }
  set textContent(text) { this._html=esc(text); this.children=[]; }
  get textContent() { return this._html + this.children.map(x=>x.textContent).join(''); }
  set innerHTML(html) { this._html=html; this.children=[]; }
  get innerHTML() { return this._html + this.children.map(x=>x.outerHTML).join(''); }
  get outerHTML() { const a={...this.attrs}; for(const k of ['href','target','rel','className']) if(this[k]) a[k==='className'?'class':k]=this[k]; return '<'+this.tagName+Object.entries(a).map(([k,v])=>' '+k+'="'+esc(v)+'"').join('')+'>'+this.innerHTML+'</'+this.tagName+'>'; }
  appendChild(node) { this.children.push(node); return node; }
  append(...nodes) { nodes.forEach(n=>this.appendChild(typeof n==='string'?Object.assign(new Node('span'),{textContent:n}):n)); }
  replaceChildren(...nodes) { this._html=''; this.children=[]; this.append(...nodes); }
  setAttribute(k,v) { this.attrs[k]=v; }
  getAttribute(k) { if(k==='data-platform-resources') return this.dataset.platformResources; return this.attrs[k]; }
  addEventListener() {}
  querySelector() { return this.area || null; }
}
const ids=['financial','mydictionary','health','ai-singularity','context-news','accountable','jarvis','property-os','pixel-agents','closeness-mirror','sushi-parisien','n8n'];
const areas=ids.map(id=>{ const n=new Node(); n.dataset.platformResources=id; return n; });
const cards=ids.map((id,i)=>{ const n=new Node('article'); n.dataset.platformId=id; n.area=areas[i]; return n; });
const byId={};
const document={hidden:false,createElement:t=>new Node(t),createTextNode:t=>Object.assign(new Node('span'),{textContent:t}),
  querySelectorAll:s=>s.includes('platform-entry')?cards:areas,
  querySelector:s=>{const i=ids.findIndex(id=>s.includes('"'+id+'"'));return i>=0?areas[i]:null;},
  getElementById:id=>byId[id]||(byId[id]=new Node()),addEventListener(){}};
let responseMode='good'; const fetchCalls=[];
const good={state:'ready',verified_at:'2026-10-19T16:00:00Z',platforms:{financial:{resources:[
  {kind:'code',scope:'current',label:'Synthetic source',url:'https://github.com/example/navigation-fixture'},
  {kind:'documents',scope:'archive',label:'Archive fixture',url:'https://drive.google.com/drive/folders/fixture-archive'},
  {kind:'code',scope:'upstream',label:'Upstream fixture',url:'https://github.com/example/upstream-fixture'},
  {kind:'notes',scope:'reference',label:'Reference fixture',url:'https://github.com/example/reference-fixture'}]}}};
const context={document, URL, URLSearchParams,Intl,Date, console, setTimeout:()=>0,clearTimeout(){},setInterval:()=>0,
  IS_FILE_DASHBOARD:false,DASHBOARD_API:'https://command.meshly.fr',IS_PUBLIC_DASHBOARD:true,
  window:{location:new URL('https://command.meshly.fr/'),addEventListener(){}},
  mmEsc:esc,mmHeaders:()=>({'X-Dashboard-Run-Token':'synthetic-owner-token'}),jarvisRunHeaders:()=>({'X-Dashboard-Run-Token':'synthetic-owner-token'}),
  fetch:async(url,options)=>{fetchCalls.push({url,options});if(responseMode==='network')throw Error('synthetic failure');return {ok:responseMode!=='unauthorized',status:responseMode==='unauthorized'?401:200,json:async()=>responseMode==='good'?good:{state:'owner_required',verified_at:null,platforms:{}}};}};
vm.createContext(context);
'''
        script = setup + "\nvm.runInContext(" + json.dumps(match.group(1)) + ", context);\n" + action
        run = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=15)
        self.assertEqual(run.returncode, 0, run.stderr)
        return json.loads(run.stdout)

    def test_ac_4_owner_cards_render_scopes_and_honest_not_linked_state(self):
        out = self.run_js("context.ccRenderPlatformResources(good);process.stdout.write(JSON.stringify(areas.map(n=>n.innerHTML)));")
        self.assertIn('https://github.com/example/navigation-fixture', out[0])
        self.assertIn('Synthetic source', out[0])
        for word in ('Архив', 'Исходный', 'Справ'):
            self.assertIn(word.lower(), out[0].lower())
        self.assertRegex(out[1], r'(?i)не подключ|не привязан|нет ссыл')
        self.assertNotRegex(out[0], r'<a[^>]+onclick=')
        for anchor in re.findall(r'<a\b[^>]*>', out[0]):
            self.assertIn('target="_blank"', anchor)
            self.assertIn('noopener', anchor)
            self.assertIn('noreferrer', anchor)

    def test_materials_disclosure_preserves_every_link_and_starts_collapsed(self):
        out = self.run_js("context.ccRenderPlatformResources(good);process.stdout.write(JSON.stringify(areas.map(n=>n.innerHTML)));")
        # Mark 2026-10-24: no counters, the disclosure just says what it holds.
        self.assertIn('<details><summary>Материалы проекта</summary>', out[0])
        self.assertNotRegex(out[0], r'<details[^>]+open')
        self.assertEqual(len(re.findall(r'<a\b', out[0])), 4)
        self.assertNotIn('<details', out[1], 'Empty cards must not offer an empty disclosure')

    def test_ec_2_label_and_note_markup_render_as_text(self):
        out = self.run_js(r'''
good.platforms.financial.resources[0].label='<img src=x onerror=alert(1)>Label';
good.platforms.financial.note='<script>alert(2)</script>';
context.ccRenderPlatformResources(good);
process.stdout.write(JSON.stringify(areas[0].innerHTML));''')
        self.assertNotIn('<img', out)
        self.assertNotIn('<script', out)
        self.assertIn('&lt;img', out)
        self.assertIn('&lt;script', out)

    def test_ac_4_ec_4_fetch_uses_owner_headers_and_failure_clears_private_links(self):
        out = self.run_js(r'''
(async()=>{await context.ccLoadPlatformResources();const success=areas[0].innerHTML;
responseMode='network';await context.ccLoadPlatformResources();const failed=areas[0].innerHTML;
responseMode='good';await context.ccLoadPlatformResources();responseMode='unauthorized';await context.ccLoadPlatformResources();
process.stdout.write(JSON.stringify({success,failed,denied:areas[0].innerHTML,calls:fetchCalls}));})().catch(e=>{console.error(e);process.exit(1)});''')
        self.assertIn('https://github.com/example/navigation-fixture', out['success'])
        for state in ('failed', 'denied'):
            self.assertNotIn('https://github.com/example/navigation-fixture', out[state])
            self.assertNotIn('Synthetic source', out[state])
            self.assertTrue(out[state].strip(), 'Readable failure/auth state required')
        for call in out['calls']:
            self.assertTrue(call['url'].endswith('/api/platform-resources'))
            self.assertEqual(call['options'].get('cache'), 'no-store')
            self.assertEqual(call['options'].get('headers', {}).get('X-Dashboard-Run-Token'), 'synthetic-owner-token')

    def test_ac_4_auth_loss_without_network_error_clears_private_links(self):
        out = self.run_js(r'''
context.ccRenderPlatformResources(good);context.ccRenderPlatformResources({state:'owner_required',verified_at:null,platforms:{}});
process.stdout.write(JSON.stringify(areas.map(n=>n.innerHTML)));''')
        self.assertNotIn('https://github.com/example/navigation-fixture', ''.join(out))
        self.assertTrue(all(s.strip() for s in out))


    def test_ac_4_ec_4_delayed_old_success_cannot_restore_links_after_newer_denial(self):
        out = self.run_js(r'''
(async()=>{const pending=[];context.fetch=(url,options)=>new Promise(resolve=>pending.push(resolve));
const old=context.ccLoadPlatformResources();const fresh=context.ccLoadPlatformResources();
if(pending.length<2){process.stdout.write(JSON.stringify({requests:pending.length}));return;}
pending[1]({ok:false,status:401,json:async()=>({state:'owner_required',verified_at:null,platforms:{}})});await fresh;
const denied=areas[0].innerHTML;
pending[0]({ok:true,status:200,json:async()=>good});await old;
process.stdout.write(JSON.stringify({requests:pending.length,denied,after:areas[0].innerHTML}));})().catch(e=>{console.error(e);process.exit(1)});''')
        self.assertEqual(out['requests'], 2, 'New access check must supersede pending older response')
        self.assertNotIn('https://github.com/example/navigation-fixture', out['after'])
        self.assertEqual(out['after'], out['denied'])

    def test_ec_2_client_rejects_unsafe_hrefs_independently_of_server(self):
        out = self.run_js(r'''
const unsafe=['javascript:alert(1)','file:///fixture','http://github.com/example/repo','https://127.0.0.1/',
'https://github.com.evil.invalid/','https://user:password@github.com/example/repo','https://github.com:bad/repo',
'https://github.com:8443/repo','https://github.com/repo?','https://github.com/repo#','https://github.com\\evil/repo',
'https://github.com/repo%0a','https://github.com/repo%5c',' https://github.com/example/repo','https://github.com/example/repo '];
const results=unsafe.map(url=>{const payload=JSON.parse(JSON.stringify(good));payload.platforms.financial.resources=[
{kind:'code',scope:'current',label:'Invalid URL fixture',url},good.platforms.financial.resources[0]];
context.ccRenderPlatformResources(payload);return areas[0].innerHTML;});
process.stdout.write(JSON.stringify(results));''')
        for html in out:
            with self.subTest(html=html):
                parser = _CommandCenterParser()
                links = re.findall(r'<a\b[^>]*href="([^"]*)"', html)
                self.assertEqual(links, ['https://github.com/example/navigation-fixture'])


if __name__ == "__main__":
    unittest.main()
