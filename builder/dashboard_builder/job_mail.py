"""Employer replies from Mark's job mailbox (Mark 2026-10-24).

Mark nearly missed an Orus interview invite: «сделай так чтобы я не пропускал положительные
результаты, веди статистику… это должно быть встроено в платформу, подключи мейл безопасно».

How it stays safe:

* Gmail is connected with the ``gmail.readonly`` scope only, so nothing here can send, delete,
  label or mark mail as read. Mark connects it himself with «Подключить почту» (Google consent).
* The refresh token lives only on the Mac mini (``~/.agent-bridge/job-mail/token.json``, mode 600).
  It is never served; the site only learns which address is connected.
* Replies are sorted on the Mac mini by plain rules (no model, no other service). What is stored
  and shown is the company, the role, the date, the verdict and the subject; never the mail text.
* Everything is owner-only. «Отключить почту» revokes the token at Google and deletes it.

``job_mail_watcher.py`` (launchd, every 10 minutes) fills ``replies.json``; the server reads it.
"""
from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

from .platform_edits import _write_json

HOME = Path.home()
JOB_MAIL_DIR = Path(os.environ.get("JOB_MAIL_DIR") or HOME / ".agent-bridge" / "job-mail")
SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"
STATE_TTL = 15 * 60
VERDICTS = ("positive", "negative", "ack", "other")


def paths(root: Path | None = None) -> dict[str, Path]:
    base = root or JOB_MAIL_DIR
    return {"dir": base, "client": base / "google_client.json", "token": base / "token.json",
            "state": base / "oauth_state.json", "replies": base / "replies.json", "status": base / "status.json"}


