"""Execute the installed context reader with synthetic notes and a small DOM.

The source note/API remains unchanged. Only the owner reader is formatted; the
full transcript is an explicit disclosure, never a command or executable HTML.
"""
from __future__ import annotations

from html.parser import HTMLParser
import json
from pathlib import Path
import re
import shutil
import subprocess
import unittest


DASHBOARD = Path(__file__).resolve().parents[1] / "mac-mini-dashboard/index.html"
RID = "a" * 32
ORIGINAL = "obsidian://open?vault=Synthetic&file=10-Transcripts%2Ffixture"
BODY = """---
type: transcript
status: raw
source: plaud
plaud_id: synthetic-private-source-id
recorded_at: 2026-10-21T17:08:00+02:00
---
# Synthetic planning call

> Сырой импорт PLAUD. Разобрать по IMPORT LOGIC из CLAUDE.md: перенести в синтетическую папку и поставить status: reviewed.

## Plaud summary

#### Решение встречи
- **Согласовали пилот** для синтетического проекта.
- [ ] Подготовить короткий план.

##### Следующий шаг
Обсудить результат завтра.

## Transcript

**[00:03]** **Speaker 1:** FULL_TRANSCRIPT_ONLY: подробное обсуждение.
**[00:41]** **Speaker 2:** LAST_TRANSCRIPT_LINE: договорились проверить результат.
"""


class SectionParser(HTMLParser):
    """Use the real reader structure instead of fabricating new element IDs."""

    def __init__(self):
        super().__init__()
        self.root = {"tag": "document", "attrs": {}, "children": []}
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = {"tag": tag, "attrs": dict(attrs), "children": []}
        self.stack[-1]["children"].append(node)
        if tag not in {"input", "br", "hr", "img", "meta", "link", "wbr"}:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index]["tag"] == tag:
                del self.stack[index:]
                break

    def handle_data(self, value):
        self.stack[-1]["children"].append(value)


