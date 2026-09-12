"""
baseline_water_risk.py
路径匹配型基准评估模块 v2.0
交付人：D（吴家宝）｜接收人：E（牛晨羽）、F（渠颖颖）
交付日期：2026-09-06｜版本：v2.0

依据：研究报告工作底稿(2) 第2.2–2.8节公式
公式：R = θWS·(WS_score/5)·BWD + θDR·DR·DYS + θSV·(SV_score/5)·CTS·OA
      C = W·R；PRWI = ΣC；PRWI区间 = [KnownRisk, KnownRisk + U·R_max]
"""

import json
from typing import Dict, List, Any, Optional

# ============================================================================
# 1. 输入数据（内嵌，确保可独立运行）
# ============================================================================

# --- 1.1 Hazard地点水危险（B交DF v1.1）---
HAZARD_DATA = {
    "SC01": {"name": "广西崇左-江州-北海", "ws_score": 3.72, "sv_score": 3.58,
             "dr": 0.30, "data_type": "V", "confidence": "High", "pfaf_id": "pfaf_1123"},
    "SC02": {"name": "云南梁河", "ws_score": 3.24, "sv_score": 3.12,
             "dr": 0.35, "data_type": "V", "confidence": "High", "pfaf_id": "pfaf_1156"},
    "SC03": {"name": "巴西中南部(圣保罗/米纳斯吉拉斯)", "ws_score": 2.85, "sv_score": 2.64,
             "dr": 0.25, "data_type": "P", "confidence": "Medium", "pfaf_id": "pfaf_5214"},
    "SC04": {"name": "泰国东北部(呵叻/孔敬)", "ws_score": 3.51, "sv_score": 3.75,
             "dr": 0.28, "data_type": "P", "confidence": "Medium", "pfaf_id": "pfaf_3207"},
    "SC05": {"name": "古巴中部(马坦萨斯)", "ws_score": 3.06, "sv_score": 2.91,
             "dr": 0.22, "data_type": "P", "confidence": "Medium", "pfaf_id": "pfaf_5602"},
    "SC06": {"name": "澳大利亚昆士兰北部", "ws_score": 4.08, "sv_score": 2.37,
             "dr": 0.42, "data_type": "P", "confidence": "Medium", "pfaf_id": "pfaf_6308"},
    "SB01": {"name": "新疆新源-昭苏", "ws_score": 4.23, "sv_score": 2.04,
             "dr": 0.55, "data_type": "V", "confidence": "High", "pfaf_id": "pfaf_2104"},
    "SB02": {"name": "内蒙古河套(巴彦淖尔)", "ws_score": 3.87, "sv_score": 2.46,
             "dr": 0.48, "data_type": "V", "confidence": "High", "pfaf_id": "pfaf_2207"},
    "SB03": {"name": "黑龙江齐齐哈尔", "ws_score": 2.52, "sv_score": 2.73,
             "dr": 0.32, "data_type": "V", "confidence": "High", "pfaf_id": "pfaf_2301"},
    "SB04": {"name": "河北张家口(坝上)", "ws_score": 3.36, "sv_score": 2.58,
             "dr": 0.41, "data_type": "V", "confidence": "High", "pfaf_id": "pfaf_2115"},
    "SB05": {"name": "甘肃张掖(河西走廊)", "ws_score": 4.01, "sv_score": 2.15,
             "dr": 0.52, "data_type": "V", "confidence": "High", "pfaf_id": "pfaf_2122"},
    "SY01": {"name": "巴西马托格罗索州", "ws_score": 2.31, "sv_score": 2.28,
             "dr": 0.20, "data_type": "P", "confidence": "Medium", "pfaf_id": "pfaf_5227"},
    "SY02": {"name": "美国中西部(爱荷华/伊利诺伊)", "ws_score": 3.04, "sv_score": 2.85,
             "dr": 0.27, "data_type": "P", "confidence": "Medium", "pfaf_id": "pfaf_7103"},
    "SY03": {"name": "阿根廷潘帕斯(布宜诺斯艾利斯)", "ws_score": 2.47, "sv_score": 2.41,
             "dr": 0.23, "data_type": "P", "confidence": "Medium", "pfaf_id": "pfaf_5302"},
    "SY04": {"name": "加拿大萨斯喀彻温省", "ws_score": 2.03, "sv_score": 2.17,
             "dr": 0.18, "data_type": "P", "confidence": "Medium", "pfaf_id": "pfaf_7205"},
    "SY05": {"name": "俄罗斯远东(阿穆尔/滨海边疆)", "ws_score": 2.68, "sv_score": 2.62,
             "dr": 0.24, "data_type": "P", "confidence": "Medium", "pfaf_id": "pfaf_4108"},
}

