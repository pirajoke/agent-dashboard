from __future__ import annotations
import fcntl, importlib.util, io, json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from dashboard_builder.docxx import docxx_projection, state_path, _safe_link, MAX_JSON
NOW=1792764000
BUILDER=Path(__file__).resolve().parents[1]
class ProjectionTests(unittest.TestCase):
 def setUp(self):
  t=tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup); self.root=Path(t.name)
  self.status={'checked_at':NOW-10,'phase':'ready','model_calls':0,'catalog':{'status':'ready','documents':42},'results':[],'drive_ingress':{'status':'idle','pending':0,'results':[]},'review_pending':[]}
  for n in ('journal.json','drive-ingress-journal.json','config.json'):self.write(n,{})
  (self.root/'runner.lock').touch()
 def write(self,n,d):(self.root/n).write_text(json.dumps(d))
 def read(self):
  self.write('status.json',self.status);return docxx_projection(self.root,owner=True,now=NOW)
 def test_anonymous_does_not_read(self):
  with patch('dashboard_builder.docxx._read',side_effect=AssertionError()):self.assertEqual(docxx_projection(self.root),{'state':'owner_required'})
 def test_fresh_ready_and_zero_is_known(self):
  d=self.read();self.assertEqual(d['state'],'ready');self.assertEqual(d['pending'],0);self.assertFalse(d['busy']);self.assertEqual(d['model_calls'],0)
 def test_real_lock_means_processing(self):
  with (self.root/'runner.lock').open('rb') as f:
   fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB);self.assertEqual(self.read()['state'],'processing')
 def test_stale_precedes_busy(self):
  self.status['checked_at']=NOW-1800
  with (self.root/'runner.lock').open('rb') as f:
   fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB);self.assertEqual(self.read()['state'],'stale')
 def test_bad_dates_not_healthy(self):
  for value in (None,'oops','2026-10-23T15:00:00',NOW+50,float('nan')):
   self.status['checked_at']=value;self.assertEqual(self.read()['state'],'stale')
 def test_missing_status(self):self.assertEqual(docxx_projection(self.root,owner=True)['state'],'unavailable')
 def test_symlink_and_oversize(self):
  other=self.root/'other';other.write_text('{}');(self.root/'status.json').symlink_to(other)
  self.assertEqual(docxx_projection(self.root,owner=True)['state'],'unavailable')
  (self.root/'status.json').unlink();(self.root/'status.json').write_bytes(b' '*(MAX_JSON+1))
  self.assertEqual(docxx_projection(self.root,owner=True)['state'],'unavailable')
 def test_unknown_queue_not_zero(self):
  del self.status['drive_ingress']['pending'];d=self.read();self.assertIsNone(d['pending']);self.assertNotEqual(d['state'],'ready')
 def test_queue_both_sources_and_attention(self):
  self.status['results']=[{'source':'scan.pdf','status':'settling'},{'source':'b.pdf','status':'needs_review'}];self.status['drive_ingress']['pending']=3
  d=self.read();self.assertEqual(d['pending'],4);self.assertEqual(d['review_count'],1);self.assertEqual(d['state'],'attention')
 def test_error_private_reason_not_leaked(self):
  self.status['catalog']={'status':'error','reason':'PRIVATE_TOKEN'};d=self.read();self.assertEqual(d['state'],'attention');self.assertNotIn('PRIVATE_TOKEN',json.dumps(d))
 def test_safe_history(self):
  self.write('drive-ingress-journal.json',{'key':{'id':'synthetic_document_1234','source':'/Users/secret/Inbox/scan.pdf','destination':'/Users/secret/DOCXXx/France/Passeport.pdf','status':'verified','at':'2026-10-22T12:00:00Z','text':'PRIVATE_CONTENT','before':{'token':'PRIVATE_TOKEN'}}})
  d=self.read();self.assertTrue(d['records'][0]['historical']);self.assertEqual(d['records'][0]['destination'],'France/Passeport.pdf')
  for p in ('/Users/secret','PRIVATE_CONTENT','PRIVATE_TOKEN'):self.assertNotIn(p,json.dumps(d))
 def test_pending_proof_not_success(self):
  self.status['results']=[{'source':'a.pdf','status':'copied','finalization':{'status':'pending'}}];d=self.read();self.assertEqual(d['records'][0]['status'],'awaiting_verification');self.assertEqual(d['state'],'attention')
 def test_malicious_links(self):
  self.status['results']=[{'source':'<script>alert(1)</script>.pdf','id':'../../evil','canonical_url':'https://evil.example/','status':'copied'}]
  r=self.read()['records'][0];self.assertIsNone(r['url']);self.assertIsNone(r['canonical_url'])
 def test_link_allowlist(self):
  self.write('dashboard-links.json',{'guide':'https://drive.google.com/drive/folders/synthetic_folder_1234','status':'javascript:alert(1)','secret':'PRIVATE'})
  self.assertEqual(list(self.read()['links']),['guide'])
  for url in ('https://drive.google.com.evil/a','https://drive.google.com/evil','https://drive.google.com/drive/folders/validfolder123?token=secret'):self.assertIsNone(_safe_link(url))
 def test_malformed_optional_fields_remain_safe(self):
  self.status['results']=[{'source':'a.pdf','status':{},'reason':[],'canonical_url':{},'at':1e100}]
  r=self.read()['records'][0];self.assertEqual(r['status'],'needs_review');self.assertIsNone(r['at']);self.assertIsNone(r['canonical_url'])
 def test_bounded_records(self):
  self.write('drive-ingress-journal.json',{str(i):{'source':str(i)+'.pdf','status':'verified'} for i in range(120)})
  d=self.read();self.assertEqual(len(d['records']),100);self.assertEqual(d['records_total'],120)
 def test_current_supersedes_history(self):
  r={'id':'synthetic_document_1234','source':'/old/scan.pdf','status':'verified'};self.write('drive-ingress-journal.json',{'key':r});self.status['drive_ingress']['results']=[{**r,'status':'awaiting_verification'}]
  d=self.read();self.assertEqual(len(d['records']),1);self.assertFalse(d['records'][0]['historical'])
 def test_current_review_identity_counts_once(self):
  row={'id':'synthetic_document_1234','source':'scan.pdf','status':'needs_review'}
  self.status['drive_ingress']['results']=[row];self.status['review_pending']=[row]
  d=self.read();self.assertEqual(d['records_total'],1);self.assertEqual(d['review_count'],1)
 def test_cloud_transitions_do_not_claim_manual_review(self):
  for source,target in (('planned','pending'),('moving','awaiting_verification'),('pending_cloud','awaiting_verification')):
   self.status['drive_ingress']['results']=[{'id':'synthetic_document_1234','source':'scan.pdf','status':source}]
   d=self.read();self.assertEqual(d['records'][0]['status'],target)
 def gmail(self,**values):
  self.write('gmail-status.json',{'schema_version':1,'producer':'docxx-gmail-intake','state':'ready','checked_at':NOW-5,'monitoring_enabled':True,'pending':0,**values})
  return self.read()['gmail']
 def test_gmail_missing_means_manual_not_automatic(self):
  d=self.read()['gmail'];self.assertEqual(d,{'state':'manual','automatic':False,'checked_at':None,'pending':None,'error':None})
 def test_gmail_fresh_worker_status_is_required(self):
  for state in ('ready','processing'):
   d=self.gmail(state=state);self.assertEqual(d['state'],state);self.assertTrue(d['automatic']);self.assertEqual(d['pending'],0)
   for flag in (False,None,1,'true'):
    d=self.gmail(state=state,monitoring_enabled=flag);self.assertEqual(d['state'],'manual');self.assertFalse(d['automatic']);self.assertIsNone(d['pending'])
 def test_gmail_stale_or_future_never_claims_active(self):
  for stamp in (None,'bad',NOW-901,NOW+10):
   d=self.gmail(checked_at=stamp);self.assertEqual(d['state'],'stale');self.assertFalse(d['automatic']);self.assertIsNone(d['pending'])
 def test_gmail_error_is_allowlisted_and_does_not_leak_mail(self):
  d=self.gmail(state='error',error_code='rate_limited',pending=2,account='PRIVATE_MAIL',token='PRIVATE_TOKEN',subject='PRIVATE_SUBJECT',error='PRIVATE_ERROR',attachments=['PRIVATE_DOCUMENT'])
  self.assertFalse(d['automatic']);self.assertEqual(d['pending'],2);self.assertIn('ограничил',d['error']);self.assertNotIn('PRIVATE_',json.dumps(d))
  self.assertNotIn('PRIVATE_',json.dumps(self.gmail(state='error',error_code='PRIVATE_ERROR')))
 def test_gmail_bad_contract_fails_closed(self):
  for values in ({'schema_version':True},{'schema_version':2},{'producer':'other'},{'state':{}},{'state':'PRIVATE_STATE'}):
   d=self.gmail(**values);self.assertEqual(d['state'],'unavailable');self.assertFalse(d['automatic']);self.assertNotIn('PRIVATE_',json.dumps(d))
 def test_gmail_pause_and_unknown_queue(self):
  d=self.gmail(state='paused');self.assertFalse(d['automatic']);self.assertIsNone(d['pending'])
  for value in (-1,True,'3',None):self.assertIsNone(self.gmail(pending=value)['pending'])
 def test_gmail_symlink_and_malformed_are_unavailable(self):
  other=self.root/'other';other.write_text('{"account":"PRIVATE_MAIL"}')
  (self.root/'gmail-status.json').symlink_to(other)
  self.assertEqual(self.read()['gmail']['state'],'unavailable')
  (self.root/'gmail-status.json').unlink();(self.root/'gmail-status.json').write_text('invalid')
  self.assertEqual(self.read()['gmail']['state'],'unavailable')
