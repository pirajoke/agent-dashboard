import asyncio, os, tempfile, sys, json
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
ghsrc = """#!/usr/bin/env python3
import sys, json, pathlib, os
db=pathlib.Path(os.environ['HOME'])/'remote.json'
rows=json.loads(db.read_text()) if db.exists() else {}
method=sys.argv[sys.argv.index('-X')+1]; path=sys.argv[sys.argv.index('-X')+2]
if path=='user': value={'login':'demo'}
elif path=='repos/demo/HQ': value={'private':True}
elif '?' in path: value=[i for i in rows.values() if 'state=all' in path or i['state']=='open']
elif method=='POST':
    ident=str(len(rows)+1); value=dict(json.load(sys.stdin), number=int(ident),state='open'); rows[ident]=value
else:
    value=rows[path.rsplit('/',1)[1]]
    if method=='PATCH': value.update(json.load(sys.stdin))
db.write_text(json.dumps(rows));print(json.dumps(value))
"""
def unpack(r):
    assert not r.isError,r
    if r.structuredContent is not None: return r.structuredContent.get('result',r.structuredContent)
    return [json.loads(v.text) for v in r.content]
async def verify():
    with tempfile.TemporaryDirectory() as tmp:
        path=Path(tmp);gh=path/'gh';gh.write_text(ghsrc);gh.chmod(0o700)
        script=str(Path.cwd()/'builder'/'dashboard_builder'/'kanban_mcp.py')
        env=dict(os.environ,PATH=tmp+':'+os.environ['PATH'],HOME=tmp)
        async with stdio_client(StdioServerParameters(command=sys.executable,args=[script],env=env)) as (read,write):
            async with ClientSession(read,write) as client:
                await client.initialize()
                assert {t.name for t in (await client.list_tools()).tools}=={'list_tasks','create_task','update_task'}
                today=datetime.now(ZoneInfo('Europe/Paris')).date()
                kwargs=dict(title='Integration test',source_key='voice:local:42',plan=str(today),due=str(today-timedelta(days=1)))
                async def call(name,**kw):
                    v=unpack(await client.call_tool(name,kw))
                    if name!='list_tasks' and isinstance(v,list) and len(v)==1: return v[0]
                    return v
                a=await call('create_task',**kwargs);assert (await call('create_task',**kwargs))['id']==a['id']
                for v in ['day','overdue','open']: assert len(await call('list_tasks',view=v))==1
                b=await call('update_task',id=a['id'],revision=a['revision'],status='doing')
                c=await call('update_task',id=b['id'],revision=b['revision'],status='done')
                assert not await call('list_tasks',view='open')
                assert len(await call('list_tasks',view='all'))==1
                assert (await call('update_task',id=c['id'],revision=c['revision'],status='todo'))['status']=='todo'
                print('MCP stdio: initialization, discovery, create/retry, views, status and reopen passed')
asyncio.run(verify())
