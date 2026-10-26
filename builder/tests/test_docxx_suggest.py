"""The Mac mini suggests a library folder for each «Нужен разбор» document from its content."""
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

BUILDER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BUILDER))

import docxx_suggest as SUGGEST  # noqa: E402
from dashboard_builder.docxx import docxx_projection  # noqa: E402
from dashboard_builder.docxx_actions import load_suggestions  # noqa: E402

REVIEW = '10 — 📥 To review/Documents to review'
SHA = 'a' * 64

FAKE_CLAUDE = '''#!/usr/bin/env python3
import json, os, re, sys
prompt = sys.stdin.read()
with open(os.environ["FAKE_CLAUDE_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps({"argv": sys.argv[1:], "prompt": prompt}) + "\\n")
data = json.loads(prompt[prompt.index("{"):])
answer = {}
for doc in data["documents"]:
    if doc["name"] == "ticket.pdf":
        answer[doc["id"]] = {"folder": "France/Médiathèque", "junk": False, "why": "Билет медиатеки"}
    elif doc["name"] == "scan.pdf":
        answer[doc["id"]] = {"folder": "Invented/Folder", "junk": True, "why": "Пустой скан"}
print(json.dumps({"result": json.dumps(answer, ensure_ascii=False)}))
'''


class SuggestTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        base = Path(t.name)
        self.home = base / 'home'
        self.state = base / 'state'
        self.state.mkdir(parents=True)
        self.library = base / 'Drive' / 'DOCXXx'
        for folder in (REVIEW, 'France/Médiathèque', 'France/Impôts', '90 — Archive'):
            (self.library / folder).mkdir(parents=True)
        status = {'checked_at': time.time() - 5, 'phase': 'needs_review', 'model_calls': 0,
                  'catalog': {'status': 'ready', 'documents': 2}, 'results': [],
                  'drive_ingress': {'status': 'idle', 'pending': 0, 'results': []}, 'review_pending': []}
        (self.state / 'status.json').write_text(json.dumps(status), encoding='utf-8')
        for name in ('journal.json', 'drive-ingress-journal.json', 'config.json'):
            (self.state / name).write_text('{}', encoding='utf-8')
        (self.state / 'runner.lock').touch()
        attachments = {}
        for name in ('ticket.pdf', 'scan.pdf'):
            path = self.library / REVIEW / name
            path.write_bytes(b'%PDF synthetic')
            attachments[name] = {'state': 'delivered', 'needs_review': True, 'name': name,
                                 'destination': str(path), 'delivered_at': time.time() - 60}
        attachments['ticket.pdf'].update(sha256=SHA, size=14)
        (self.state / 'gmail-journal.json').write_text(
            json.dumps({'schema_version': 1, 'attachments': attachments}), encoding='utf-8')
        db = sqlite3.connect(self.state / 'operations.sqlite3')
        db.execute('CREATE TABLE extractions (sha256 TEXT, extractor_id TEXT, created_at TEXT, text TEXT)')
        db.execute('INSERT INTO extractions VALUES (?,?,?,?)', (SHA, 'pdf', '2026-10-24T10:00:00Z',
                   'Médiathèque Ormesson\nTicket de connexion\nIdentifiant : mark42\nMot de passe : hunter2\nValable 1h'))
        db.commit()
        db.close()
        self.cli = base / 'claude'
        self.cli.write_text(FAKE_CLAUDE, encoding='utf-8')
        self.cli.chmod(0o755)
        self.log = base / 'calls.log'
        env = patch.dict(os.environ, {'FAKE_CLAUDE_LOG': str(self.log)})
        env.start()
        self.addCleanup(env.stop)

    def run_main(self):
        return SUGGEST.main(['--state', str(self.state), '--home', str(self.home), '--claude', str(self.cli)])

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def test_suggestions_use_the_text_without_passwords_and_only_real_folders(self):
        self.assertEqual(self.run_main(), 0)
        call = self.calls()[0]
        self.assertIn('Médiathèque Ormesson', call['prompt'])
        self.assertNotIn('hunter2', call['prompt'])
        self.assertNotIn('mark42', call['prompt'])
        self.assertNotIn(str(self.library), call['prompt'])
        self.assertEqual(call['argv'][call['argv'].index('--tools') + 1], '')
        out = self.home / '.agent-bridge' / 'docxx-suggestions.json'
        self.assertEqual(out.stat().st_mode & 0o777, 0o600)
        items = load_suggestions(out)
        by_name = {v['name']: v for v in items.values()}
        self.assertEqual(by_name['ticket.pdf']['folder'], 'France/Médiathèque')
        self.assertEqual((by_name['scan.pdf']['folder'], by_name['scan.pdf']['junk']), (None, True))
        rows = {r['original_name']: r for r in docxx_projection(self.state, owner=True, suggestions=items)['records']}
        self.assertEqual(rows['ticket.pdf']['suggest'], {'folder': 'France/Médiathèque', 'why': 'Билет медиатеки'})
        self.assertEqual(rows['scan.pdf']['suggest'], {'junk': True, 'why': 'Пустой скан'})

        self.run_main()
        self.assertEqual(len(self.calls()), 1)  # Documents already guessed are not asked again.

    def test_public_projection_never_carries_suggestions(self):
        self.run_main()
        items = load_suggestions(self.home / '.agent-bridge' / 'docxx-suggestions.json')
        self.assertEqual(docxx_projection(self.state, owner=False, suggestions=items), {'state': 'owner_required'})

    def test_deploy_installs_the_job(self):
        deploy = (BUILDER / 'deploy_to_scripts.sh').read_text()
        self.assertIn('cp "$SRC_DIR/docxx_suggest.py"', deploy)
        self.assertIn('py_compile docxx_suggest.py', deploy)
        plist = (BUILDER / 'launchd' / 'com.pirajoke.docxx-suggest.plist.template').read_text()
        self.assertIn('__SCRIPTS_DIR__/docxx_suggest.py', plist)


if __name__ == '__main__':
    unittest.main()