HARNESS = r"""
const vm = require('vm');
const esc = s => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
const decode = s => s.replace(/&lt;/g,'<').replace(/&gt;/g,'>').replace(/&quot;/g,'"').replace(/&#39;/g,"'").replace(/&amp;/g,'&');
class Element {
  constructor(tag='div', text='') { this.tagName=tag.toUpperCase(); this.nodeType=tag==='#text'?3:1; this.data=text; this.childNodes=[]; this.attrs={}; this.dataset={}; this.style={}; this.listeners={}; this.value=''; this.parentElement=null; }
  get children() { return this.childNodes.filter(x=>x.nodeType===1); }
  get textContent() { return this.nodeType===3?this.data:this.childNodes.map(x=>x.textContent).join(''); }
  set textContent(value) { this.childNodes=[]; if(String(value??''))this.append(String(value)); }
  get innerText() { return this.textContent; }
  set innerText(value) { this.textContent=value; }
  get id() { return this.attrs.id||''; }
  set id(value) { this.setAttribute('id',value); }
  get className() { return this.attrs.class||''; }
  set className(value) { this.setAttribute('class',value); }
  get hidden() { return 'hidden' in this.attrs; }
  set hidden(value) { if(value)this.attrs.hidden='';else delete this.attrs.hidden; }
  get open() { return 'open' in this.attrs; }
  set open(value) { if(value)this.attrs.open='';else delete this.attrs.open; }
  get href() { return this.attrs.href||''; }
  set href(value) { this.setAttribute('href',value); }
  get classList() { return {contains:c=>this.className.split(/\s+/).includes(c),add:(...cs)=>{this.className=[...new Set([...this.className.split(/\s+/),...cs])].filter(Boolean).join(' ');},remove:(...cs)=>{this.className=this.className.split(/\s+/).filter(c=>!cs.includes(c)).join(' ');}}; }
  setAttribute(key,value) { this.attrs[key]=String(value??''); if(key.startsWith('data-'))this.dataset[key.slice(5).replace(/-([a-z])/g,(_,c)=>c.toUpperCase())]=String(value??''); }
  getAttribute(key) { return key in this.attrs?this.attrs[key]:null; }
  hasAttribute(key) { return key in this.attrs; }
  removeAttribute(key) { delete this.attrs[key]; }
  appendChild(node) { if(node.parentElement)node.remove(); node.parentElement=this; this.childNodes.push(node); return node; }
  append(...nodes) { nodes.forEach(n=>this.appendChild(typeof n==='string'?new Element('#text',n):n)); }
  replaceChildren(...nodes) { this.childNodes.forEach(n=>n.parentElement=null); this.childNodes=[]; this.append(...nodes); }
  remove() { if(this.parentElement)this.parentElement.childNodes=this.parentElement.childNodes.filter(n=>n!==this);this.parentElement=null; }
  addEventListener(name,fn) { (this.listeners[name]||=[]).push(fn); }
  dispatchEvent(event) { event.target ||= this; for(const fn of this.listeners[event.type]||[])fn(event); }
  click() { if(this.tagName==='SUMMARY'){const d=this.closest('details');if(d)d.open=!d.open;}this.dispatchEvent({type:'click',preventDefault(){}}); }
  focus() { document.activeElement=this; }
  matches(selector) { return selector.split(',').some(part=>{let s=part.trim();const attr=[...s.matchAll(/\[([^\]=]+)(?:=["']?([^\]"']*)["']?)?\]/g)];s=s.replace(/\[[^\]]+\]/g,'');if(attr.some(([,k,v])=>!this.hasAttribute(k)||(v!==undefined&&this.getAttribute(k)!==v)))return false;const id=s.match(/#([\w-]+)/);if(id&&this.id!==id[1])return false;const classes=[...s.matchAll(/\.([\w-]+)/g)].map(x=>x[1]);if(classes.some(c=>!this.classList.contains(c)))return false;const tag=s.match(/^[\w-]+/);return !tag||this.tagName===tag[0].toUpperCase();}); }
  closest(selector) { for(let n=this;n;n=n.parentElement)if(n.matches(selector))return n;return null; }
  querySelectorAll(selector) { const out=[];for(const n of this.children){if(n.matches(selector))out.push(n);out.push(...n.querySelectorAll(selector));}return out; }
  querySelector(selector) { return this.querySelectorAll(selector)[0]||null; }
  get innerHTML() { return this.childNodes.map(n=>n.outerHTML).join(''); }
  set innerHTML(value) {
    this.replaceChildren(); const stack=[this];
    for(const chunk of String(value).match(/<[^>]*>|[^<]+|</g)||[]) {
      if(chunk.startsWith('</')){if(stack.length>1)stack.pop();continue;}
      const start=chunk.match(/^<([a-z][\w:-]*)\b([^>]*)>/i);
      if(!start){stack.at(-1).append(decode(chunk));continue;}
      const n=new Element(start[1]);
      for(const a of start[2].matchAll(/([^\s=]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?/g))n.setAttribute(a[1],decode(a[2]??a[3]??a[4]??''));
      stack.at(-1).append(n);if(!['BR','HR','IMG','INPUT','WBR'].includes(n.tagName))stack.push(n);
    }
  }
  get outerHTML() { return this.nodeType===3?esc(this.data):'<'+this.tagName.toLowerCase()+Object.entries(this.attrs).map(([k,v])=>' '+k+'="'+esc(v)+'"').join('')+'>'+this.innerHTML+'</'+this.tagName.toLowerCase()+'>'; }
}
function build(spec) { if(typeof spec==='string')return new Element('#text',spec);const n=new Element(spec.tag);Object.entries(spec.attrs).forEach(([k,v])=>n.setAttribute(k,v));spec.children.forEach(c=>n.append(build(c)));return n; }
const root=build(__TREE__);
const document={hidden:false,activeElement:null,listeners:{},createElement:t=>new Element(t),createTextNode:t=>new Element('#text',String(t)),createDocumentFragment:()=>new Element('fragment'),getElementById:id=>root.querySelector('#'+id),querySelector:s=>root.querySelector(s),querySelectorAll:s=>root.querySelectorAll(s),addEventListener:Element.prototype.addEventListener,dispatchEvent:Element.prototype.dispatchEvent};
document.getElementById('section-context').classList.add('active');
const window={listeners:{},addEventListener:Element.prototype.addEventListener,dispatchEvent:Element.prototype.dispatchEvent};
const reader=()=>document.getElementById('context-reader');
function visibleText(n) { if(n.hidden||n.style.display==='none')return '';if(n.nodeType===3)return n.data;if(n.tagName==='DETAILS'&&!n.open)return n.children.filter(c=>c.tagName==='SUMMARY').map(visibleText).join('');return n.childNodes.map(visibleText).join(''); }
const body=__BODY__;
const good={state:'ready',generated_at:'2026-10-23T07:00:00Z',record:{id:'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',source:'plaud',kind:'transcript',title:'Synthetic planning call',date:'2026-10-21',modified_at:'2026-10-22T07:00:00Z',obsidian_url:'obsidian://open?vault=Synthetic&file=10-Transcripts%2Ffixture',body}};
const originalPayload=JSON.stringify(good);
let responseMode='good';const fetchCalls=[];let storageWrites=0;
const context={document,window,URL,URLSearchParams,Intl,Date,AbortController,console,IS_FILE_DASHBOARD:false,DASHBOARD_API:'https://synthetic.invalid',JARVIS_RUN_TOKEN_KEY:'fixture-key',setTimeout:()=>0,clearTimeout(){},setInterval:()=>0,localStorage:{setItem(){storageWrites++;}},sessionStorage:{setItem(){storageWrites++;}},jarvisRunHeaders:()=>({'X-Dashboard-Run-Token':'synthetic-owner'}),fetch:async(url,options)=>{fetchCalls.push({url,options});return {ok:responseMode!=='denied',status:responseMode==='denied'?401:200,json:async()=>responseMode==='good'?good:{state:'owner_required'}};}};
vm.createContext(context);vm.runInContext(__CODE__,context);
const snapshot=()=>({visible:visibleText(reader()),all:reader().textContent,html:reader().innerHTML,hidden:reader().hidden,href:document.getElementById('context-obsidian').getAttribute('href'),details:reader().querySelectorAll('details').map(n=>({open:n.open,text:n.textContent,label:n.querySelector('summary')?.textContent||''})),headings:reader().querySelectorAll('h1,h2,h3,h4,h5,h6').map(n=>n.textContent),bullets:reader().querySelectorAll('li').map(n=>n.textContent),tags:reader().querySelectorAll('*').map(n=>({tag:n.tagName,attrs:n.attrs})),storageWrites,calls:fetchCalls,payloadUnchanged:JSON.stringify(good)===originalPayload});
"""


