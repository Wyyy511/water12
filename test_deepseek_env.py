import os
from agent import deepseek_client as dc

def _clear():
    for k in list(os.environ):
        if "DEEPSEEK" in k.upper():
            os.environ.pop(k, None)

def test_canonical_key(monkeypatch):
    _clear()
    monkeypatch.setenv("DEEPSEEK_API_KEY","  sk-demo-canonical  ")
    assert dc.configured()
    assert dc.api_key_source()=="DEEPSEEK_API_KEY"
    assert dc.api_key_value()=="sk-demo-canonical"

def test_alias_key(monkeypatch):
    _clear()
    monkeypatch.setenv("deepseek_key","'sk-demo-alias'")
    assert dc.configured()
    assert dc.api_key_value()=="sk-demo-alias"

def test_pasted_assignment(monkeypatch):
    _clear()
    monkeypatch.setenv("DEEPSEEK_API_KEY","DEEPSEEK_API_KEY=sk-demo-pasted")
    assert dc.api_key_value()=="sk-demo-pasted"

def test_blank_model_uses_default(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_MODEL"," ")
    assert dc.model_name()=="deepseek-v4-flash"
