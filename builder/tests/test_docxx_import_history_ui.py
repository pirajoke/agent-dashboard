"""User-visible import history renders context without a manual filing queue."""
import shutil
import subprocess
import unittest

from test_docxx_readable_ui import HTML, function


@unittest.skipUnless(shutil.which('node'), 'Node required for actual UI rendering')
class ImportHistoryUITests(unittest.TestCase):
    def run_dom(self, assertions):
        source = HTML.read_text()
        functions = '\n'.join(function(source, name) for name in (
            'ccDocxxEl', 'ccDocxxSafeLink', 'ccDocxxLink', 'ccDocxxSourceLink',
            'ccDocxxShortDate', 'ccDocxxFrom', 'ccDocxxFolder', 'ccDocxxRecordDate', 'ccDocxxDate', 'ccDocxxRenderRecords',
            'ccDocxxText', 'ccDocxxCount', 'ccDocxxPick', 'ccDocxxAct', 'ccDocxxMovable',
            'ccDocxxSuggested', 'ccDocxxFolderName', 'ccDocxxRecordActions',
            'ccDocxxGuessed', 'ccDocxxSortBar'))
        script = '''const assert=require('node:assert/strict');
class E { constructor(tag){this.tag=tag;this.children=[];this.dataset={};this.value='';this.textContent='';}
append(...xs){this.children.push(...xs)} replaceChildren(){this.children=[]} setAttribute(k,v){this[k]=v} querySelectorAll(){return []} addEventListener(){}}
const elements=new Map(); const document={createElement:t=>new E(t),getElementById:id=>{if(!elements.has(id))elements.set(id,new E('div'));return elements.get(id)}};
const list=document.getElementById('docxx-records');
const flatten=e=>typeof e==='string'?e:e.textContent+' '+e.children.map(flatten).join(' ');
const nodes=e=>typeof e==='string'?[]:[e,...e.children.flatMap(nodes)];
const ccDocxxAttention=new Set(['needs_review','error']); let ccDocxxRecordsSignature=null,ccDocxxFilter='all';
const ccDocxxSelected=new Set(); let ccDocxxSortVisible=[],ccDocxxPickable=[],ccDocxxFolders=null,ccDocxxBusy=false;
let ccDocxxData={records:[]};
''' + functions + assertions
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_completed_import_shows_name_location_date_and_source_without_mutation_controls(self):
        self.run_dom('''
ccDocxxData.records=[{key:'done',name:'Birth certificate — Example — RU-FR.pdf',original_name:'scan.pdf',source:'gmail',source_account:'owner@example.com',status:'verified',label:'Проверено',at:'2026-10-28T14:00:00Z',destination:'40 — Family/Grandparents/Example/Certificates',url:'https://drive.google.com/file/d/abcdefghijklmnop/view',source_url:'https://mail.google.com/mail/#all/0123456789abcdef'}];
ccDocxxRenderRecords(); const card=list.children[0], summary=card.children[0];
assert.match(flatten(summary),/Birth certificate — Example — RU-FR/);
assert.match(flatten(summary),/Example › Certificates/);
assert.match(flatten(card),/Family › Grandparents › Example › Certificates/);
assert.match(flatten(summary),/28/); assert.match(flatten(summary),/owner@example\.com/);
assert.ok(nodes(card).some(e=>e.tag==='a'&&e.href==='https://drive.google.com/file/d/abcdefghijklmnop/view'));
assert.ok(nodes(card).some(e=>e.tag==='a'&&e.href==='https://mail.google.com/mail/#all/0123456789abcdef'));
assert.equal(nodes(card).some(e=>e.role==='checkbox'),false);
assert.doesNotMatch(flatten(card),/Выбрать папку|Положить в|В архив|Оставить|Удалить|Вернуть как было/);
assert.equal(document.getElementById('docxx-sort-bar').hidden,true);
''')

    def test_unreadable_import_remains_an_exception_without_requesting_a_folder(self):
        self.run_dom('''
ccDocxxFolders={folders:['Family/Certificates'],archive:'Archive'};
ccDocxxData.records=[{key:'exception',name:'Unreadable scan.pdf',source:'gmail',status:'needs_review',label:'Нужен разбор',reason:'Не удалось прочитать страницы.',destination:'To review',at:'2026-10-28T14:01:00Z',suggest:{folder:'Family/Certificates',why:'неполный текст'}}];
ccDocxxRenderRecords(); const card=list.children[0];
assert.match(flatten(card),/Нужен разбор/); assert.match(flatten(card),/Не удалось прочитать страницы/);
assert.doesNotMatch(flatten(card),/Разобрано|Проверено|Выбрать папку|Положить в|В архив|Оставить|Удалить/);
assert.equal(nodes(card).some(e=>e.role==='checkbox'),false);
assert.ok(nodes(card).some(e=>e.dataset.tone==='attention'));
''')

    def test_history_preserves_link_safety_and_does_not_invent_missing_dates(self):
        self.run_dom('''
ccDocxxData.records=[{key:'bad',name:'Unknown.pdf',source:'drive',status:'pending',label:'В очереди',url:'javascript:alert(1)',source_url:'https://mail.google.com.evil.test/mail/#all/0123456789abcdef'}];
ccDocxxRenderRecords(); const card=list.children[0];
assert.equal(nodes(card).some(e=>e.tag==='a'),false);
assert.match(flatten(card),/В очереди/);
assert.doesNotMatch(flatten(card),/Invalid Date|NaN|1970|Проверено|Разобрано/);
''')
