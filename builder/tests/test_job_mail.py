"""Employer replies from Mark's job mailbox (Mark 2026-10-24): sorted on the Mac mini, read-only Gmail."""
from __future__ import annotations

import base64
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.parse

from dashboard_builder import job_mail
from dashboard_builder.owner_todo import load_items

BUILDER = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("job_mail_watcher_test", BUILDER / "job_mail_watcher.py")
WATCHER = importlib.util.module_from_spec(spec)
spec.loader.exec_module(WATCHER)
spec = importlib.util.spec_from_file_location("dashboard_job_mail_test", BUILDER / "dashboard-server-m4.py")
SERVER = importlib.util.module_from_spec(spec)
spec.loader.exec_module(SERVER)  # The server must still import with the new routes.
PAGE = (BUILDER / "mac-mini-dashboard" / "index.html").read_text()

ORUS = ("Bonjour Maxim, Merci pour ta candidature au poste de Business Developer - Paris - CDI, elle a retenu mon attention. "
        "Je te propose un premier échange d'environ 30 minutes afin de faire connaissance. "
        "Tu peux choisir directement le créneau qui te convient via mon agenda.")


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def client_file(root: Path, kind: str = "web") -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "google_client.json").write_text(json.dumps({kind: {
        "client_id": "id.apps.googleusercontent.com", "client_secret": "s3cret",
        "redirect_uris": ["https://command.meshly.fr/api/job-mail/oauth/callback"]}}))