# --- 1.2 月度WS（B岗补充数据包2 v2.0）---
MONTHLY_WS = {
    "SC01": [3.35,3.52,3.78,4.01,4.23,4.30,4.25,4.02,3.70,3.42,3.21,3.14],
    "SC02": [2.87,3.02,3.25,3.48,3.65,3.72,3.68,3.45,3.20,2.98,2.82,2.76],
    "SC03": [2.55,2.42,2.61,2.87,3.12,3.25,3.30,3.21,3.02,2.78,2.60,2.48],
    "SC04": [3.72,3.85,3.98,3.82,3.56,3.21,3.05,3.12,3.38,3.65,3.78,3.70],
    "SC05": [3.25,3.38,3.42,3.31,3.10,2.87,2.75,2.82,2.98,3.15,3.28,3.32],
    "SC06": [3.62,3.48,3.75,4.02,4.35,4.52,4.58,4.45,4.21,3.90,3.68,3.55],
    "SB01": [4.52,4.65,4.58,4.32,4.10,3.95,3.88,3.95,4.18,4.35,4.48,4.55],
    "SB02": [4.12,4.25,4.18,3.95,3.72,3.58,3.52,3.60,3.82,4.00,4.15,4.22],
    "SB03": [2.75,2.82,2.78,2.60,2.42,2.30,2.25,2.32,2.48,2.62,2.72,2.78],
    "SB04": [3.62,3.75,3.68,3.45,3.22,3.08,3.02,3.10,3.28,3.45,3.58,3.65],
    "SB05": [4.32,4.45,4.38,4.12,3.88,3.72,3.65,3.75,3.98,4.18,4.32,4.38],
    "SY01": [2.05,1.92,2.10,2.35,2.60,2.72,2.78,2.68,2.48,2.25,2.08,1.98],
    "SY02": [3.25,3.38,3.32,3.10,2.88,2.75,2.68,2.78,2.98,3.15,3.28,3.35],
    "SY03": [2.20,2.08,2.25,2.50,2.72,2.85,2.90,2.80,2.60,2.38,2.22,2.12],
    "SY04": [2.25,2.32,2.28,2.10,1.92,1.80,1.75,1.82,1.98,2.12,2.22,2.28],
    "SY05": [2.92,3.00,2.95,2.75,2.55,2.42,2.35,2.45,2.62,2.78,2.88,2.95],
}

# --- 1.3 极端干旱DR_ED（B岗补充数据包2 v2.0）---
EXTREME_DR = {
    "SC01": {"dr_ed": 0.72, "months": 12, "basin": "珠江流域"},
    "SC02": {"dr_ed": 0.78, "months": 14, "basin": "澜沧江流域"},
    "SC03": {"dr_ed": 0.65, "months": 10, "basin": "巴拉那河流域"},
    "SC04": {"dr_ed": 0.68, "months": 11, "basin": "湄公河流域"},
    "SC05": {"dr_ed": 0.60, "months": 9, "basin": "古巴岛内水系"},
    "SC06": {"dr_ed": 0.85, "months": 16, "basin": "墨累-达令流域"},
    "SB01": {"dr_ed": 0.90, "months": 18, "basin": "伊犁河流域"},
    "SB02": {"dr_ed": 0.82, "months": 15, "basin": "黄河流域"},
    "SB03": {"dr_ed": 0.68, "months": 11, "basin": "黑龙江流域"},
    "SB04": {"dr_ed": 0.75, "months": 13, "basin": "海河流域"},
    "SB05": {"dr_ed": 0.88, "months": 17, "basin": "黑河流域"},
    "SY01": {"dr_ed": 0.58, "months": 8, "basin": "亚马逊南部流域"},
    "SY02": {"dr_ed": 0.65, "months": 10, "basin": "密西西比河流域"},
    "SY03": {"dr_ed": 0.62, "months": 9, "basin": "拉普拉塔河流域"},
    "SY04": {"dr_ed": 0.55, "months": 7, "basin": "哈德逊湾流域"},
    "SY05": {"dr_ed": 0.66, "months": 10, "basin": "阿穆尔河流域"},
}

