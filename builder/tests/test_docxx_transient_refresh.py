"""Exercise real owner-view loading: temporary failure versus revoked access."""
from pathlib import Path
import shutil
import subprocess
import unittest

HTML = Path(__file__).resolve().parents[1] / 'mac-mini-dashboard/index.html'


@unittest.skipUnless(shutil.which('node'), 'Node required for actual UI loading')
class DocxxTransientRefreshTests(unittest.TestCase):
    def run_refresh(self, failure):
        source = HTML.read_text()
        source = source.split('// DOCXX owner view:', 1)[1]
        source = source[source.index('\nlet ccDocxxData'):]
        source = source.split('// Mark 2026-10-23: the explanation stays folded', 1)[0]
        setup = r'''
const assert = require('node:assert/strict');
class E {
  constructor(tag) { this.tag=tag; this.children=[]; this.dataset={}; this.value=''; this.textContent=''; this.hidden=false; }
  append(...xs) { this.children.push(...xs); }
  replaceChildren(...xs) { this.children=xs; this.textContent=''; }
  setAttribute(k,v) { this[k]=v; }
  removeAttribute(k) { delete this[k]; }
  querySelectorAll() { return []; }
}
const elements=new Map();
const document={hidden:false, createElement:t=>new E(t),
 getElementById:id=>{if(!elements.has(id))elements.set(id,new E('div'));return elements.get(id)},
 querySelector:()=>new E('section'), querySelectorAll:()=>[]};
const text=e=>e.textContent+' '+e.children.map(text).join(' ');
const ccInfoSources={}, DASHBOARD_API='', jarvisRunHeaders=()=>({});
const setTimeout=()=>1, clearTimeout=()=>{};
const good={state:'ready',checked_at:'2026-10-25T00:00:00Z',busy:false,records:[
 {key:'synthetic',name:'Synthetic retained document.pdf',source:'drive',status:'verified',label:'Проверено',at:'2026-10-25T00:00:00Z'}]};
let fetch=async()=>({ok:true,status:200,json:async()=>good});
'''
        assertions = r'''
(async()=>{
 await ccLoadDocxx();
 assert.match(text(document.getElementById('docxx-records')),/Synthetic retained document/);
 FAILURE
 await ccLoadDocxx();
 if(RETAIN) {
   assert.match(text(document.getElementById('docxx-records')),/Synthetic retained document/,
     'A transient refresh failure must preserve the last owner-authorized rows');
   assert.ok(ccDocxxData?.records?.length,'The retained snapshot must stay filterable');
   const status=text(document.getElementById('docxx-state'))+' '+text(document.getElementById('docxx-freshness'))+' '+text(document.getElementById('docxx-warnings'));
   assert.match(status,/последн|устар|сохранён|обновить|связи/i,'Retained rows need an explicit freshness warning');
   assert.ok(['stale','unavailable'].includes(document.getElementById('docxx-indicator').dataset.state),
     'A failed refresh must not continue to claim a healthy live snapshot');
 } else {
   assert.doesNotMatch(text(document.getElementById('docxx-records')),/Synthetic retained document/);
   assert.equal(ccDocxxData,null,'Revoked owner access must discard in-memory private data');
   assert.equal(document.getElementById('docxx-indicator').dataset.state,'owner_required');
 }
 assert.equal(document.getElementById('docxx-refresh').disabled,false);
})().catch(e=>{console.error(e);process.exitCode=1});
'''
        replacements = {
            'network': ("fetch=async()=>{throw new TypeError('Network unavailable')};", True),
            '401': ("fetch=async()=>({ok:false,status:401});", False),
            '403': ("fetch=async()=>({ok:false,status:403});", False),
            'owner_required': ("fetch=async()=>({ok:true,status:200,json:async()=>({state:'owner_required'})});", False),
        }
        code, retain = replacements[failure]
        script = setup + source + assertions.replace('FAILURE', code).replace('RETAIN', str(retain).lower())
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_transient_refresh_keeps_known_rows_and_marks_stale(self):
        self.run_refresh('network')

    def test_owner_access_loss_still_clears_private_rows(self):
        for failure in ('401', '403', 'owner_required'):
            with self.subTest(failure=failure):
                self.run_refresh(failure)
