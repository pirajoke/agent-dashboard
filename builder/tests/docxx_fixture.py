"""Synthetic DOCXX scenarios for the isolated browser preview."""
from datetime import datetime, timezone, timedelta

def fixture(mode):
    if mode == 'anonymous': return {'state':'owner_required'}
    if mode == 'unavailable': return {'state':'unavailable'}
    now=datetime.now(timezone.utc)
    state={'waiting':'processing','failure':'attention','stale':'stale','unknown':'waiting'}.get(mode,'ready')
    result = {'state':state,'checked_at':(now-timedelta(minutes=40 if state=='stale' else 1)).isoformat(),
            'busy':state=='processing','pending':2 if state in ('processing','waiting') else 0,
            'review_count':1 if state=='attention' else 0,'catalog_count':42,'model_calls':0,
            'warnings':['Демонстрационные данные для проверки интерфейса. Это не текущие документы.'],
            'links':{'library':'https://drive.google.com/drive/folders/synthetic_library_123','review':'https://drive.google.com/drive/folders/synthetic_review_123'},
            'records_total':0 if mode=='empty' else 3,
            'records':[] if mode=='empty' else [
             {'key':'1','name':'Пример: Bulletin de paie - 2026-09.pdf','original_name':'Scan001.pdf','destination':'France / Emploi / Bulletins de paie','source':'drive','status':'verified','label':'Проверено в Google Drive','at':now.isoformat(),'historical':True,'kind':'file'},
             {'key':'2','name':'Пример: документы для проверки.pdf','original_name':'DOC002.pdf','destination':'Разобрать позже / Проверить документы','source':'review','status':'needs_review','label':'Нужен разбор','reason':'Назначение документа не определено однозначно.','at':now.isoformat(),'historical':state!='attention','kind':'file'},
             {'key':'3','name':'Пример: комплект для учёбы','original_name':'New folder','destination':'Образование / Комплекты документов','source':'drive','status':'verified','label':'Проверено в Google Drive','at':now.isoformat(),'historical':True,'kind':'folder'}]}
    if mode == 'gmail':
        result['gmail'] = {'state':'ready','automatic':True,'checked_at':now.isoformat(),'pending':0,'error':None}
        result['records'] = [dict(row, source='gmail', kind='file', status='verified',
            label='Проверено в Google Drive', historical=True,
            name='Пример: ' + title + '.pdf', original_name='original.pdf + traduction.pdf',
            destination='France / Documents de famille / ' + title + '.pdf', reason=None)
            for row, title in zip(result['records'], ('Acte de naissance', 'Acte de mariage', 'Livret de famille'))]
    return result