class ContextReaderBrowserTests(unittest.TestCase):
    def run_js(self, action, body=BODY):
        html = DASHBOARD.read_text(encoding="utf-8")
        section = re.search(r'<section id="section-context"[\s\S]*?</section>', html)
        code = re.search(r'// Private context is kept only in the active DOM,[\s\S]*?(?=// ── Platform edits)', html)
        self.assertIsNotNone(section, "Installed context section required")
        self.assertIsNotNone(code, "Installed context reader entry point required")
        parser = SectionParser()
        parser.feed(section.group(0))
        setup = HARNESS.replace("__TREE__", json.dumps(parser.root)).replace("__BODY__", json.dumps(body)).replace("__CODE__", json.dumps(code.group(0)))
        node = shutil.which("node") or str(Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node")
        self.assertTrue(Path(node).exists(), "Node runtime is required")
        run = subprocess.run([node, "-e", setup + "\n(async()=>{" + action + "})().catch(e=>{console.error(e);process.exit(1)});"], capture_output=True, text=True, timeout=15)
        self.assertEqual(run.returncode, 0, run.stderr)
        return json.loads(run.stdout)

    def load(self, body=BODY):
        return self.run_js("await context.ccLoadContext(good.record.id);process.stdout.write(JSON.stringify(snapshot()));", body)

    def test_summary_is_readable_first_without_import_metadata(self):
        out = self.load()
        self.assertIn("Согласовали пилот", out["visible"])
        for technical in ("plaud_id", "synthetic-private-source-id", "Сырой импорт", "IMPORT LOGIC", "status: raw", "FULL_TRANSCRIPT_ONLY"):
            self.assertNotIn(technical, out["visible"], "Reader must show the useful summary before technical/raw content")
        self.assertIn("Решение встречи", out["headings"])
        self.assertTrue(any("Согласовали пилот" in bullet for bullet in out["bullets"]), "Summary bullets must render as list items")
        self.assertNotIn("####", out["visible"])
        self.assertNotIn("**Согласовали", out["visible"])

    def test_complete_transcript_requires_explicit_native_disclosure(self):
        out = self.run_js("""
await context.ccLoadContext(good.record.id);const before=snapshot();
const disclosure=reader().querySelectorAll('details').find(n=>n.textContent.includes('FULL_TRANSCRIPT_ONLY'));
if(disclosure)disclosure.querySelector('summary')?.click();
process.stdout.write(JSON.stringify({before,after:snapshot(),found:!!disclosure}));
""")
        self.assertTrue(out["found"], "The full transcript needs a keyboard-accessible deliberate disclosure")
        self.assertNotIn("FULL_TRANSCRIPT_ONLY", out["before"]["visible"])
        self.assertTrue(all(not d["open"] for d in out["before"]["details"]))
        self.assertIn("FULL_TRANSCRIPT_ONLY", out["after"]["visible"])
        self.assertIn("LAST_TRANSCRIPT_LINE", out["after"]["visible"])
        self.assertEqual(out["after"]["href"], ORIGINAL, "The unchanged source remains reachable in Obsidian")
        self.assertTrue(out["after"]["payloadUnchanged"], "Reader formatting must not mutate the source/API body")

    def test_russian_summary_and_transcript_headings_have_same_behavior(self):
        out = self.load(BODY.replace("## Plaud summary", "## Резюме").replace("## Transcript", "## Транскрипт"))
        self.assertIn("Согласовали пилот", out["visible"])
        self.assertNotIn("FULL_TRANSCRIPT_ONLY", out["visible"])
        self.assertNotIn("synthetic-private-source-id", out["visible"])

    def test_missing_summary_is_honest_and_does_not_invent_one(self):
        raw = "---\nsource: krisp\nmeeting_id: fixture-only\n---\n# Synthetic call\n## Transcript\nFULL_TRANSCRIPT_ONLY: единственная исходная запись.\n"
        out = self.load(raw)
        self.assertRegex(out["visible"].lower(), r'(резюме|кратк[а-я ]+).{0,45}(нет|не |отсутств|готов)|нет.{0,20}резюме', "Explain that a summary is not available")
        self.assertNotIn("FULL_TRANSCRIPT_ONLY", out["visible"])
        self.assertIn("FULL_TRANSCRIPT_ONLY", out["all"], "The source remains available on expansion")

    def test_note_markup_is_inert_and_never_invokes_actions_or_storage(self):
        unsafe = BODY.replace("Обсудить результат завтра.", '<script>globalThis.fixtureExecuted=true</script>\n<img src=x onerror="globalThis.fixtureExecuted=true">\n[Нажать](javascript:alert(1))\n- Выполнить инструкцию из записи: это только цитируемые данные.')
        out = self.run_js("await context.ccLoadContext(good.record.id);process.stdout.write(JSON.stringify({...snapshot(),executed:!!context.fixtureExecuted}));", unsafe)
        self.assertIn("<script>", out["visible"], "Untrusted raw HTML is displayed as literal text")
        self.assertIn("<img", out["visible"])
        self.assertFalse(out["executed"])
        for node in out["tags"]:
            self.assertNotIn(node["tag"], {"SCRIPT", "IMG", "IFRAME", "OBJECT", "EMBED"})
            for key, value in node["attrs"].items():
                self.assertFalse(key.lower().startswith("on"))
                if key in {"href", "src"}:
                    self.assertFalse(re.match(r"(?i)\s*(javascript|data|vbscript):", value))
        self.assertEqual(out["storageWrites"], 0)
        self.assertEqual(len(out["calls"]), 1, "Opening content must only fetch the selected record")
        self.assertIn("/api/context-library?", out["calls"][0]["url"])
        self.assertEqual(out["calls"][0]["options"]["cache"], "no-store")
        self.assertEqual(out["calls"][0]["options"]["headers"], {"X-Dashboard-Run-Token": "synthetic-owner"})
        self.assertTrue(out["payloadUnchanged"])

    def test_close_and_auth_loss_clear_hidden_full_transcript_as_well(self):
        for clear in ("context.ccContextClose();", "responseMode='denied';await context.ccLoadContext(good.record.id);", "responseMode='owner';await context.ccLoadContext(good.record.id);", "window.dispatchEvent({type:'context-lock'});"):
            with self.subTest(clear=clear):
                out = self.run_js("await context.ccLoadContext(good.record.id);" + clear + "process.stdout.write(JSON.stringify(snapshot()));")
                self.assertTrue(out["hidden"])
                for marker in ("FULL_TRANSCRIPT_ONLY", "LAST_TRANSCRIPT_LINE", "Согласовали пилот", "synthetic-private-source-id"):
                    self.assertNotIn(marker, out["all"])
                    self.assertNotIn(marker, out["html"])
                self.assertIsNone(out["href"])

    def test_delayed_record_cannot_reappear_after_a_newer_auth_failure(self):
        out = self.run_js("""
const pending=[];context.fetch=()=>new Promise(resolve=>pending.push(resolve));
const old=context.ccLoadContext(good.record.id);const latest=context.ccLoadContext(good.record.id);
pending[1]({ok:false,status:401});await latest;
pending[0]({ok:true,status:200,json:async()=>good});await old;
process.stdout.write(JSON.stringify(snapshot()));
""")
        self.assertTrue(out["hidden"])
        self.assertNotIn("FULL_TRANSCRIPT_ONLY", out["html"])
        self.assertNotIn("Согласовали пилот", out["html"])
        self.assertIsNone(out["href"])

    def test_quotes_emphasis_and_checklists_remain_read_only_source_text(self):
        out = self.load(BODY.replace("Обсудить результат завтра.", "> **Рекомендация**\n> Обсудить с *Максом*.\n\n- [x] Отметка из исходной заметки.\n- [ ] План из исходной заметки."))
        self.assertIn("<blockquote>", out["html"])
        self.assertIn("<em>Максом</em>", out["html"])
        self.assertNotIn("*Максом*", out["visible"])
        self.assertNotIn("&gt;", out["html"])
        self.assertNotIn('type="checkbox"', out["html"], "A note checklist is not a task-status control")
        self.assertEqual(len(out["calls"]), 1)

    def test_source_work_links_are_clickable_deduplicated_and_not_fabricated(self):
        text = """[Проверить задачу](https://github.com/example/context-fixture/issues/23)
https://github.com/example/context-fixture/issues/23.
[Правка](https://github.com/example/context-fixture/pull/24)
[Доска](https://www.notion.so/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa?v=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb)
[Карточка](https://linear.app/fixture/issue/CTX-12/summary)
"""
        out = self.run_js("await context.ccLoadContext(good.record.id);const area=document.getElementById('context-links');process.stdout.write(JSON.stringify({...snapshot(),links:area.querySelectorAll('a').map(a=>a.attrs),relatedHidden:area.hidden}));", BODY.replace("Обсудить результат завтра.", text))
        self.assertFalse(out["relatedHidden"])
        self.assertEqual(len(out["links"]), 4)
        self.assertEqual(out["links"][0]["href"], "https://github.com/example/context-fixture/issues/23")
        for link in out["links"]:
            self.assertEqual(link["target"], "_blank")
            self.assertEqual(link["rel"], "noopener noreferrer")
        self.assertEqual(len(out["calls"]), 1, "Viewing source links must not fetch other services or create tasks")
        self.assertTrue(out["payloadUnchanged"])
        self.assertEqual(out["storageWrites"], 0)
        self.assertIn('id="context-work" href="?tab=work&amp;view=todo"', out["html"])
        self.assertIn('id="context-agents" href="?tab=agents"', out["html"])

    def test_no_task_links_are_inferred_and_examples_are_not_task_relationships(self):
        text = """Нужно создать задачу #123 и поручить агенту.
`https://github.com/example/context-fixture/issues/25`
```markdown
https://github.com/example/context-fixture/issues/26
```
[Небезопасно](javascript:alert(1))
[Поддельный домен](https://github.com.evil.invalid/a/b/issues/1)
[Доступ](https://owner:secret@github.com/a/b/issues/1)
[Команда](https://github.com/a/b/issues/1?run=true)
[Смена маршрута](https://github.com/a/b/../issues/1)
"""
        out = self.run_js("await context.ccLoadContext(good.record.id);process.stdout.write(JSON.stringify({...snapshot(),relatedHidden:document.getElementById('context-links').hidden,links:document.getElementById('context-body').querySelectorAll('a').map(a=>a.attrs)}));", BODY.replace("Обсудить результат завтра.", text))
        self.assertTrue(out["relatedHidden"])
        self.assertEqual(out["links"], [])
        self.assertIn("Нужно создать задачу #123", out["visible"])
        self.assertEqual(len(out["calls"]), 1)

    def test_private_work_links_disappear_after_close_and_access_loss(self):
        body = BODY.replace("Обсудить результат завтра.", "[Задача](https://github.com/example/private-context/issues/7)")
        for clear in ("context.ccContextClose();", "responseMode='denied';await context.ccLoadContext(good.record.id);", "window.dispatchEvent({type:'context-lock'});"):
            with self.subTest(clear=clear):
                out = self.run_js("await context.ccLoadContext(good.record.id);" + clear + "process.stdout.write(JSON.stringify({...snapshot(),relatedHidden:document.getElementById('context-links').hidden}));", body)
                self.assertNotIn("private-context", out["html"])
                self.assertTrue(out["relatedHidden"])


    def test_long_meeting_leads_with_short_summary_and_folds_topics(self):
        """Mark 2026-10-26: «много информации, много метаданных» on a long PLAUD summary."""
        body = """---
source: plaud
---
# 10-26 Synthetic platform audit

## 📝 Краткое резюме

[](plaud://image?type=summaryCard&id=oc_su_fixture_i1)

LEAD_PARAGRAPH: проверили продукт целиком. Нашли несколько ошибок.

---

**Онбординг и профиль**

TOPIC_ONE_FIRST: регистрация прошла заново. TOPIC_ONE_DETAIL: подсказки непонятные.

---

**Подбор вакансий**

TOPIC_TWO_FIRST: подбор работает. TOPIC_TWO_DETAIL: фильтр по городу сбоит.

**🎯 Следующие шаги**

- NEXT_STEP_ITEM: исправить подсказки.

## Transcript

FULL_TRANSCRIPT_ONLY
"""
        out = self.run_js("""
good.record.title='10-26 Synthetic platform audit';
await context.ccLoadContext(good.record.id);const before=snapshot();
const title=document.getElementById('context-reader-title').textContent;
const topics=reader().querySelectorAll('details').filter(d=>d.classList.contains('context-topic'));
topics.forEach(d=>d.querySelector('summary').click());
process.stdout.write(JSON.stringify({before,title,topicCount:topics.length,after:snapshot(),info:document.getElementById('context-info').dataset.ccInfo}));
""", body)
        visible = out["before"]["visible"]
        self.assertIn("Коротко", visible)
        self.assertIn("LEAD_PARAGRAPH", visible)
        self.assertLess(visible.index("LEAD_PARAGRAPH"), visible.index("NEXT_STEP_ITEM"), "The short summary comes first")
        self.assertLess(visible.index("NEXT_STEP_ITEM"), visible.index("Онбординг и профиль"), "Next steps stay open above the folded topics")
        self.assertEqual(out["topicCount"], 2)
        self.assertIn("TOPIC_ONE_FIRST", visible, "A folded topic shows its first sentence")
        self.assertNotIn("TOPIC_ONE_DETAIL", visible)
        self.assertIn("TOPIC_TWO_DETAIL", out["after"]["visible"])
        for noise in ("plaud://", "oc_su_fixture", "---", "📝", "🎯", "**", "PLAUD ·", "26 октября", "FULL_TRANSCRIPT_ONLY"):
            self.assertNotIn(noise, visible)
        self.assertNotIn("plaud://", out["before"]["html"])
        self.assertEqual(out["title"], "Synthetic platform audit", "The date prefix moves out of the title")
        self.assertEqual(out["info"], "context-record", "Source and date stay one tap away behind «i»")
        self.assertIn("Следующие шаги", out["before"]["headings"])

    def test_bold_statements_and_code_examples_are_not_split_into_sections(self):
        body = BODY.replace("## Plaud summary\n", "## Plaud summary\n\nВступление.\n\n**Запуск переносится на пятницу.**\n\n```markdown\n# Пример\nhttps://github.com/example/context-fixture/issues/26\n```\n\n")
        out = self.run_js("await context.ccLoadContext(good.record.id);process.stdout.write(JSON.stringify({...snapshot(),relatedHidden:document.getElementById('context-links').hidden}));", body)
        self.assertIn("Запуск переносится на пятницу.", out["visible"])
        self.assertIn("<pre>", out["html"])
        self.assertNotIn("Пример", out["headings"])
        self.assertTrue(out["relatedHidden"], "A URL inside a code example is not a work link")
        bold_only = "# Synthetic planning call\n## Plaud summary\n\nВступление.\n\n**Тема без текста**\n\n**Тема**\n\nТекст темы.\n\n**Запуск переносится на пятницу.**\n\n**Следующие шаги**\n\n- Сделать план.\n"
        out = self.run_js("await context.ccLoadContext(good.record.id);const d=reader().querySelectorAll('details');d.forEach(x=>x.querySelector('summary').click());process.stdout.write(JSON.stringify(snapshot()));", bold_only)
        self.assertIn("Запуск переносится на пятницу.", out["visible"], "A bold statement stays in the record")
        self.assertIn("Тема без текста", out["visible"], "A heading with nothing under it is not dropped")
        self.assertIn("Следующие шаги", out["headings"])

if __name__ == "__main__":
    unittest.main()
