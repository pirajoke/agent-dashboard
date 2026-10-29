"""Owner-only, bounded projection of the news bot's read-only media export."""
from __future__ import annotations

import json
import os
import sqlite3
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def media_projection(environment=None):
    env = os.environ if environment is None else environment
    url = env.get('MEDIA_SOURCE_URL', '').rstrip('/')
    token = env.get('MEDIA_EXPORT_TOKEN', '')
    parsed = urlsplit(url)
    safe = parsed.scheme == 'https' or (parsed.scheme == 'http' and
            parsed.hostname in {'127.0.0.1', 'localhost', '::1'})
    if not url or len(token) < 32:
        return {'state': 'not_configured'}
    if not safe or parsed.username or parsed.password or parsed.query or parsed.fragment:
        return {'state': 'invalid_configuration'}
    try:
        req = urllib.request.Request(url + '/admin/media/snapshot',
                                     headers={'Authorization': 'Bearer ' + token})
        with urllib.request.build_opener(NoRedirect).open(req, timeout=5) as response:
            raw = response.read(131073)
        if len(raw) > 131072:
            raise ValueError('oversize projection')
        data = json.loads(raw)
        if data.get('schema') != 'media_department_v1':
            raise ValueError('invalid schema')
        observed = datetime.fromisoformat(data['observed_at'])
        if observed.tzinfo is None:
            raise ValueError('timezone required')
        age = (datetime.now(timezone.utc) - observed).total_seconds()
        allowed = {
            'telegram': ('published', 'schedule_enabled', 'timezone', 'hours', 'next_at'),
            'linkedin': ('states', 'auto_publish_enabled', 'preview_enabled', 'editorial_enabled',
                         'mode', 'timezone', 'hours', 'recent'),
            'generation': ('scope', 'requests', 'input_tokens', 'output_tokens', 'priced_requests',
                           'priced_subtotal_usd', 'total_usd', 'pricing_status', 'model',
                           'input_per_million_usd', 'output_per_million_usd'),
            'analytics': ('status', 'reason', 'impressions', 'engagement', 'clicks', 'follower_growth'),
        }
        result = {key: {field: data[key].get(field) for field in fields}
                  for key, fields in allowed.items()}
        result.update(state='stale' if age > 300 or age < -60 else 'ready',
                      observed_at=data['observed_at'])
        result['notifications'] = notification_status(env.get('MEDIA_NOTIFICATIONS_DB', ''))
        return result
    except Exception:
        return {'state': 'unavailable'}


def notification_status(raw):
    if not raw:
        return {'state': 'not_configured'}
    try:
        path = Path(raw).expanduser().resolve()
        connection = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
        try:
            counts = dict(connection.execute(
                'SELECT state, COUNT(*) FROM media_receipts GROUP BY state').fetchall())
        finally:
            connection.close()
        return {'state': 'reconcile_required' if counts.get('reconcile_required')
                or counts.get('sending') else 'ready', 'counts': counts}
    except (OSError, sqlite3.Error):
        return {'state': 'unavailable'}


def build_media_html():
    # Static/public builds contain no operational data. The owner endpoint fills this shell.
    return '''
<section class="section" id="media-department" aria-labelledby="media-title">
  <div class="section-head">
    <h2 class="section-title" id="media-title">Медиаотдел</h2>
    <span id="media-status" role="status">Требуется вход владельца</span>
    <button type="button" id="media-refresh" class="command-refresh">Обновить</button>
  </div>
  <div id="media-details" hidden>
    <div class="command-layout">
      <article class="command-system-card"><h3>Публикации и расписание</h3>
        <p id="media-publishing"></p><p id="media-schedule"></p></article>
      <article class="command-system-card"><h3>Стоимость генерации</h3>
        <p id="media-cost"></p><p id="media-rates"></p></article>
      <article class="command-system-card"><h3>Traction и уведомления</h3>
        <p id="media-analytics"></p><p id="media-notifications"></p></article>
    </div>
    <p id="media-observed"></p>
    <ul id="media-posts" aria-label="Последние публикации LinkedIn"></ul>
  </div>
</section>'''