# --- 1.4 Exposure采购结构（B交DF v1.1）---
EXPOSURE_DATA = {
    "甘蔗": {
        "SC01": {"W": 0.25, "U": 0.00, "confidence": "Low"},
        "SC02": {"W": 0.10, "U": 0.00, "confidence": "Low"},
        "SC03": {"W": 0.45, "U": 0.00, "confidence": "Low"},
        "SC04": {"W": 0.12, "U": 0.00, "confidence": "Low"},
        "SC05": {"W": 0.04, "U": 0.00, "confidence": "Low"},
        "SC06": {"W": 0.04, "U": 0.00, "confidence": "Low"},
    },
    "甜菜": {
        "SB01": {"W": 0.70, "U": 0.00, "confidence": "Low"},
        "SB02": {"W": 0.15, "U": 0.00, "confidence": "Low"},
        "SB03": {"W": 0.10, "U": 0.00, "confidence": "Low"},
        "SB04": {"W": 0.05, "U": 0.00, "confidence": "Low"},
        "SB05": {"W": 0.00, "U": 0.00, "confidence": "Low"},
    },
    "大豆": {
        "SY01": {"W": 0.65, "U": 0.00, "confidence": "Low"},
        "SY02": {"W": 0.20, "U": 0.00, "confidence": "Low"},
        "SY03": {"W": 0.10, "U": 0.00, "confidence": "Low"},
        "SY04": {"W": 0.05, "U": 0.00, "confidence": "Low"},
        "SY05": {"W": 0.00, "U": 0.00, "confidence": "Low"},
    },
}

# --- 1.5 材料参数（C部分材料水风险参数初步证据表）---
MATERIAL_PARAMS = {
    "甘蔗": {
        "BWD": 0.75, "BWD_confidence": "Medium",
        "DYS_min": 0.25, "DYS_mid": 0.625, "DYS_max": 1.00,
        "DYS_confidence": "High",
        "CTS": 1.00, "CTS_confidence": "High",
        "OA": 0.75, "OA_confidence": "Low",  # S类假设，待补充
    },
    "甜菜": {
        "BWD": 0.80, "BWD_confidence": "Medium",
        "DYS_min": 0.25, "DYS_mid": 0.625, "DYS_max": 1.00,
        "DYS_confidence": "High",
        "CTS": 1.00, "CTS_confidence": "High",
        "OA": 0.75, "OA_confidence": "Low",
    },
    "大豆": {
        "BWD": 0.85, "BWD_confidence": "Medium",
        "DYS_min": 0.50, "DYS_mid": 0.75, "DYS_max": 1.00,
        "DYS_confidence": "High",
        "CTS": 1.00, "CTS_confidence": "High",
        "OA": 0.75, "OA_confidence": "Low",
    },
}

ENTERPRISE_MAP = {
    "甘蔗": "DEMO_A(制糖示范企业)",
    "甜菜": "DEMO_A(制糖示范企业)",
    "大豆": "DEMO_B(植物蛋白示范企业)",
}

# 路径权重（底稿2.2：第一版基准θ=1/3）
DEFAULT_THETA = {"WS": 1/3, "DR": 1/3, "SV": 1/3}

# 可信度数值映射（用于最弱环节规则）
CONFIDENCE_RANK = {"High": 3, "Medium": 2, "Low": 1}


# ============================================================================
# 2. 核心计算函数
# ============================================================================

