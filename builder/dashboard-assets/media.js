(() => {
  const root = document.getElementById('media-department');
  if (!root) return;
  const node = id => document.getElementById('media-' + id);
  let loading = false;
  async function refresh() {
    if (loading) return;
    loading = true;
    node('refresh').disabled = true;
    node('details').hidden = true;
    node('posts').replaceChildren();
    node('status').textContent = 'Проверяем…';
    try {
      const response = await fetch('/api/media', {credentials: 'same-origin', cache: 'no-store'});
      if (response.status === 401 || response.status === 403) {
        node('status').textContent = 'Требуется вход владельца'; return;
      }
      if (!response.ok) throw Error('unavailable');
      const data = await response.json();
      if (!['ready', 'stale'].includes(data.state)) {
        node('status').textContent = data.state === 'not_configured'
          ? 'Источник ещё не подключён' : 'Источник недоступен'; return;
      }
      node('details').hidden = false;
      node('status').textContent = data.state === 'stale' ? 'Данные устарели' : 'Подключено';
      const tg = data.telegram, li = data.linkedin, gen = data.generation;
      node('publishing').textContent = `Telegram: ${tg.published ?? 'нет данных'} публикаций. ` +
        `LinkedIn: ${li.states.sent ?? 0} публикаций. Автопубликация: ${li.auto_publish_enabled ? 'включена' : 'выключена'}.`;
      const hours = Array.isArray(tg.hours) ? tg.hours.map(h => `${h}:00`).join(', ') : 'нет данных';
      node('schedule').textContent = `Telegram (${tg.timezone}): ${hours}; ` +
        `${tg.schedule_enabled ? 'включено' : 'выключено'}. ` +
        (tg.next_at ? `Следующий слот: ${tg.next_at}. ` : '') +
        (li.mode === 'telegram' ? 'LinkedIn следует за успешной публикацией Telegram, когда автоматический режим включён.' :
          `LinkedIn (${li.timezone}): ${(li.hours || []).map(h => `${h}:00`).join(', ')}.`);
      node('cost').textContent = gen.total_usd == null ?
        `Полная стоимость недоступна. Учтено запросов: ${gen.requests}; оценённая часть: $${gen.priced_subtotal_usd}.` :
        `Стоимость учтённой генерации: $${gen.total_usd}; запросов: ${gen.requests}.`;
      node('rates').textContent = gen.pricing_status === 'not_configured' ?
        'Тарифы не настроены. История до включения учёта не включена.' :
        `${gen.model}: вход $${gen.input_per_million_usd}, выход $${gen.output_per_million_usd} за 1 млн токенов. ` +
        'Только редакционные черновики LinkedIn с момента включения учёта.';
      node('analytics').textContent = 'Показы, вовлечённость, клики и рост подписчиков недоступны: доступ к аналитике не подключён.';
      const ns = data.notifications || {};
      node('notifications').textContent = `Уведомления Jarvis: ${ns.state || 'нет данных'}`;
      node('observed').textContent = `Данные на ${data.observed_at}`;
      for (const post of (li.recent || []).slice(0, 20)) {
        if (!/^https:\/\/www\.linkedin\.com\/feed\/update\/urn:li:(share|ugcPost):[1-9]\d*\/$/.test(post.url || '')) continue;
        const item = document.createElement('li'), a = document.createElement('a');
        a.href = post.url; a.textContent = `Открыть пост · ${post.published_at || ''}`;
        a.target = '_blank'; a.rel = 'noopener noreferrer'; item.append(a); node('posts').append(item);
      }
    } catch (_) { node('status').textContent = 'Источник недоступен'; }
    finally { loading = false; node('refresh').disabled = false; }
  }
  node('refresh').addEventListener('click', refresh);
  refresh();
})();
