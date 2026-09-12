import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from server import app

c=TestClient(app)

def test_agent_status_and_template():
    assert c.get('/api/agent/status').status_code==200
    assert c.get('/api/template').status_code==200

def test_conversational_demo_auto_baseline_and_scenario():
    r=c.post('/api/agent/message',data={'action':'use_demo','material':'甘蔗','message':'用甘蔗示范数据分析'}).json()
    assert r['status']=='success'
    assert r.get('result_summary',{}).get('baseline')
    sid=r['session_id']
    s=c.post('/api/agent/message',data={'session_id':sid,'action':'run_scenario','scenario_type':'NodeFailure','message':'核心节点失效'}).json()
    assert s['status']=='success'
    assert s.get('result_summary',{}).get('scenario')
    assert c.get('/api/agent/report/'+sid).status_code==200

def test_no_data_does_not_fake_score():
    r=c.post('/api/agent/message',data={'message':'帮我算正式PRWI'}).json()
    assert r['status'] in {'needs_input','success'}
    # A text-only request must not return a fabricated numeric result card.
    assert not r.get('result_summary')
