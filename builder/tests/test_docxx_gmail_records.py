import json
import unittest
import test_docxx as fixture
NOW = fixture.NOW


class GmailRecordsTests(unittest.TestCase):
 setUp = fixture.ProjectionTests.setUp
 write = fixture.ProjectionTests.write
 read = fixture.ProjectionTests.read
 def seed(self, attachments):
  self.write('gmail-journal.json', {'schema_version':1, 'source_account':'source@example.com',
    'delivery_account':'archive@example.com', 'attachments':attachments,
    'history_id':'PRIVATE_HISTORY'})

 def test_gmail_cloud_receipt_replaces_shared_classifier_row(self):
  self.write('journal.json', {'hash':{'source':'/Users/private/state/gmail-staging/hash/scan.pdf',
    'destination':'/Users/private/DOCXXx/France/Acte.pdf', 'status':'copied'}})
  self.seed({'secret_attachment':{'state':'delivered','name':'scan.pdf',
    'destination':'/Users/private/DOCXXx/France/Acte.pdf','cloud_file_id':'synthetic_document_1234',
    'delivered_at':NOW-20,'message_id':'PRIVATE_MESSAGE','attachment_id':'PRIVATE_ATTACHMENT',
    'text':'PRIVATE_TEXT'}})
  result=self.read();self.assertEqual(len(result['records']),1)
  row=result['records'][0];self.assertEqual(row['source'],'gmail');self.assertEqual(row['status'],'verified')
  # Mark 2026-11-02: the owner sees which mailbox sent it; nothing else from the mail leaks.
  self.assertEqual(row['source_account'],'source@example.com')
  for private in ('PRIVATE_','archive@example.com','/Users/private','secret_attachment'):
   self.assertNotIn(private,json.dumps(result))

 def test_per_attachment_mailbox_wins_and_junk_accounts_are_dropped(self):
  self.seed({'a':{'state':'delivered','name':'a.pdf','destination':'/Users/private/DOCXXx/A/a.pdf',
    'cloud_file_id':'synthetic_document_aaaa','delivered_at':NOW-20,'source_account':'Other@Example.com'},
    'b':{'state':'delivered','name':'b.pdf','destination':'/Users/private/DOCXXx/B/b.pdf',
    'cloud_file_id':'synthetic_document_bbbb','delivered_at':NOW-20,'source_account':'PRIVATE_<script>'}})
  rows={r['name']:r for r in self.read()['records']}
  self.assertEqual(rows['a.pdf']['source_account'],'other@example.com')
  self.assertEqual(rows['b.pdf']['source_account'],'source@example.com')

 def test_reviewed_original_and_translation_are_one_result(self):
  item={'state':'delivered','destination':'/Users/private/DOCXXx/France/Acte.pdf',
    'cloud_file_id':'synthetic_document_1234','delivered_at':NOW-20}
  self.seed({'original':dict(item,name='original.pdf'),'translation':dict(item,name='translation.pdf')})
  result=self.read();self.assertEqual(result['records_total'],1)
  self.assertEqual(result['records'][0]['original_name'],'original.pdf + translation.pdf')

 def test_unverified_and_unknown_remain_attention(self):
  self.seed({'pending':{'state':'pending','name':'scan.pdf','destination':'/Users/private/DOCXXx/France/Acte.pdf',
    'error_code':'delivery_pending'},'review':{'state':'delivered','name':'other.pdf','needs_review':True}})
  result=self.read();self.assertEqual(result['review_count'],2)
  self.assertEqual({r['status'] for r in result['records']},{'awaiting_verification','needs_review'})
  self.assertTrue(all(r['url'] is None for r in result['records']))

 def test_gmail_auth_and_catalog_errors_have_specific_safe_copy(self):
  for code,expected in [('auth_required','подключить Gmail'),('catalog_unavailable','каталог недоступен'),
                       ('message_not_found','Одно из писем недоступно')]:
   self.write('gmail-status.json',{'schema_version':1,'producer':'docxx-gmail-intake',
     'state':'error','checked_at':NOW-1,'monitoring_enabled':True,'pending':2,'error_code':code})
   self.assertIn(expected,self.read()['gmail']['error'])

 def test_malformed_gmail_journal_does_not_hide_other_sources(self):
  self.write('gmail-journal.json',{'schema_version':1,'attachments':[]})
  result=self.read();self.assertIn('История вложений Gmail недоступна.',result['warnings'])

 def test_shared_review_pending_preserves_dedicated_gmail_source_and_link(self):
  destination='/Users/private/DOCXXx/Review/Acte.pdf'
  self.seed({'record':{'state':'delivered','needs_review':True,'name':'scan.pdf',
    'destination':destination,'cloud_file_id':'synthetic_document_1234','delivered_at':NOW-20}})
  self.status['review_pending']=[{'source':'/Users/private/state/gmail-staging/hash/scan.pdf',
    'destination':destination,'status':'needs_review'}]
  result=self.read();self.assertEqual(result['records_total'],1)
  row=result['records'][0];self.assertEqual(row['source'],'gmail')
  self.assertEqual(row['status'],'needs_review')
  self.assertIn('synthetic_document_1234',row['url'])

 def test_shared_review_falls_back_when_gmail_journal_unavailable(self):
  self.write('gmail-journal.json',{'schema_version':1,'attachments':[]})
  self.status['review_pending']=[{'source':'/Users/private/state/gmail-staging/hash/scan.pdf',
    'destination':'/Users/private/DOCXXx/Review/Acte.pdf','status':'needs_review'}]
  result=self.read();self.assertEqual(result['records_total'],1)
  self.assertEqual(result['records'][0]['status'],'needs_review')