def calculate_node_risk(node_id: str, material: str,
                        scenario: str = "neutral",
                        theta: Optional[Dict[str, float]] = None,
                        oa_override: Optional[float] = None) -> Dict[str, Any]:
    """
    计算单个节点的风险强度R和三路径分量。
    公式（底稿2.2）：
      R = θWS·(WS_score/5)·BWD + θDR·DR·DYS + θSV·(SV_score/5)·CTS·OA
    """
    h = HAZARD_DATA[node_id]
    p = MATERIAL_PARAMS[material]
    t = theta if theta is not None else DEFAULT_THETA

    dys = p["DYS_mid"] if scenario == "neutral" else (
          p["DYS_max"] if scenario == "conservative" else
          p["DYS_min"] if scenario == "optimistic" else p["DYS_mid"])
    oa = oa_override if oa_override is not None else p["OA"]

    ws_norm = h["ws_score"] / 5.0
    sv_norm = h["sv_score"] / 5.0

    r_ws = t["WS"] * ws_norm * p["BWD"]
    r_dr = t["DR"] * h["dr"] * dys
    r_sv = t["SV"] * sv_norm * p["CTS"] * oa
    node_risk = r_ws + r_dr + r_sv

    path_vals = {"WS": r_ws, "DR": r_dr, "SV": r_sv}
    dominant = max(path_vals, key=path_vals.get)

    return {
        "node_id": node_id,
        "node_name": h["name"],
        "pfaf_id": h["pfaf_id"],
        "data_type": h["data_type"],
        "R_WS": round(r_ws, 6),
        "R_DR": round(r_dr, 6),
        "R_SV": round(r_sv, 6),
        "Node_Risk": round(node_risk, 6),
        "dominant_path": dominant,
        "ws_norm": round(ws_norm, 4),
        "sv_norm": round(sv_norm, 4),
        "dr": h["dr"],
        "dys_used": dys,
        "oa_used": oa,
    }


def calculate_material_baseline(material: str,
                                  scenario: str = "neutral",
                                  theta: Optional[Dict[str, float]] = None,
                                  oa_override: Optional[float] = None) -> Dict[str, Any]:
    """
    计算材料级Baseline：PRWI、路径贡献、节点贡献、PRWI区间、覆盖率、证据可信度。
    公式（底稿2.6–2.7）：
      C = W·R；PRWI = ΣC；ContributionShare = C / PRWI
      KnownRisk = ΣW·R；R_max = θWS·BWD + θDR·DYS + θSV·CTS
      PRWI_lower = KnownRisk；PRWI_upper = KnownRisk + U·R_max
      Coverage = 1 − U
    """
    t = theta if theta is not None else DEFAULT_THETA
    p = MATERIAL_PARAMS[material]
    nodes = EXPOSURE_DATA[material]

    dys = p["DYS_mid"] if scenario == "neutral" else (
          p["DYS_max"] if scenario == "conservative" else
          p["DYS_min"] if scenario == "optimistic" else p["DYS_mid"])
    oa = oa_override if oa_override is not None else p["OA"]

    node_results = []
    path_ws = path_dr = path_sv = 0.0
    known_risk = 0.0
    total_u = 0.0

    # 材料参数综合可信度 = 最弱环节
    material_conf = min([p["BWD_confidence"], p["DYS_confidence"], p["CTS_confidence"]],
                        key=lambda x: CONFIDENCE_RANK[x])
    seasonal_conf = p["OA_confidence"]

    for node_id, exp in nodes.items():
        w = exp["W"]
        u = exp["U"]
        total_u += u
        if w == 0:
            continue

        nr = calculate_node_risk(node_id, material, scenario, t, oa)
        c = w * nr["Node_Risk"]
        c_ws = w * nr["R_WS"]
        c_dr = w * nr["R_DR"]
        c_sv = w * nr["R_SV"]

        path_ws += c_ws
        path_dr += c_dr
        path_sv += c_sv
        known_risk += c

        hazard_conf = HAZARD_DATA[node_id]["confidence"]
        exposure_conf = exp["confidence"]
        overall_conf = min([hazard_conf, exposure_conf, material_conf, seasonal_conf],
                          key=lambda x: CONFIDENCE_RANK[x])

        node_results.append({
            **nr,
            "weight": w,
            "unknown": u,
            "contrib": round(c, 6),
            "contrib_WS": round(c_ws, 6),
            "contrib_DR": round(c_dr, 6),
            "contrib_SV": round(c_sv, 6),
            "hazard_confidence": hazard_conf,
            "exposure_confidence": exposure_conf,
            "material_confidence": material_conf,
            "seasonal_confidence": seasonal_conf,
            "overall_confidence": overall_conf,
        })

    prwi = path_ws + path_dr + path_sv
    for nr in node_results:
        nr["contrib_pct"] = round(nr["contrib"] / prwi * 100, 2) if prwi > 0 else 0.0
    node_results.sort(key=lambda x: x["contrib"], reverse=True)

    # R_max（底稿2.7）
    r_max = t["WS"] * p["BWD"] + t["DR"] * dys + t["SV"] * p["CTS"]
    prwi_lower = known_risk
    prwi_upper = known_risk + total_u * r_max
    coverage = 1.0 - total_u

    return {
        "material": material,
        "enterprise": ENTERPRISE_MAP[material],
        "scenario": scenario,
        "theta": t,
        "params": {
            "BWD": p["BWD"], "DYS": dys, "CTS": p["CTS"], "OA": oa,
            "BWD_confidence": p["BWD_confidence"],
            "DYS_confidence": p["DYS_confidence"],
            "CTS_confidence": p["CTS_confidence"],
            "OA_confidence": p["OA_confidence"],
        },
        "PRWI": round(prwi, 6),
        "PRWI_lower": round(prwi_lower, 6),
        "PRWI_upper": round(prwi_upper, 6),
        "path_contrib_WS": round(path_ws, 6),
        "path_contrib_DR": round(path_dr, 6),
        "path_contrib_SV": round(path_sv, 6),
        "known_risk": round(known_risk, 6),
        "R_max": round(r_max, 6),
        "coverage": round(coverage, 4),
        "total_unknown": round(total_u, 4),
        "nodes": node_results,
    }


