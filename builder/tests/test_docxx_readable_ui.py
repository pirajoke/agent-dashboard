"""Render the actual card function with synthetic owner data and a minimal DOM."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

HTML = Path(__file__).resolve().parents[1] / 'mac-mini-dashboard/index.html'


def function(source, name):
    marker = 'function ' + name + '('
    if marker not in source:
        return ''
    block = source[source.index(marker):]
    first = block.splitlines()[0]
    return first if first.endswith('}') else block[:block.index('\n}') + 2]


@unittest.skipUnless(shutil.which('node'), 'Node required for actual UI rendering')
class ReadableRecordUITests(unittest.TestCase):
    def test_collapsed_card_exposes_context_date_and_safe_source_link(self):
        source = HTML.read_text()
        functions = '\n'.join(function(source, name) for name in (
            'ccDocxxEl', 'ccDocxxSafeLink', 'ccDocxxLink', 'ccDocxxSourceLink',
            'ccDocxxShortDate', 'ccDocxxRecordDate', 'ccDocxxDate', 'ccDocxxRenderRecords',
            'ccDocxxText', 'ccDocxxCount', 'ccDocxxPick', 'ccDocxxRecordActions', 'ccDocxxSortBar'))
        script = '''const assert=require('node:assert/strict');
class E { constructor(tag){this.tag=tag;this.children=[];this.dataset={};this.value='';this.textContent='';}
append(...xs){this.children.push(...xs)} replaceChildren(){this.children=[]} setAttribute(k,v){this[k]=v} querySelectorAll(){return []} addEventListener(){}}
const list=new E('div'), search=new E('input');
const document={createElement:t=>new E(t),getElementById:id=>id==='docxx-records'?list:search};
const flatten=e=>e.textContent+' '+e.children.map(flatten).join(' ');
const ccDocxxAttention=new Set(['needs_review']); let ccDocxxRecordsSignature=null,ccDocxxFilter='all';
const ccDocxxSelected=new Set(); let ccDocxxSortVisible=[],ccDocxxFolders=null,ccDocxxBusy=false;
let ccDocxxData={records:[{key:'one',name:'Ticket — Médiathèque',original_name:'scan.pdf',source:'gmail',status:'needs_review',label:'Нужен разбор',at:'2026-10-24T09:54:16Z',date_kind:'added',description:'Доступ к компьютерам библиотеки.',valid_from:'2026-10-24',valid_until:'2027-10-24',source_url:'https://mail.google.com/mail/#all/0123456789abcdef'}]};
''' + functions + '''
ccDocxxRenderRecords();
const summary=list.children[0].children[0];
assert.match(flatten(summary),/Доступ к компьютерам/);
assert.match(flatten(summary),/Добавлен/);
assert.match(flatten(summary),/2026/);
assert.ok(summary.children.some(x=>x.tag==='a' && x.href==='https://mail.google.com/mail/#all/0123456789abcdef'));
assert.match(flatten(summary),/2027/);
for(const u of ['javascript:alert(1)','https://mail.google.com.evil.test/mail/#all/0123456789abcdef','https://mail.google.com/mail/?token=x#all/0123456789abcdef']) assert.equal(ccDocxxSourceLink('Open',u),null);
ccDocxxData={records:[{key:'two',name:'unknown.pdf',source:'gmail',status:'needs_review',label:'Нужен разбор'}]};
ccDocxxRenderRecords(); assert.match(flatten(list.children[0].children[0]),/Дата не указана/);
assert.match(flatten(list.children[0].children[0]),/Содержимое ещё не определено/);
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
