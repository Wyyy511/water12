from pathlib import Path
import pandas as pd
from fastapi.testclient import TestClient
from server import app
from tools.baseline_tool import calculate_baseline
from tools.scenario_tool import run_scenario

c=TestClient(app)

def case_df():
    return pd.DataFrame([
        {"enterprise":"示例企业","material":"甘蔗","node_id":"SC01","node_name":"广西崇左-江州-北海","purchase_weight":0.4,"year":2025,"source_type":"V","confidence":"High"},
        {"enterprise":"示例企业","material":"甘蔗","node_id":"SC03","node_name":"巴西中南部(圣保罗/米纳斯吉拉斯)","purchase_weight":0.6,"year":2025,"source_type":"V","confidence":"High"},
    ])

def test_path_contribution_4060_exact():
    out=calculate_baseline(case_df(),run_id="audit4060"); r=out["data"]["summary"].iloc[0]
    assert abs(r.PRWI-0.36695)<1e-6
    assert abs(r.path_contrib_WS-0.1599)<1e-6
    assert abs(r.path_contrib_DR-0.05625)<1e-6
    assert abs(r.path_contrib_SV-0.1508)<1e-6
    assert abs((r.path_contrib_WS+r.path_contrib_DR+r.path_contrib_SV)-r.PRWI)<1e-9
    assert abs(r.path_contrib_WS/r.PRWI-0.4357542)<1e-5
    assert abs(r.path_contrib_DR/r.PRWI-0.1532906)<1e-5
    assert abs(r.path_contrib_SV/r.PRWI-0.4109552)<1e-5

def test_proxy_assumptions_sources_propagate():
    out=calculate_baseline(case_df())
    assert out["proxy_fields"] and out["assumptions"] and out["source_details"]
    assert out["data_identity"]["has_proxy"] and out["data_identity"]["has_assumption"]

def test_zero_impact_node_failure():
    b=calculate_baseline(case_df()); s=run_scenario(b,"NodeFailure","甘蔗",failure_fraction=0.0,inventory=0.10)
    assert s["status"]=="success"; assert abs(s["data"]["gross_loss"])<1e-12; assert abs(s["data"]["unmet_demand"])<1e-12

def test_no_proxy_constraint_knows_uploaded_state():
    with open("Water_Risk_Input_Template.xlsx","rb") as f:
        r=c.post("/api/agent/message",data={"message":"请分析，但不得使用任何代理值或假设。"},files={"file":("Water_Risk_Input_Template.xlsx",f,"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}).json()
    assert r["status"]=="insufficient"; assert "已经读取" in r["message"] and "2 条采购记录" in r["message"]

def test_natural_language_procurement_goes_to_confirmation():
    r=c.post("/api/agent/message",data={"message":"请分析甘蔗，SC01 40%，SC03 60%。"}).json()
    assert r["status"]=="needs_confirmation"; assert "40.0%" in r["message"] and "60.0%" in r["message"]

def test_frontend_guards_and_multimaterial_history():
    html=Path("index.html").read_text(encoding="utf-8")
    assert "if(isMissing(v))return'不可计算'" in html
    assert "return rows.map(r=>" in html
    assert "最大贡献供应地" in html and "查看来源与数据说明" in html
    assert "waterpulse_history_v2" in html