def calculate_baseline_all(scenario: str = "neutral",
                             theta: Optional[Dict[str, float]] = None,
                             oa_override: Optional[float] = None) -> Dict[str, Any]:
    """计算全部三材料的Baseline结果。"""
    results = {}
    for material in ["甘蔗", "甜菜", "大豆"]:
        results[material] = calculate_material_baseline(material, scenario, theta, oa_override)
    return results


# ============================================================================
# 3. 输出格式化
# ============================================================================

def format_summary(results: Dict[str, Any]) -> str:
    """生成人类可读的结果摘要。"""
    lines = ["=" * 65, "路径匹配型基准评估结果 (PRWI)", "=" * 65]
    for mat, res in results.items():
        lines.append(f"\n【{mat}】{res['enterprise']}")
        lines.append(f"  场景:{res['scenario']} | θWS={res['theta']['WS']:.3f} θDR={res['theta']['DR']:.3f} θSV={res['theta']['SV']:.3f}")
        lines.append(f"  PRWI={res['PRWI']:.6f}  [下限={res['PRWI_lower']:.6f}, 上限={res['PRWI_upper']:.6f}]")
        lines.append(f"  路径贡献: WS={res['path_contrib_WS']:.6f} | DR={res['path_contrib_DR']:.6f} | SV={res['path_contrib_SV']:.6f}")
        lines.append(f"  覆盖率={res['coverage']*100:.0f}% | R_max={res['R_max']:.6f}")
        lines.append("  节点贡献排名:")
        for i, n in enumerate(res["nodes"], 1):
            lines.append(f"    {i}. {n['node_name']}({n['node_id']}): R={n['Node_Risk']:.6f} "
                         f"C={n['contrib']:.6f}({n['contrib_pct']:.2f}%) 主导={n['dominant_path']} 证据={n['overall_confidence']}")
    return "\n".join(lines)


# ============================================================================
# 4. 主程序
# ============================================================================

if __name__ == "__main__":
    scenario_input = "neutral"
    baseline_results = calculate_baseline_all(scenario_input)

    print("\n【JSON输出】")
    print(json.dumps(baseline_results, indent=2, ensure_ascii=False))

    print("\n【文本摘要】")
    print(format_summary(baseline_results))
