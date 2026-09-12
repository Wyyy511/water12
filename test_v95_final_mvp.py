import os, math, json
import pandas as pd
from fastapi.testclient import TestClient
from server import app
from tools.baseline_tool import calculate_baseline

c=TestClient(app)

def test_v95_health():
    d=c.get("/api/health").json()
    assert d["version"]=="9.6"

def test_40_60_path_contribution_exact_and_integrity():
    df=pd.DataFrame([
        {"enterprise":"TEST","material":"甘蔗","node_id":"SC01","node_name":"广西崇左-江州-北海","purchase_weight":0.4,"year":2025},
        {"enterprise":"TEST","material":"甘蔗","node_id":"SC03","node_name":"巴西中南部(圣保罗/米纳斯吉拉斯)","purchase_weight":0.6,"year":2025},
    ])
    out=calculate_baseline(df,run_id="v95_4060")
    assert out["status"] not in {"error","conflict","insufficient"}
    s=out["data"]["summary"]
    if isinstance(s,list): s=pd.DataFrame(s)
    r=s.iloc[0]
    assert abs(float(r["PRWI"])-0.36695)<1e-6
    assert abs(float(r["path_contrib_WS"])-0.1599)<1e-6
    assert abs(float(r["path_contrib_DR"])-0.05625)<1e-6
    assert abs(float(r["path_contrib_SV"])-0.1508)<1e-6
    assert abs((float(r["path_contrib_WS"])+float(r["path_contrib_DR"])+float(r["path_contrib_SV"]))-float(r["PRWI"]))<5e-6
    assert out["integrity_checks"] and all(x["ok"] for x in out["integrity_checks"])

def test_sources_include_confirmed_registry():
    df=pd.DataFrame([
        {"enterprise":"TEST","material":"甘蔗","node_id":"SC01","node_name":"广西崇左-江州-北海","purchase_weight":1.0,"year":2025},
    ])
    out=calculate_baseline(df,run_id="v95_source")
    details=out.get("source_details") or []
    water=[x for x in details if x.get("kind")=="water_risk"][0]
    assert "World Resources Institute" in (water.get("source_org") or "")
    assert "Aqueduct40" in (water.get("original_url") or "")
    assert water.get("secondary_method_doi")=="10.1175/2009JCLI2909.1"

def test_run_record_download():
    first=c.post("/api/agent/message",data={"message":"我没有企业文件，想先看看甘蔗风险"}).json()
    sid=first["session_id"]
    c.post("/api/agent/message",data={"session_id":sid,"message":"用参考数据做初步分析",
                                     "action":"use_reference_data","material":"甘蔗"})
    r=c.get(f"/api/agent/run-record/{sid}")
    assert r.status_code==200
    d=r.json()
    assert d["waterpulse_version"]=="9.6"
    assert d["session_id"]==sid
    assert "source_details" in d
    assert "integrity_checks" in d

def test_ui_has_no_voice_and_declares_mvp_scope():
    text=open("index.html",encoding="utf-8").read()
    assert 'id="micBtn"' not in text
    assert "MVP稳定支持" in text
    assert "不可计算" in text

def test_default_scenario_menu_is_node_failure_only():
    first=c.post("/api/agent/message",data={"message":"你好"}).json()
    sid=first["session_id"]
    d=c.post("/api/agent/message",data={"session_id":sid,"action":"scenario_menu","message":"看看压力测试"}).json()
    labels=[a["label"] for a in d.get("actions",[])]
    assert any("供应地中断" in x for x in labels)
    assert not any("未来水环境" in x for x in labels)
