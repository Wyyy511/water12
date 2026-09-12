import os
from fastapi.testclient import TestClient
from server import app

c=TestClient(app)

def _msg(text, action="", material="", sid=""):
    data={"message":text,"action":action,"material":material,"session_id":sid}
    return c.post("/api/agent/message",data=data).json()

def test_concept_question_without_file_gets_real_answer(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY",raising=False)
    d=_msg("什么是供应链水风险？")
    assert d["status"]=="success"
    assert "供应链水风险" in d["message"]
    assert not d["message"].startswith("可以继续做更贴近你企业实际采购情况")

def test_material_question_without_file_uses_reference_context(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY",raising=False)
    d=_msg("甘蔗的上游水风险主要看什么？")
    assert d["status"]=="success"
    assert "甘蔗" in d["message"]
    assert d.get("reference_scope",{}).get("material_supported") is True
    labels=[x.get("label") for x in d.get("actions",[])]
    assert "用参考数据做初步分析" in labels
    assert "查看当前可参考的供应地区" in labels

def test_unsupported_material_still_answers_without_fake_numbers(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY",raising=False)
    d=_msg("玉米上游水风险有哪些？")
    assert d["status"]=="success"
    assert "玉米" in d["message"]
    assert "不会编造" in d["message"] or "不" in d["message"]
    assert d.get("reference_scope",{}).get("material_supported") is False

def test_reference_data_action_runs_without_user_file(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY",raising=False)
    first=_msg("我没有企业文件，想先看看甘蔗风险")
    sid=first["session_id"]
    d=_msg("用参考数据做初步分析",action="use_reference_data",material="甘蔗",sid=sid)
    assert d["status"] in {"success","partial"}
    assert "参考分析说明" in d["message"]
    assert d.get("result_summary",{}).get("baseline") is not None

def test_reference_locations_action(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY",raising=False)
    first=_msg("我想了解大豆")
    sid=first["session_id"]
    d=_msg("查看当前可参考的供应地区",action="show_reference_locations",material="大豆",sid=sid)
    assert d["status"]=="success"
    assert "大豆" in d["message"]
    assert "巴西马托格罗索州" in d["message"]