class RouteTests(unittest.TestCase):
 def setUp(self):
  spec=importlib.util.spec_from_file_location('docxx_test_server',BUILDER/'dashboard-server-m4.py');self.server=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.server)
  t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);self.home=Path(t.name);state=state_path(self.home);state.mkdir(parents=True);(state/'status.json').write_text('PRIVATE_STATE');(self.home/'alias.json').symlink_to(state/'status.json');(self.home/'dir-alias').symlink_to(state)
 def request(self,path,owner=False,method='GET'):
  h=self.server.Handler.__new__(self.server.Handler);h.path=path;h.command=method;h.headers={'Host':'localhost:7777'};h.wfile=io.BytesIO();out={'headers':{}}
  h.send_response=lambda code,*a:out.update(code=code);h.send_header=lambda k,v:out['headers'].update({k:v});h.end_headers=lambda:None;h.send_error=lambda code,*a:out.update(code=code)
  with patch.object(self.server,'HOME',self.home),patch.object(self.server.Handler,'_decision_owner_authorized',return_value=owner) as gate:getattr(h,'do_'+method)()
  out['body']=h.wfile.getvalue().decode();out['gate']=gate.called;return out
 def test_anonymous_loopback_is_locked(self):
  d=self.request('/api/docxx');self.assertTrue(d['gate']);self.assertEqual(json.loads(d['body']),{'state':'owner_required'});self.assertIn('no-store',d['headers']['Cache-Control'])
 def test_owner_only_projection(self):
  d=self.request('/api/docxx',True);self.assertTrue(d['gate']);self.assertEqual(json.loads(d['body'])['state'],'unavailable');self.assertNotIn('PRIVATE_STATE',d['body'])
 def test_static_no_get_no_head_even_owner_or_alias(self):
  for owner in (True,False):
   for method in ('GET','HEAD'):
    for path in ('/Library/Application Support/DOCXX-intake/status.json','/alias.json','/dir-alias/'):
     d=self.request(path,owner,method);self.assertEqual(d['code'],403);self.assertNotIn('PRIVATE_STATE',d['body'])
if __name__=='__main__':unittest.main()