class ClassifyTests(unittest.TestCase):
    def test_orus_invite_is_positive(self):
        self.assertEqual(job_mail.classify("Orus invites you to a meeting", ORUS, "Orus <no-reply@teamtailor.com>"), "positive")

    def test_rejections(self):
        for body in ("Malheureusement, nous ne donnerons pas suite à ta candidature au poste.",
                     "Unfortunately we have decided to move forward with other candidates for this position.",
                     "Après votre entretien, nous avons retenu un autre candidat pour le poste."):
            self.assertEqual(job_mail.classify("Votre candidature", body), "negative", body)

    def test_receipts_are_not_invites(self):
        for body in ("Nous avons bien reçu votre candidature. Si votre profil correspond, nous vous proposerons un entretien.",
                     "Thank you for applying! We will review your application and get back to you."):
            self.assertEqual(job_mail.classify("Candidature reçue", body), "ack", body)

    def test_conditional_promise_is_still_a_receipt(self):
        body = "Thank you for applying. If your application is selected, we will invite you to the next stage."
        self.assertEqual(job_mail.classify("Your application", body), "ack")
        self.assertEqual(job_mail.classify("Interview", "If you have questions, reply. Please book a slot in my calendly for your interview."), "positive")

    def test_alerts_and_unrelated_mail_are_skipped(self):
        self.assertIsNone(job_mail.classify("10 nouvelles offres qui pourraient vous intéresser", "Business Developer CDI"))
        self.assertIsNone(job_mail.classify("Votre colis", "Livraison demain", "colis@laposte.fr"))
        self.assertIsNone(job_mail.classify("Jobs for you", "Apply now", "LinkedIn <jobalerts-noreply@linkedin.com>"))

    def test_benefits_parcels_and_gyms_are_not_employers(self):
        # Seen as «зовут на собеседование» on 2026-10-25.
        self.assertIsNone(job_mail.classify("Votre CAF vous informe", "Prenez rendez-vous pour votre dossier. Reprise d'emploi : déclarez-la.",
                                            "Caf <ne-pas-repondre@caf.fr>"))
        self.assertIsNone(job_mail.classify("Votre colis arrive", "Choisissez votre créneau de livraison. Position du colis : en transit.",
                                            "La Poste - Colissimo <noreply@notif-colissimo-laposte.info>"))
        self.assertIsNone(job_mail.classify("Ton rendez-vous au club", "Réserve ton créneau avec un coach.", "Basic-Fit <info@basic-fit.com>"))
        self.assertIsNone(job_mail.classify("Rendez-vous confirmé", "Votre créneau du lundi est réservé.", "Doctolib <no-reply@doctolib.fr>"))

    def test_hiring_side_of_a_service_company_still_counts(self):
        self.assertEqual(job_mail.classify("Interview invitation", "Please book a slot for your interview.", "Amazon <jobs@amazon.com>"), "positive")
        self.assertEqual(job_mail.classify("Your application", "If you are interested, please book a slot for your interview."), "positive")

    def test_bare_job_words_are_not_enough(self):
        self.assertIsNone(job_mail.classify("Your call is booked", "Pick a slot for your demo call", "Acme <sales@acme.io>"))
        self.assertEqual(job_mail.classify("Business Developer", "Votre candidature a retenu notre attention, choisissez un créneau.",
                                           "Kaora <jobs@kaora.fr>"), "positive")

    def test_personal_mail_from_the_wrong_inbox_is_skipped(self):
        # What the personal inbox produced on 2026-10-25.
        for sender, subject, body in (
                ("Vélib' Métropole <noreply@velib-metropole.fr>", "Vos codes d'accès", "Votre réponse est confirmée. Rendez-vous en station."),
                ("Trip.com <noreply@trip.com>", "Votre réservation est confirmée", "Rendez-vous à l'aéroport. Échangez avec notre service."),
                ("GetYourGuide <no-reply@getyourguide.com>", "Your activity", "Meet your guide at the meeting point. Call us."),
                ("AliExpress <promo@aliexpress.com>", "Offre spéciale", "Une opportunité à ne pas manquer ! Échangez vos points."),
                ("Mon espace santé <ne-pas-repondre@monespacesante.fr>", "Nouveau document", "Rendez-vous dans votre espace pour échanger."),
                ("CIC <alertes@cic.fr>", "Rappel de rendez-vous", "Malheureusement votre conseiller est absent, rendez-vous décalé.")):
            self.assertIsNone(job_mail.classify(subject, body, sender), sender)

    def test_thanks_for_applying_with_next_steps_is_a_receipt(self):
        body = "Thanks for applying to Dedale! Next steps: our team reviews every application and will get back to you."
        self.assertEqual(job_mail.classify("Thanks for applying", body, "Dedale <no-reply@ashbyhq.com>"), "ack")
        body = "Merci pour votre candidature. Si votre profil correspond, nous vous proposerons un premier échange."
        self.assertEqual(job_mail.classify("Votre candidature", body, "Kaora <rh@kaora.fr>"), "ack")

    def test_company_and_role(self):
        self.assertEqual(job_mail.company_of("Orus <no-reply@teamtailor.com>"), "Orus")
        self.assertEqual(job_mail.company_of("Talent Acquisition <jobs@mytraffic.io>"), "Mytraffic")
        self.assertEqual(job_mail.company_of('"Sarah from Aircall" <sarah@aircall.io>'), "Aircall")
        self.assertEqual(job_mail.company_of("Lucca Recrutement <recrutement@lucca.fr>"), "Lucca")
        self.assertEqual(job_mail.role_of("", ORUS), "Business Developer")


class ConnectTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / "job-mail"

    def test_not_configured_until_a_client_exists(self):
        with self.assertRaises(LookupError):
            job_mail.start_connect(self.root)
        self.assertEqual(job_mail.projection(self.root)["state"], "not_configured")

    def test_downloaded_client_is_adopted_privately(self):
        downloads = self.root.parent / "Downloads"
        downloads.mkdir()
        (downloads / "client_secret_1-abc.apps.googleusercontent.com.json").write_text(json.dumps(
            {"installed": {"client_id": "x", "client_secret": "y", "redirect_uris": ["http://localhost"]}}))
        client = job_mail.load_client(self.root, downloads=downloads)
        self.assertEqual((client["kind"], client["redirect_uri"]), ("installed", "http://localhost"))
        self.assertEqual((self.root / "google_client.json").stat().st_mode & 0o777, 0o600)

    def test_consent_url_asks_read_only_with_pkce(self):
        client_file(self.root)
        url = job_mail.start_connect(self.root)
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        self.assertEqual(query["scope"], [job_mail.SCOPE])
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertEqual(query["redirect_uri"], ["https://command.meshly.fr/api/job-mail/oauth/callback"])
        self.assertEqual((self.root / "oauth_state.json").stat().st_mode & 0o777, 0o600)

    def _opener(self, scope: str, calls: list):
        def opener(request, timeout=None):
            calls.append(request.full_url)
            if request.full_url == job_mail.TOKEN_URL:
                return Response(json.dumps({"access_token": "a", "refresh_token": "r", "scope": scope}).encode())
            if request.full_url.endswith("/profile"):
                return Response(b'{"emailAddress": "maximegrachev@gmail.com"}')
            return Response(b"{}")
        return opener

    def test_finish_keeps_only_a_read_only_grant(self):
        client_file(self.root)
        state = urllib.parse.parse_qs(urllib.parse.urlsplit(job_mail.start_connect(self.root)).query)["state"][0]
        calls = []
        self.assertEqual(job_mail.finish_connect("4/0AbCdEfGhIj", state, self.root, opener=self._opener(job_mail.SCOPE, calls)),
                         {"email": "maximegrachev@gmail.com"})
        token = json.loads((self.root / "token.json").read_text())
        self.assertEqual((token["refresh_token"], token["scope"]), ("r", job_mail.SCOPE))
        self.assertEqual((self.root / "token.json").stat().st_mode & 0o777, 0o600)
        view = job_mail.projection(self.root)
        self.assertEqual((view["state"], view["email"]), ("connected", "maximegrachev@gmail.com"))
        self.assertNotIn("\"r\"", json.dumps(view))
        self.assertNotIn("s3cret", json.dumps(view))

    def test_wider_grant_is_revoked_and_refused(self):
        client_file(self.root)
        state = urllib.parse.parse_qs(urllib.parse.urlsplit(job_mail.start_connect(self.root)).query)["state"][0]
        calls = []
        with self.assertRaises(ValueError):
            job_mail.finish_connect("4/0AbCdEfGhIj", state, self.root,
                                    opener=self._opener(f"{job_mail.SCOPE} https://mail.google.com/", calls))
        self.assertIn(job_mail.REVOKE_URL, calls)
        self.assertFalse((self.root / "token.json").exists())

    def test_another_inbox_is_revoked_and_refused(self):
        client_file(self.root)
        (self.root / "expected_account").write_text("job.inbox@gmail.com")
        state = urllib.parse.parse_qs(urllib.parse.urlsplit(job_mail.start_connect(self.root)).query)["state"][0]
        calls = []
        with self.assertRaisesRegex(ValueError, "wrong_account"):
            job_mail.finish_connect("4/0AbCdEfGhIj", state, self.root, opener=self._opener(job_mail.SCOPE, calls))
        self.assertIn(job_mail.REVOKE_URL, calls)
        self.assertFalse((self.root / "token.json").exists())

    def test_state_must_match_and_is_single_use(self):
        client_file(self.root)
        state = urllib.parse.parse_qs(urllib.parse.urlsplit(job_mail.start_connect(self.root)).query)["state"][0]
        with self.assertRaises(ValueError):
            job_mail.finish_connect("4/0AbCdEfGhIj", "forged", self.root, opener=self._opener(job_mail.SCOPE, []))
        with self.assertRaises(ValueError):
            job_mail.finish_connect("4/0AbCdEfGhIj", state, self.root, opener=self._opener(job_mail.SCOPE, []))

    def test_pasted_return_address(self):
        self.assertEqual(job_mail.parse_pasted_return("http://localhost:8080/cb?state=abc&code=4/xyz&scope=x"), ("4/xyz", "abc"))
        with self.assertRaises(ValueError):
            job_mail.parse_pasted_return("http://localhost/?error=access_denied&state=abc")


