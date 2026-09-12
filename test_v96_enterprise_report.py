from pathlib import Path
import pandas as pd
from tools.baseline_tool import calculate_baseline
from tools.export_tool import export_risk_report

def _b():
    df=pd.DataFrame([
        {"enterprise":"Demo Food Co.","material":"甘蔗","node_id":"SC01","node_name":"广西崇左-江州-北海","purchase_weight":0.4,"year":2025},
        {"enterprise":"Demo Food Co.","material":"甘蔗","node_id":"SC03","node_name":"巴西中南部(圣保罗/米纳斯吉拉斯)","purchase_weight":0.6,"year":2025},
    ])
    return calculate_baseline(df,run_id="v96")

def test_enterprise_report_output():
    p=export_risk_report(_b(),None,None,"snap_v96")
    assert Path(p).exists()
    assert "Enterprise_Water_Risk_Report" in Path(p).name

def test_enterprise_sections_present():
    src=Path("export_tool.py").read_text(encoding="utf-8")
    for x in ["执行摘要","当前上游供应链水风险","AI 风险评估与管理建议","压力测试与供应链韧性","建议企业优先采取的行动","数据来源、限制与可追溯信息"]:
        assert x in src

def test_server_uses_enterprise_export_label():
    src=Path("server.py").read_text(encoding="utf-8")
    assert "导出企业水风险报告" in src
    assert "下载企业水风险报告" in src
