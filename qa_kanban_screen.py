import json, sys, tempfile
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
base=Path.cwd()/'builder'
(Path.cwd()/'qa-screens').mkdir(exist_ok=True)
sys.path[:0]=[str(base),str(base/'tests')]
from dashboard_builder.personal_kanban import Board
from test_personal_kanban import Issues
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
today=datetime.now(ZoneInfo('Europe/Paris')).date()
with tempfile.TemporaryDirectory() as d, sync_playwright() as pw:
    browser=pw.chromium.launch(executable_path='/usr/bin/google-chrome',args=['--no-sandbox'])
    for mobile in (False,True):
        board=Board(api=Issues(),repo='owner/tasks',ledger=Path(d)/str(mobile)/'log.db')
        a=board.apply('create_task',dict(source_key='a',title='Подготовить демо',project='Студия',plan=str(today)))
        b=board.apply('create_task',dict(source_key='b',title='Проверить макет',project='Дизайн',due=str(today-timedelta(days=1))))
        board.apply('update_task',dict(id=b['id'],revision=b['revision'],status='doing'))
        size={'width':390,'height':844} if mobile else {'width':1280,'height':800}
        page=browser.new_page(viewport=size,locale='ru',color_scheme='light',reduced_motion='reduce')
        errors=[]; page.on('pageerror',lambda e:errors.append(str(e)))
        auth=[True]
        def route(req):
            if req.request.url.endswith('/api/kanban'):
                if not auth[0]: return req.fulfill(status=401,body='{}')
                payload=req.request.post_data_json
                answer=board.apply(payload['action'],payload)
                return req.fulfill(content_type='application/json',body=json.dumps(answer))
            req.fulfill(content_type='text/html; charset=utf-8',body=(base/'dashboard-assets/kanban.html').read_text())
        page.route('http://localhost/**',route)
        page.goto('http://localhost/kanban')
        expect(page.get_by_text('Сделать · 1')).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        page.screenshot(path='qa-screens/kanban-'+('mobile' if mobile else 'desktop')+'.png',full_page=True)
        page.get_by_text('Начать',exact=True).click()
        expect(page.get_by_text('В процессе · 2')).to_be_visible()
        page.get_by_role('checkbox',name='Завершить задачу Подготовить демо').click()
        page.locator('summary').click()
        expect(page.get_by_role('checkbox',name='Вернуть задачу Подготовить демо')).to_be_visible()
        page.get_by_role('checkbox',name='Вернуть задачу Подготовить демо').click()
        expect(page.get_by_text('Сделать · 1')).to_be_visible()
        page.get_by_label('Название задачи').fill('Новый пункт')
        page.get_by_role('button',name='Добавить',exact=True).click()
        expect(page.get_by_text('Сделать · 2')).to_be_visible()
        page.locator('#view').select_option('overdue');expect(page.locator('article')).to_have_count(1)
        page.locator('#view').select_option('day');expect(page.locator('article')).to_have_count(1)
        page.locator('#filter').select_option('Дизайн');expect(page.locator('article')).to_have_count(0)
        auth[0]=False;page.locator('#reload').click()
        expect(page.get_by_role('status')).to_contain_text('Войди');expect(page.locator('article')).to_have_count(0)
        assert not errors,errors
        page.close();print('Passed',size)
    browser.close()