def gmail_message(message_id, thread_id, sender, subject, body, ms, labels=("INBOX",)):
    data = base64.urlsafe_b64encode(body.encode()).decode()
    return {"id": message_id, "threadId": thread_id, "internalDate": str(ms), "labelIds": list(labels),
            "payload": {"mimeType": "text/plain", "headers": [{"name": "From", "value": sender}, {"name": "Subject", "value": subject}],
                        "body": {"data": data}}}


class WatcherTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        base = Path(temp.name)
        self.root = base / "job-mail"
        client_file(self.root)
        (self.root / "token.json").write_text(json.dumps({"refresh_token": "r", "email": "maximegrachev@gmail.com"}))
        self.todo = base / "owner-todo.json"
        self.telegram = base / "telegram.json"
        self.sent: list[dict] = []
        self.replied: set[str] = set()
        self.messages = {
            "m1": gmail_message("m1", "t1", "Orus <no-reply@teamtailor.com>", "Orus invites you to a meeting", ORUS, 1_792_000_000_000),
            "m2": gmail_message("m2", "t2", "Lucca Recrutement <recrutement@lucca.fr>", "Votre candidature",
                                "Malheureusement nous ne donnerons pas suite à votre candidature.", 1_791_000_000_000),
            "m3": gmail_message("m3", "t3", "Fabriq <jobs@fabriq.tech>", "Candidature reçue",
                                "Nous avons bien reçu votre candidature.", 1_790_000_000_000),
        }
        patches = [patch.object(WATCHER, "OWNER_TODO_FILE", self.todo), patch.object(WATCHER, "TELEGRAM_FILE", self.telegram)]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def opener(self, request, timeout=None):
        url = request.full_url
        if url == job_mail.TOKEN_URL:
            return Response(b'{"access_token": "a"}')
        if url.startswith("https://api.telegram.org/"):
            self.sent.append(json.loads(request.data))
            return Response(b'{"ok": true}')
        path = urllib.parse.urlsplit(url).path.rsplit("/me/", 1)[1]
        if path == "messages":
            return Response(json.dumps({"messages": [{"id": key} for key in self.messages]}).encode())
        if path.startswith("messages/"):
            return Response(json.dumps(self.messages[path.split("/")[1]]).encode())
        if path.startswith("threads/"):
            thread = path.split("/")[1]
            sent = [{"labelIds": ["SENT"], "internalDate": "1792000000001"}] if thread in self.replied else []
            return Response(json.dumps({"messages": sent}).encode())
        raise AssertionError(url)

    def test_new_invite_alerts_once_then_closes_when_answered(self):
        self.telegram.write_text(json.dumps({"bot_token": "b", "chat_id": "c"}))
        result = WATCHER.run(self.root, opener=self.opener)
        self.assertTrue(result["ok"])
        view = job_mail.projection(self.root)
        self.assertEqual([reply["company"] for reply in view["waiting"]], ["Orus"])
        self.assertEqual(view["stats"]["totals"], {"positive": 1, "negative": 1, "ack": 1, "other": 0})
        self.assertEqual(view["stats"]["positive_rate"], 50)
        self.assertEqual(len(self.sent), 1)
        self.assertIn("Orus", self.sent[0]["text"])
        self.assertNotIn("créneau", self.sent[0]["text"])  # A pointer to the mail, never its text.
        todo = load_items(self.todo)["items"][0]
        self.assertTrue(todo["text"].startswith("Ответить Orus"))
        self.assertFalse(todo["triage"]["agent"])  # Agents never answer employers.
        WATCHER.run(self.root, opener=self.opener)
        self.assertEqual(len(self.sent), 1)  # Seen mail is not alerted twice.
        self.replied.add("t1")
        WATCHER.run(self.root, opener=self.opener)
        self.assertEqual(job_mail.projection(self.root)["waiting"], [])
        self.assertTrue(load_items(self.todo)["items"][0]["done"])

    def test_failed_telegram_is_retried_and_downtime_is_rescanned(self):
        self.telegram.write_text(json.dumps({"bot_token": "b", "chat_id": "c"}))
        real = self.opener
        down = {"on": True}

        def flaky(request, timeout=None):
            if request.full_url.startswith("https://api.telegram.org/") and down["on"]:
                raise OSError("telegram down")
            return real(request, timeout)
        self.assertEqual(WATCHER.run(self.root, opener=flaky)["telegram"], "telegram_failed")
        down["on"] = False
        self.assertEqual(WATCHER.run(self.root, opener=flaky)["telegram"], "sent")
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(sum(item["text"].startswith("Ответить") for item in load_items(self.todo)["items"]), 1)  # Not one per try.
        WATCHER.run(self.root, opener=flaky)
        self.assertEqual(len(self.sent), 1)
        saved = json.loads((self.root / "replies.json").read_text())
        self.assertTrue(saved["last_scan_ok"])
        queries = []

        def watch(request, timeout=None):
            if "/messages?" in request.full_url:
                queries.append(urllib.parse.parse_qs(urllib.parse.urlsplit(request.full_url).query)["q"][0])
            return real(request, timeout)
        WATCHER.run(self.root, opener=watch)
        self.assertTrue(queries[0].startswith("after:"))

    def test_new_rules_resort_the_inbox_and_drop_false_invites(self):
        self.messages["m4"] = gmail_message("m4", "t4", "Caf <ne-pas-repondre@caf.fr>", "Votre CAF : prenez rendez-vous",
                                            "Réservez un créneau. Candidature au RSA.", 1_792_100_000_000)
        real = job_mail.classify
        loose = lambda subject, body, sender="": "positive" if "caf" in sender.lower() else real(subject, body, sender)
        with patch.object(job_mail, "CLASSIFIER_VERSION", 1), patch.object(job_mail, "classify", loose):
            WATCHER.run(self.root, opener=self.opener)
        self.assertEqual(sorted(reply["company"] for reply in job_mail.projection(self.root)["waiting"]), ["Caf", "Orus"])
        WATCHER.run(self.root, opener=self.opener)  # Current rules: sorted again.
        self.assertEqual([reply["company"] for reply in job_mail.projection(self.root)["waiting"]], ["Orus"])
        items = {item["text"]: item for item in load_items(self.todo)["items"]}
        self.assertNotIn("Ответить Caf: зовут на собеседование", items)  # A false invite leaves no trace in «Ждёт тебя».
        self.assertFalse(items["Ответить Orus: зовут на собеседование"]["done"])  # Kept, not added twice.
        self.assertEqual(sum(text.startswith("Ответить Orus") for text in items), 1)
        saved = json.loads((self.root / "replies.json").read_text())
        self.assertEqual(saved["classifier"], job_mail.CLASSIFIER_VERSION)

    def test_only_the_job_inbox_is_watched(self):
        (self.root / "expected_account").write_text("maximegrachev@gmail.com\n")
        url = job_mail.start_connect(self.root)
        self.assertIn("login_hint=maximegrachev%40gmail.com", url)
        (self.root / "token.json").write_text(json.dumps({"refresh_token": "r", "email": "someone.else@gmail.com"}))
        result = WATCHER.run(self.root, opener=self.opener)
        self.assertEqual((result["ok"], result["reason"]), (False, "wrong_account"))
        view = job_mail.projection(self.root)
        self.assertEqual((view["state"], view["expected"], view["recent"]), ("wrong_account", "maximegrachev@gmail.com", []))

    def test_switching_inbox_starts_over(self):
        self.messages["m4"] = gmail_message("m4", "t4", "Acme Talent <talent@acme.io>", "Interview invitation",
                                            "We would like to invite you to an interview. Pick a slot.", 1_792_100_000_000)
        (self.root / "token.json").write_text(json.dumps({"refresh_token": "r", "email": "personal@gmail.com"}))
        WATCHER.run(self.root, opener=self.opener)
        self.assertEqual(len(job_mail.projection(self.root)["waiting"]), 2)
        del self.messages["m4"]
        (self.root / "token.json").write_text(json.dumps({"refresh_token": "r", "email": "maximegrachev@gmail.com"}))
        WATCHER.run(self.root, opener=self.opener)
        self.assertEqual([reply["company"] for reply in job_mail.projection(self.root)["waiting"]], ["Orus"])
        self.assertEqual([item["text"] for item in load_items(self.todo)["items"] if item["text"].startswith("Ответить")],
                         ["Ответить Orus: зовут на собеседование"])

    def test_failed_resort_sends_nothing_twice(self):
        self.telegram.write_text(json.dumps({"bot_token": "b", "chat_id": "c"}))
        with patch.object(job_mail, "CLASSIFIER_VERSION", 1):
            WATCHER.run(self.root, opener=self.opener)
        self.assertEqual(len(self.sent), 1)
        self.messages["m5"] = gmail_message("m5", "t5", "Acme Talent <talent@acme.io>", "Interview invitation",
                                            "We would like to invite you to an interview. Pick a slot.", 1_792_100_000_000)
        real = self.opener

        def broken_threads(request, timeout=None):
            if "/threads/" in request.full_url:
                raise OSError("gmail down")
            return real(request, timeout)
        self.assertFalse(WATCHER.run(self.root, opener=broken_threads)["ok"])  # Re-sort read Acme, then Gmail failed.
        self.assertEqual(len(self.sent), 1)
        WATCHER.run(self.root, opener=self.opener)
        WATCHER.run(self.root, opener=self.opener)
        self.assertEqual(len(self.sent), 2)  # Acme once, Orus never again.
        self.assertEqual(sorted(item["text"] for item in load_items(self.todo)["items"] if item["text"].startswith("Ответить")),
                         ["Ответить Acme: зовут на собеседование", "Ответить Orus: зовут на собеседование"])

    def test_stale_check_is_not_shown_as_all_clear(self):
        WATCHER.run(self.root, opener=self.opener)
        from datetime import datetime, timedelta, timezone
        later = datetime.now(timezone.utc) + timedelta(hours=3)
        self.assertTrue(job_mail.projection(self.root, today=later)["stale"])
        self.assertFalse(job_mail.projection(self.root)["stale"])

    def test_without_telegram_the_site_still_shows_it(self):
        result = WATCHER.run(self.root, opener=self.opener)
        self.assertEqual(result["telegram"], "telegram_not_configured")
        self.assertEqual(len(job_mail.projection(self.root)["waiting"]), 1)

    def test_not_connected_is_quiet(self):
        (self.root / "token.json").unlink()
        result = WATCHER.run(self.root, opener=self.opener)
        self.assertEqual((result["ok"], result["reason"]), (False, "not_connected"))
        self.assertEqual(job_mail.projection(self.root)["state"], "not_connected")