def _read(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ─── Connecting (OAuth with PKCE) ───

def _adopt_downloaded_client(target: Path, downloads: Path) -> None:
    """Mark's Google OAuth client sits in ~/Downloads as Google names it; keep a private copy (mode 600)."""
    try:
        found = sorted(downloads.glob("client_secret_*.apps.googleusercontent.com.json"), key=lambda path: path.stat().st_mtime)
    except OSError:
        return
    for candidate in reversed(found):
        data = _read(candidate)
        if isinstance(data, dict) and (isinstance(data.get("web"), dict) or isinstance(data.get("installed"), dict)):
            _write_json(target, data, prefix=".client-")
            return


def load_client(root: Path | None = None, *, downloads: Path | None = None) -> dict | None:
    """The Google OAuth client Mark downloaded ("web" or "installed" JSON), or None."""
    target = paths(root)["client"]
    if not target.exists() and (root is None or downloads is not None):
        _adopt_downloaded_client(target, downloads or HOME / "Downloads")
    data = _read(target)
    if not isinstance(data, dict):
        return None
    kind = "web" if isinstance(data.get("web"), dict) else "installed" if isinstance(data.get("installed"), dict) else None
    if not kind:
        return None
    entry = data[kind]
    if not all(isinstance(entry.get(key), str) and entry[key] for key in ("client_id", "client_secret")):
        return None
    redirects = [uri for uri in entry.get("redirect_uris") or [] if isinstance(uri, str)]
    # A web client sends Google back to a registered address; ours on the site wins when registered.
    preferred = next((uri for uri in redirects if uri.endswith("/api/job-mail/oauth/callback")), None)
    redirect = data.get("redirect_uri") if isinstance(data.get("redirect_uri"), str) else preferred or (redirects[0] if redirects else None)
    if not redirect:
        redirect = "http://127.0.0.1:7777/api/job-mail/oauth/callback"
    return {"kind": kind, "client_id": entry["client_id"], "client_secret": entry["client_secret"], "redirect_uri": redirect}


def start_connect(root: Path | None = None, *, now: float | None = None) -> str:
    """Return the Google consent URL and remember its state + PKCE verifier on the Mac mini."""
    client = load_client(root)
    if not client:
        raise LookupError("client_not_configured")
    state = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    _write_json(paths(root)["state"], {"state": state, "verifier": verifier, "created": now or time.time(),
                                       "redirect_uri": client["redirect_uri"]}, prefix=".oauth-state-")
    query = {"client_id": client["client_id"], "redirect_uri": client["redirect_uri"], "response_type": "code",
             "scope": SCOPE, "access_type": "offline", "prompt": "consent select_account", "state": state,
             "code_challenge": challenge, "code_challenge_method": "S256"}
    return f"{AUTH_URL}?{urllib.parse.urlencode(query)}"


def _post_form(url: str, form: dict, opener=urllib.request.urlopen) -> dict:
    request = urllib.request.Request(url, data=urllib.parse.urlencode(form).encode(), method="POST",
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with opener(request, timeout=20) as response:
            return json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        try:
            detail = json.loads(error.read() or b"{}")
        except ValueError:
            detail = {}
        raise RuntimeError(str(detail.get("error") or f"http_{error.code}")[:60]) from None


def _get_json(url: str, access_token: str, opener=urllib.request.urlopen) -> dict:
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {access_token}"})
    try:
        with opener(request, timeout=30) as response:
            return json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        raise RuntimeError("auth_required" if error.code in (401, 403) else f"gmail_http_{error.code}") from None


def finish_connect(code: str, state: str, root: Path | None = None, *, now: float | None = None,
                   opener=urllib.request.urlopen) -> dict:
    """Swap Google's one-time code for a read-only refresh token; store it on the Mac mini only."""
    p = paths(root)
    saved = _read(p["state"])
    try:
        p["state"].unlink()  # One try per «Подключить почту».
    except OSError:
        pass
    if (not isinstance(saved, dict) or not isinstance(state, str) or not secrets.compare_digest(str(saved.get("state", "")), state)
            or (now or time.time()) - float(saved.get("created") or 0) > STATE_TTL):
        raise ValueError("state_mismatch")
    if not isinstance(code, str) or not re.fullmatch(r"[A-Za-z0-9/_.\-]{10,512}", code):
        raise ValueError("invalid_code")
    client = load_client(root)
    if not client:
        raise LookupError("client_not_configured")
    answer = _post_form(TOKEN_URL, {"code": code, "client_id": client["client_id"], "client_secret": client["client_secret"],
                                    "redirect_uri": saved.get("redirect_uri") or client["redirect_uri"],
                                    "grant_type": "authorization_code", "code_verifier": saved.get("verifier", "")}, opener)
    granted = set(str(answer.get("scope") or "").split())
    if granted != {SCOPE}:
        # Only ever keep a read-only grant. Anything wider is handed straight back to Google.
        for token in (answer.get("refresh_token"), answer.get("access_token")):
            if token:
                try:
                    _post_form(REVOKE_URL, {"token": token}, opener)
                except RuntimeError:
                    pass
        raise ValueError("scope_not_read_only")
    if not answer.get("refresh_token"):
        raise ValueError("no_refresh_token")
    profile = _get_json(f"{GMAIL_API}/profile", answer["access_token"], opener)
    email = str(profile.get("emailAddress") or "")[:120]
    record = {"refresh_token": answer["refresh_token"], "scope": SCOPE, "email": email,
              "connected_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    _write_json(p["token"], record, prefix=".token-")
    return {"email": email}


def parse_pasted_return(url: str) -> tuple[str, str]:
    """When Google sends the phone to an address only the Mac mini answers, Mark pastes it here."""
    if not isinstance(url, str) or len(url) > 2048:
        raise ValueError("invalid_url")
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(url.strip()).query)
    if query.get("error"):
        raise ValueError("consent_refused")
    code, state = (query.get("code") or [""])[0], (query.get("state") or [""])[0]
    if not code or not state:
        raise ValueError("invalid_url")
    return code, state


def disconnect(root: Path | None = None, opener=urllib.request.urlopen) -> None:
    """Revoke at Google (best effort) and delete the token. The reply history stays."""
    p = paths(root)
    token = _read(p["token"])
    if isinstance(token, dict) and token.get("refresh_token"):
        try:
            _post_form(REVOKE_URL, {"token": token["refresh_token"]}, opener)
        except (RuntimeError, OSError):
            pass
    for name in ("token", "state"):
        try:
            p[name].unlink()
        except FileNotFoundError:
            pass


def access_token(root: Path | None = None, opener=urllib.request.urlopen) -> tuple[str, str]:
    """A short-lived read-only access token and the mailbox address, for the watcher."""
    token, client = _read(paths(root)["token"]), load_client(root)
    if not isinstance(token, dict) or not token.get("refresh_token"):
        raise LookupError("not_connected")
    if not client:
        raise LookupError("client_not_configured")
    try:
        answer = _post_form(TOKEN_URL, {"refresh_token": token["refresh_token"], "client_id": client["client_id"],
                                        "client_secret": client["client_secret"], "grant_type": "refresh_token"}, opener)
    except RuntimeError as error:
        raise RuntimeError("auth_required" if str(error) in ("invalid_grant", "unauthorized_client") else str(error)) from None
    if not answer.get("access_token"):
        raise RuntimeError("auth_required")
    return answer["access_token"], str(token.get("email") or "")


# ─── Sorting a reply ───

def _plain(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return " ".join(text.replace("’", "'").split())


# Newsletters and job alerts are not replies to Mark.
_NOT_A_REPLY = re.compile(r"job ?alert|alerte(s)? (emploi|e-mail)|offres? (qui )?pourrai|new jobs? for you|jobs? you may|recommended jobs|"
                          r"emplois? recommand|nouvelles? offres?|jobs? (similaires|similar)|newsletter|webinar|unsubscribe from (job|this alert)")
_JOB = re.compile(r"candidat|application|apply|applied|poste|position|role\b|recrut|recruit|hiring|talent|entretien|interview|"
                  r"\bcdi\b|\bcdd\b|stage|alternance|job|emploi|opportunit|process(us)? de recrutement")
_NEGATIVE = re.compile(
    r"malheureusement|ne (pas )?(pouvons|pourrons) (pas )?(donner|repondre) (une )?suite|pas (pu )?donner (une )?suite|"
    r"(ne|pas) donner suite|ne donnerons pas suite|n'?avons pas retenu|pas (ete )?retenu|n'?a pas ete retenu|"
    r"(d'?autres?|un autre) (candidat|profil)|ne correspond(ent)? pas|regret|unfortunately|not (to )?(be )?mov(e|ing) forward|"
    r"decided to (move|proceed|pursue|go) (forward )?with (other|another)|other candidates|not (been )?selected|"
    r"will not be (progressing|proceeding|taking)|position has been filled|poste (a ete|est) pourvu|"
    r"no longer (considering|available)|declin|suite defavorable|pas de suite favorable|pas en mesure de (vous )?proposer")
_STRONG_POSITIVE = re.compile(
    r"invites? you|t'?invite|vous invite|invitation (a|to) (un|an|a|the)? ?(entretien|interview|echange|call|meeting)|"
    r"(premier|1er|court) (echange|entretien|appel|call)|(choisir|reserver|selectionner|book|pick|schedule) (un |a |le |your |ton |votre )?"
    r"(creneau|slot|time|call|interview|meeting|entretien)|calendly|cal\.com|meetings\.hubspot|creneau|disponibilites|your availability|"
    r"a retenu (mon|notre) attention|retenu notre attention|caught (my|our) (attention|eye)|(aimerions|aimerais|souhaiterions|souhaiterais) "
    r"(vous|te) (rencontrer|parler|echanger|proposer un)|(would|we'?d) (like|love) to (meet|speak|chat|schedule|invite|talk)|"
    r"next (step|round|stage)|prochaine etape|etape suivante|test technique|cas pratique|case study|home assignment|phone screen|"
    r"rendez-vous|(nous|je) (vous|te) propos(e|ons) (un|une)|offre d'?embauche|job offer|lettre d'?offre|promesse d'?embauche")
_WEAK_POSITIVE = re.compile(r"entretien|interview|\becha?nger\b|\bechange\b|\bappel\b|\bcall\b|visio|\bmeet")
# «Если вас выберут, мы назначим интервью» is still just a receipt.
_CONDITIONAL = re.compile(r"\bsi (votre|ta) (candidature|profil)|\bsi (vous|tu) (etes|es) (retenu|selectionne)|\bif (your|you|we)\b|"
                          r"\ble cas echeant|\bdans le cas ou")
_ACK = re.compile(r"(avons|a) bien (ete )?recu|bien recu|a bien ete (recue|enregistree|transmise)|accuse de reception|"
                  r"thank(s| you) for (applying|your application|your interest)|we (have )?received your application|"
                  r"application (has been|was) (received|submitted)|merci (pour|de) (votre|ta) candidature|candidature (a bien|est bien)|"
                  r"reviendrons vers (vous|toi)|will (get back|be in touch|review)|reviewing your application|etudi(ons|er) (votre|ta) candidature")


def classify(subject: str, body: str, sender: str = "") -> str | None:
    """positive / negative / ack / other, or None when the mail is not about Mark's applications."""
    text = _plain(f"{subject}\n{body[:6000]}")
    who = _plain(sender)
    if _NOT_A_REPLY.search(text) or re.search(r"jobalerts?|jobs-listings|job-alert|alert@|newsletter", who):
        return None
    if not _JOB.search(text):
        return None
    if _NEGATIVE.search(text):
        return "negative"
    if _STRONG_POSITIVE.search(text):
        return "positive"
    if _WEAK_POSITIVE.search(text) and not _CONDITIONAL.search(text) and not _ACK.search(text):
        return "positive"
    if _ACK.search(text):
        return "ack"
    return "other"


_GENERIC_DOMAINS = {"gmail", "googlemail", "outlook", "hotmail", "yahoo", "icloud", "me", "live", "proton", "protonmail",
                    "welcometothejungle", "wttj", "lever", "greenhouse", "greenhouse-mail", "ashbyhq", "teamtailor", "workable",
                    "smartrecruiters", "recruitee", "taleo", "workday", "myworkday", "successfactors", "jobvite", "breezy",
                    "linkedin", "indeed", "hellowork", "apec", "jobteaser", "flatchr", "talent-soft", "talentsoft", "join",
                    "personio", "bamboohr", "jazzhr", "icims", "pinpointhq", "homerun", "hrflow", "notifications", "mail", "email"}


def company_of(sender: str, subject: str = "") -> str:
    """A readable company name from the From header (and the subject for job boards)."""
    match = re.match(r'\s*"?([^"<]*)"?\s*<([^>]+)>', sender or "")
    name, address = (match.group(1).strip(), match.group(2)) if match else ("", (sender or "").strip())
    name = re.sub(r"\s+(via|par|through)\s+.*$", "", name, flags=re.I)
    name = re.sub(r"^(l'?equipe|l'?équipe|team|the|equipe|équipe)\s+", "", name, flags=re.I)
    name = re.sub(r"\s*(recruiting|recrutement|recruitment|careers|talent( acquisition)?|hiring team|rh|hr|jobs|no-?reply)\s*$", "", name, flags=re.I)
    for pattern in (r"^.+?\b(?:from|de chez|chez|at|@)\s+(.+)$",):
        found = re.match(pattern, name, flags=re.I)
        if found:
            name = found.group(1)
    domain = address.rsplit("@", 1)[-1].lower() if "@" in address else ""
    parts = [part for part in domain.split(".") if part]
    base = parts[-2] if len(parts) >= 2 else ""
    if base and base not in _GENERIC_DOMAINS and (not name or "@" in name or name.lower() in {"noreply", "no-reply", "notification"}):
        name = base.capitalize()
    if not name or base in _GENERIC_DOMAINS and len(name.split()) >= 2 and name.istitle() and not re.search(r"(?i)team|recrut|talent", sender):
        # A person writing from a job board or webmail: the subject usually names the company.
        found = re.search(r"(?:chez|at|@|from|de)\s+([A-Z][\w&.\- ]{1,30})", subject or "")
        if found:
            name = found.group(1)
    return " ".join(name.split())[:60] or "Неизвестно"


def role_of(subject: str, body: str) -> str:
    text = " ".join(f"{subject} {body[:1500]}".split())
    for pattern in (r"(?:poste|position|role|r[ôo]le|offre)\s+(?:de|d'|of|as|:)?\s*[«\"“]?([A-Z][^\n«»\"“”.,!?]{2,70}?)(?:[»\"”]|,|\.| chez | at | -\s*(?:Paris|Lyon|Remote)|$)",
                    r"for (?:the|our) ([A-Z][^.,!?]{2,60}?) (?:role|position)"):
        found = re.search(pattern, text)
        if found:
            return found.group(1).strip(" -–:")[:80]
    return ""


# ─── What the site shows ───

def _week(day: str) -> str:
    try:
        year, week, _ = datetime.strptime(day[:10], "%Y-%m-%d").isocalendar()
    except ValueError:
        return ""
    return f"{year}-W{week:02d}"


def stats(replies: list[dict], *, today: datetime | None = None, weeks: int = 8) -> dict:
    today = today or datetime.now(timezone.utc)
    totals = {verdict: 0 for verdict in VERDICTS}
    by_week: dict[str, dict] = {}
    for offset in range(weeks - 1, -1, -1):
        key = _week((today - timedelta(weeks=offset)).strftime("%Y-%m-%d"))
        by_week[key] = {"week": key, **{verdict: 0 for verdict in VERDICTS}}
    companies: dict[str, dict] = {}
    for reply in replies:
        verdict = reply.get("verdict")
        if verdict not in totals:
            continue
        totals[verdict] += 1
        week = _week(str(reply.get("date") or ""))
        if week in by_week:
            by_week[week][verdict] += 1
        company = companies.setdefault(reply.get("company") or "Неизвестно", {"company": reply.get("company") or "Неизвестно",
                                                                                **{verdict: 0 for verdict in VERDICTS}, "last": ""})
        company[verdict] += 1
        company["last"] = max(company["last"], str(reply.get("date") or ""))
    decided = totals["positive"] + totals["negative"]
    return {"totals": totals, "decided": decided,
            "positive_rate": round(100 * totals["positive"] / decided) if decided else None,
            "weeks": list(by_week.values()),
            "companies": sorted(companies.values(), key=lambda row: (-row["positive"], row["last"]), reverse=False)[:40]}


def projection(root: Path | None = None, *, today: datetime | None = None) -> dict:
    """Owner-only view for the site: never the token, never mail text."""
    p = paths(root)
    token = _read(p["token"])
    status = _read(p["status"]) or {}
    saved = _read(p["replies"]) or {}
    replies = [reply for reply in saved.get("replies", []) if isinstance(reply, dict)] if isinstance(saved, dict) else []
    replies.sort(key=lambda reply: str(reply.get("date") or ""), reverse=True)
    if load_client(root) is None:
        state = "not_configured"
    elif not isinstance(token, dict) or not token.get("refresh_token"):
        state = "not_connected"
    elif status.get("ok") is False:
        state = "error"
    else:
        state = "connected"
    public_keys = ("id", "thread_id", "date", "company", "role", "subject", "verdict", "answered", "link")
    clean = [{key: reply.get(key) for key in public_keys if key in reply} for reply in replies]
    waiting = [reply for reply in clean if reply.get("verdict") == "positive" and not reply.get("answered")]
    return {"state": state, "email": token.get("email") if isinstance(token, dict) else None,
            "last_check": status.get("last_run"), "error": status.get("reason") if status.get("ok") is False else None,
            "first_scan_done": bool(saved.get("first_scan_done")) if isinstance(saved, dict) else False,
            "waiting": waiting[:20], "recent": clean[:40], "stats": stats(clean, today=today)}
