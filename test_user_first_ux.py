import os
from fastapi.testclient import TestClient
from server import app
c=TestClient(app)
def test_text_only_question_is_user_friendly(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY",raising=False)
    d=c.post('/api/agent/message',data={'message':'请帮我分析中国大豆的上游水风险是怎么样的？'}).json()
    assert d['status']=='success'
    text=d.get('message','')
    for x in ['Baseline','Scenario','PRWI','Schema','JSON']:
        assert x not in text
    assert '上传' in text or '采购' in text
def test_health_v87():
    d=c.get('/api/health').json()
    assert d['version']=='9.6'
    assert d['deployment_layout']=='server-self-healing'