class ServerAndPageTests(unittest.TestCase):
    def test_api_is_owner_only_and_page_has_the_fold(self):
        source = (BUILDER / "dashboard-server-m4.py").read_text()
        self.assertIn("if parsed.path == '/api/job-mail':\n            # Employer replies", source)
        self.assertIn("if not self._decision_owner_authorized():\n                self._json_response(401, {'error': 'owner_token_required', 'state': 'owner_required'})", source)
        self.assertIn("self._platform_owner_body(4096)", source)  # Writes: owner + same origin + JSON.
        self.assertIn('id="mm-job-mail"', PAGE)
        self.assertIn("Ответы работодателей", PAGE)
        self.assertIn("/^https:\\/\\/accounts\\.google\\.com\\//", PAGE)  # Only ever sends Mark to Google.

    def test_deploy_installs_the_watcher(self):
        deploy = (BUILDER / "deploy_to_scripts.sh").read_text()
        self.assertIn("com.pirajoke.job-mail-watcher", deploy)
        self.assertIn('cp "$SRC_DIR/job_mail_watcher.py"', deploy)
        plist = (BUILDER / "launchd" / "com.pirajoke.job-mail-watcher.plist.template").read_text()
        self.assertIn("job_mail_watcher.py", plist)


if __name__ == "__main__":
    unittest.main()
