import json
import sys
import tempfile
from pathlib import Path
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, expect
from subprocess import Popen, PIPE

base=Path('builder')
sys.path[:0]=[str(base.resolve()),str((base/'tests').resolve())]
from dashboard_builder.personal_kanban import Board
from test_personal_kanban import Issues

dst=Path('qa-screens')
dst.mkdir(exist_ok=True)
preview=Popen([sys.executable,'-u','builder/tests/preview_command_center.py'],stdout=PIPE,text=True)
url=preview.stdout.readline().strip()
assert url.startswith('http://127.0.0.1:'),url
today=datetime.now(ZoneInfo('Europe/Paris')).date()
try:
    with tempfile.TemporaryDirectory() as d, sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path='/usr/bin/google-chrome',args=['--no-sandbox'])
        for mobile in (False,True):
            size={'width':390,'height':844} if mobile else {'width':1366,'height':865}
            page=browser.new_page(viewport=size,reduced_motion='reduce',locale='ru',color_scheme='light')
            errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            board=Board(api=Issues(),repo='owner/tasks',ledger=Path(d)/str(mobile)/'log.db')
            for key,title,project,dates in [
                ('a','Подготовить демо','Студия',{'plan':str(today)}),
                ('b','Проверить макет','Дизайн',{'due':str(today-timedelta(days=1))}),
                ('c','Согласовать сценарий','Студия',{}),
                ('d','Собрать материалы','Дизайн',{})]:
                card=board.apply('create_task',dict(title=title,project=project,source_key=key,**dates))
                if key in ('b','d'): board.apply('update_task',dict(id=card['id'],revision=card['revision'],status='doing' if key=='b' else 'done'))
            state={'auth':True,'conflict':False}
            def route(r):
                if not state['auth']: return r.fulfill(status=403,json={})
                data=r.request.post_data_json
                if state['conflict'] and data['action']=='update_task':return r.fulfill(status=409,json={})
                return r.fulfill(json=board.apply(data['action'],data))
            page.route('**/api/kanban',route)
            page.route('**/*',lambda r:r.fallback() if r.request.url.startswith(url) else r.abort())
            page.goto(url+'?tab=tasks',wait_until='domcontentloaded')
            tab=page.locator('.cc-main-nav [aria-controls="section-tasks"]')
            expect(tab).to_have_attribute('aria-pressed','true')
            expect(page.locator('#kb-todo-count')).to_have_text('2')
            expect(page.locator('#kb-doing-count')).to_have_text('1')
            assert not page.locator('#kb-archive').evaluate('e => e.open')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(dst/('section-mobile.png' if mobile else 'section-desktop.png')))
            if mobile:
                page.locator('.kb-switch [data-lane=doing]').click()
                expect(page.locator('#kb-doing')).to_be_visible()
                expect(page.locator('#kb-todo')).to_be_hidden()
                page.screenshot(path=str(dst/'section-mobile-doing.png'))
                page.locator('.kb-switch [data-lane=todo]').click()
            if not mobile:
                page.locator('#cc-theme-toggle').click()
                expect(page.locator('html')).to_have_attribute('data-theme','dark')
                page.screenshot(path=str(dst/'section-dark.png'))
                page.locator('#cc-theme-toggle').click()
            first=page.locator('.kb-card').filter(has_text='Подготовить демо')
            state['conflict']=True
            first.get_by_role('button',name='Начать').click()
            expect(page.locator('#kb-message')).to_contain_text('изменилась')
            state['conflict']=False
            first.get_by_role('button',name='Начать').click()
            expect(page.locator('#kb-doing-count')).to_have_text('2')
            first.get_by_role('checkbox').focus()
            page.keyboard.press('Space')
            expect(page.locator('#kb-done-count')).to_have_text('2')
            page.locator('#kb-archive summary').click()
            first.get_by_role('checkbox').click()
            expect(page.locator('#kb-todo-count')).to_have_text('2')
            page.locator('#kb-filter').select_option('Дизайн')
            page.locator('#kb-view').select_option('overdue')
            expect(page.locator('#kb-todo .kb-card')).to_have_count(0)
            expect(page.locator('#kb-doing .kb-card')).to_have_count(1)
            page.locator('#kb-add').click()
            page.get_by_label('Название задачи').fill('Проверить прототип')
            page.locator('#kb-form button[type=submit]').click()
            expect(page.locator('#kb-todo-count')).to_have_text('3')
            page.locator('.cc-main-nav [aria-controls="section-work"]').click()
            expect(page.locator('#kb-board')).to_be_hidden()
            tab.click()
            expect(page.locator('#kb-todo-count')).to_have_text('3')
            state['auth']=False
            page.locator('#kb-refresh').click()
            expect(page.locator('#kb-message')).to_contain_text('Войди')
            expect(page.locator('#section-tasks .kb-card')).to_have_count(0)
            expect(page.locator('#kb-add')).to_be_disabled()
            assert not errors, errors
            print('PASS',size,flush=True)
            page.close()
        browser.close()
finally:
    preview.terminate()
