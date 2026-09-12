import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from server import app

c=TestClient(app)

def run():
    assert c.get('/api/health').status_code==200
    d=c.get('/api/demo/甘蔗').json()
    assert d['status']=='success' and d['records']
    conf=c.post('/api/confirm',json={'records':d['records'],'mapping':d['mapping'],'weight_mode':'0-1','human_confirmed':True}).json()
    assert conf['records']
    base=c.post('/api/baseline',json={'records':conf['records']}).json()
    assert base['data'] and base['data']['summary']
    sc=c.post('/api/scenario',json={'baseline':base,'scenario_type':'NodeFailure','material':'甘蔗','year':2050,'path':'BAU','failure_fraction':1.0,'inventory':0.1}).json()
    assert sc['data'] and sc['data']['scenario_type']=='NodeFailure'
    chat=c.post('/api/chat',json={'message':'如果核心节点完全断供会怎样？','validation':conf['validation'],'baseline':base,'scenario':sc}).json()
    assert chat['status']=='success' and chat['answer']
    print('PASS')
    print('PRWI',base['data']['summary'][0]['PRWI'])
    print('Scenario',sc['data']['scenario_type'],sc['data'].get('unmet_demand'))
    print('Intent',chat['intent'])

if __name__=='__main__': run()
