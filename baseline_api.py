#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Baseline Engine API v1.2
路径匹配型水风险基准评估 —— 统一确定性计算内核（Agent 调用接口）

提供：calculate_baseline(request: dict) -> dict
      validate_baseline_request(request: dict) -> dict   （仅校验，不计算）

口径冻结（与研究报告底稿一致）：
  R = theta_WS*(WS/5)*BWD + theta_DR*DR*DYS + theta_SV*(SV/5)*CTS*OA
  C = W * R ；PRWI = ΣC ；区间见底稿2.7；证据可信度取最弱环节。
  OA 缺失不得静默设为 1；未知份额不得静默归一化；不自行补值。

版本：v1.4 | 2026-09-12 | 负责人：D（F 协助对齐 QA 与产品输出）
  v1.3 变更：field_meta.approved_proxy=true 的字段，即使值随节点/材料层显式给出
  （值本身来自已批准的代理规则，如 MH蓝水足迹P类代理规则v1），也计入 proxy_fields，
  calculation_mode 判定为 proxy。修复黄金样例2"期望 proxy、实际 strict"的不一致。
  数值计算完全不变（PRWI 与 v1.2 逐位一致）。
公式版本：path-matching-v1.1（与底稿2.2/2.6/2.7逐条对应）
依赖：baseline_calculator.py v1.1（仅复用映射规则函数，计算内核在本文件）
"""

import hashlib
import json
from datetime import datetime, timezone

from baseline_calculator import (
    map_dys_score,
    confidence_level_to_score,
    score_to_confidence_label,
)

# ----------------------------------------------------------------------
# 版本常量
# ----------------------------------------------------------------------
ENGINE_VERSION = "baseline-engine-1.4"
FORMULA_VERSION = "path-matching-v1.1"
PARAMETER_VERSION = "theta-equal-1/3;dys-map-v1;g-map-v1"
TOL = 1e-3  # 权重和/theta和容差

CRITICAL_FIELDS = ["node_id", "W", "WS", "SV", "DR"]
PARAM_FIELDS = ["BWD", "DYS", "CTS", "OA"]


def _utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _hash_request(req: dict) -> str:
    canonical = json.dumps(req, sort_keys=True, ensure_ascii=False,
                           separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _is_conflict_value(v):
    """字段是否以未解决冲突形式传入"""
    return isinstance(v, dict) and v.get("conflict") is True


# ----------------------------------------------------------------------
# 第一层：结构与范围校验（失败 -> status=error，停止计算）
# ----------------------------------------------------------------------
def _validate_request(request):
    errors = []
    if not isinstance(request, dict):
        return ["request 必须是 dict/JSON object"]
    for k in ("run_id", "enterprise_id", "materials"):
        if k not in request:
            errors.append(f"缺少必填顶层字段: {k}")
    if "materials" in request and not isinstance(request["materials"], list):
        errors.append("materials 必须是数组")
    if errors:
        return errors

    theta = request.get("theta") or {}
    t_ws, t_dr, t_sv = theta.get("WS", 1/3), theta.get("DR", 1/3), theta.get("SV", 1/3)
    for name, t in (("theta.WS", t_ws), ("theta.DR", t_dr), ("theta.SV", t_sv)):
        if not isinstance(t, (int, float)) or not (0 <= t <= 1):
            errors.append(f"{name} 必须是 0-1 数值")
    if not errors and abs(t_ws + t_dr + t_sv - 1.0) > TOL:
        errors.append(f"theta 三项之和必须=1（当前={t_ws + t_dr + t_sv:.4f}）")

    for mi, mat in enumerate(request["materials"]):
        mname = mat.get("material", f"materials[{mi}]")
        for k in ("material", "U", "nodes"):
            if k not in mat:
                errors.append(f"{mname}: 缺少必填字段 {k}")
        if errors:
            continue
        U = mat.get("U")
        if not isinstance(U, (int, float)) or not (0 <= U <= 1):
            errors.append(f"{mname}: U 必须是 0-1 数值")
        nodes = mat.get("nodes")
        if not isinstance(nodes, list) or len(nodes) == 0:
            errors.append(f"{mname}: nodes 必须是非空数组")
            continue
        sum_w = 0.0
        for ni, nd in enumerate(nodes):
            nid = nd.get("node_id", f"nodes[{ni}]") if isinstance(nd, dict) else f"nodes[{ni}]"
            if not isinstance(nd, dict):
                errors.append(f"{mname}/{nid}: 节点必须是 object")
                continue
            W = nd.get("W")
            if isinstance(W, (int, float)):
                if not (0 <= W <= 1):
                    errors.append(f"{mname}/{nid}: W={W} 越界（必须 0-1）")
                sum_w += W
            for f in ("WS", "SV", "DR", "BWD", "DYS", "CTS", "OA"):
                v = nd.get(f)
                if v is None:
                    continue
                if isinstance(v, dict) and v.get("conflict") is True:
                    continue
                if not isinstance(v, (int, float)):
                    errors.append(f"{mname}/{nid}: {f} 必须是数值/null/冲突对象")
                else:
                    hi = 5.0 if (f in ("WS", "SV") and nd.get(f + "_unit") == "aqueduct_score_0_5") else 1.0
                    if not (0 <= v <= hi + 1e-9):
                        errors.append(f"{mname}/{nid}: {f}={v} 越界（允许 0-{hi:g}）")
        has_conflict_ph = any(isinstance(nd.get(f), dict) and nd.get(f, {}).get("conflict") is True
                              for nd in nodes for f in ("W", "WS", "SV", "DR"))
        if not errors and not has_conflict_ph and abs(sum_w + mat["U"] - 1.0) > TOL:
            errors.append(f"{mname}: ΣW+U={sum_w + mat['U']:.4f}，必须=1（不得静默归一化）")
    return errors


# ----------------------------------------------------------------------
# 第二层：冲突检测（-> status=conflict，等待人工确认）
# ----------------------------------------------------------------------
def _detect_conflicts(request):
    conflicts = []
    for mat in request.get("materials", []):
        mname = mat.get("material", "?")
        for f in ("material", "U"):
            if _is_conflict_value(mat.get(f)):
                conflicts.append({"material": mname, "field": f,
                                  "candidates": mat[f].get("candidates", [])})
        for nd in mat.get("nodes", []):
            if not isinstance(nd, dict):
                continue
            nid = nd.get("node_id", "?")
            for f in ("node_id", "W", "reference_period", "WS", "SV", "DR",
                      "BWD", "DYS", "CTS", "OA"):
                if _is_conflict_value(nd.get(f)):
                    conflicts.append({"material": mname, "node_id": nid, "field": f,
                                      "candidates": nd[f].get("candidates", [])})
    return conflicts


# ----------------------------------------------------------------------
# 数值与元数据工具
# ----------------------------------------------------------------------
def _norm_hazard(v, unit):
    """WS/SV -> 0-1。默认输入已是 0-1；声明 aqueduct_score_0_5 时除以 5。"""
    if v is None or isinstance(v, dict):
        return None
    return v / 5.0 if unit == "aqueduct_score_0_5" else v


def _norm_dys(v, unit):
    """DYS -> 0-1 评分。默认已是评分；声明 loss_percent 时按冻结映射规则转换。"""
    if v is None or isinstance(v, dict):
        return None
    if unit == "loss_percent":
        return map_dys_score(v)
    return v


def _meta(container, field):
    """取字段元数据：{source_ref, data_status, confidence, approved_proxy}"""
    fm = container.get("field_meta") or {}
    m = fm.get(field) or {}
    return {
        "source_ref": m.get("source_ref"),
        "data_status": m.get("data_status"),          # V/P/A/S
        "confidence": m.get("confidence"),            # High/Medium/Low
        "approved_proxy": bool(m.get("approved_proxy", False)),
        "proxy_value": m.get("proxy_value"),          # 仅批准代理规则允许
        "assumption": bool(m.get("assumption", False)),
    }


def _min_conf(labels):
    scores = [confidence_level_to_score(x) for x in labels]
    return score_to_confidence_label(min(scores) if scores else 0)


# ----------------------------------------------------------------------
# 主入口：calculate_baseline
# ----------------------------------------------------------------------
def calculate_baseline(request: dict) -> dict:
    run_id = request.get("run_id", "UNKNOWN") if isinstance(request, dict) else "UNKNOWN"
    base = {
        "run_id": run_id,
        "input_hash": _hash_request(request) if isinstance(request, dict) else None,
        "enterprise_id": request.get("enterprise_id"),
        "data_version": request.get("data_version"),
        "engine_version": ENGINE_VERSION,
        "formula_version": FORMULA_VERSION,
        "parameter_version": PARAMETER_VERSION,
        "theta": {"WS": 1/3, "DR": 1/3, "SV": 1/3},
        "calculated_at": _utc_now(),
    }

    # ---- Layer 0a: 请求必须是 dict ----
    if not isinstance(request, dict):
        return {**base, "status": "error", "calculation_mode": "none",
                "errors": ["request 必须是 dict/JSON object"], "materials": [],
                "warnings": [], "assumptions": [], "source_refs": [],
                "missing_fields": [], "proxy_fields": [], "excluded_nodes": []}

    # ---- Layer 0b: conflict 优先于范围校验（冲突占位符不参与 ΣW+U 检查） ----
    conflicts = _detect_conflicts(request)
    if conflicts:
        return {**base, "status": "conflict", "calculation_mode": "none",
                "conflicts": conflicts, "materials": [],
                "warnings": ["存在未解决的数据冲突，已停止计算，等待人工确认"],
                "assumptions": [], "source_refs": [],
                "missing_fields": [], "proxy_fields": [], "excluded_nodes": []}

    # ---- Layer 0c: error ----
    errors = _validate_request(request)
    if errors:
        return {**base, "status": "error", "calculation_mode": "none",
                "errors": errors, "materials": [],
                "warnings": [], "assumptions": [], "source_refs": [],
                "missing_fields": [], "proxy_fields": [], "excluded_nodes": []}

    theta = request.get("theta") or {}
    t_ws, t_dr, t_sv = (theta.get("WS", 1/3), theta.get("DR", 1/3), theta.get("SV", 1/3))
    base["theta"] = {"WS": t_ws, "DR": t_dr, "SV": t_sv}

    warnings, assumptions, source_refs = [], [], set()
    mat_outputs = []
    any_proxy = False

    for mat in request["materials"]:
        mname = mat["material"]
        U = mat["U"]
        mparams = mat.get("material_params") or {}
        m_out = {
            "material": mname, "U": U,
            "procurement_coverage": None, "scored_coverage": None,
            "unknown_share": U,
            "nodes": [], "missing_fields": [], "proxy_fields": [],
            "excluded_nodes": [], "warnings": [], "assumptions": [],
        }

        # ---- Layer 2: critical / insufficient ----
        critical_missing, excluded = [], []
        active = []
        for nd in mat["nodes"]:
            nid = nd.get("node_id")
            if isinstance(nd.get("W"), (int, float)) and nd["W"] == 0:
                m_out["excluded_nodes"].append({"node_id": nid, "reason": "control_node_W=0"})
                continue
            miss = [f for f in CRITICAL_FIELDS
                    if nd.get(f) is None or (isinstance(nd.get(f), dict))]
            if miss:
                critical_missing.append({"node_id": nid, "missing": miss})
                excluded.append(nid)
            else:
                active.append(nd)

        m_out["procurement_coverage"] = round(sum(nd["W"] for nd in active) , 6) if active else 0.0

        if not active or critical_missing:
            m_out.update({
                "status": "insufficient", "calculation_mode": "unscored",
                "PRWI": None, "PRWI_lower": None, "PRWI_upper": None,
                "missing_fields": critical_missing,
                "excluded_nodes": m_out["excluded_nodes"]
                    + [{"node_id": e, "reason": "critical_field_missing"} for e in excluded],
                "warnings": ["关键字段缺失，本材料不生成正式 R/C/PRWI（Unscored）"],
            })
            mat_outputs.append(m_out)
            warnings.append(f"{mname}: insufficient，正式核心值未生成")
            continue

        # ---- Layer 3: parameter resolution + node computation ----
        node_rows = []
        for nd in active:
            nid = nd["node_id"]
            W = nd["W"]
            ws = _norm_hazard(nd.get("WS"), nd.get("WS_unit"))
            sv = _norm_hazard(nd.get("SV"), nd.get("SV_unit"))
            dr = nd.get("DR")

            mp = mat.get("material_params") or {}
            # v1.3: approved_proxy=true 表示该字段取值来自已批准的代理规则（P类），
            # 无论值写在节点层还是由 proxy_value 兜底，均属 proxy 填充，须显式披露。
            def resolve(f, node_val, meta):
                if node_val is not None and not isinstance(node_val, dict):
                    return node_val, "node", bool(meta.get("approved_proxy"))
                if mp.get(f) is not None:
                    return mp[f], "material_fallback", bool(meta.get("approved_proxy"))
                if meta.get("approved_proxy") and meta.get("proxy_value") is not None:
                    return meta["proxy_value"], "approved_proxy", True
                return None, None, False

            bwd, bwd_src, bwd_filled = resolve("BWD", nd.get("BWD"), _meta(nd, "BWD"))
            dys_raw, dys_src, dys_filled = resolve("DYS", nd.get("DYS"), _meta(nd, "DYS"))
            cts, cts_src, cts_filled = resolve("CTS", nd.get("CTS"), _meta(nd, "CTS"))
            oa, oa_src, oa_filled = resolve("OA", nd.get("OA"), _meta(nd, "OA"))

            dys = _norm_dys(dys_raw, nd.get("DYS_unit") or mp.get("DYS_unit"))

            miss_p, proxy_p = [], []
            provenance = {}
            # Procurement and hazard provenance must also be preserved.
            for hf, hv in (("W", W), ("WS", ws), ("DR", dr), ("SV", sv)):
                hm = _meta(nd, hf)
                provenance[hf] = {"data_status": hm["data_status"], "source_ref": hm["source_ref"]}
                if hm["source_ref"]:
                    source_refs.add(hm["source_ref"])
                if hm["approved_proxy"]:
                    proxy_p.append({"node_id": nid, "field": hf, "value": hv, "filled_by": "registered_proxy",
                                    "data_status": hm["data_status"], "source_ref": hm["source_ref"]})
                    any_proxy = True
                if hm["assumption"]:
                    m_out["assumptions"].append({"node_id": nid, "field": hf, "value": hv,
                                                 "data_status": hm["data_status"], "source_ref": hm["source_ref"]})
            for f, val, src, filled, unit in (
                    ("BWD", bwd, bwd_src, bwd_filled, None),
                    ("DYS", dys, dys_src, dys_filled, nd.get("DYS_unit")),
                    ("CTS", cts, cts_src, cts_filled, None),
                    ("OA", oa, oa_src, oa_filled, None)):
                m = _meta(nd if src == "node" else mat, f) if src else _meta(nd, f)
                if val is None:
                    miss_p.append(f)
                    provenance[f] = {"data_status": None, "source_ref": None}
                else:
                    provenance[f] = {"data_status": m["data_status"],
                                     "source_ref": m["source_ref"]}
                    if filled:
                        proxy_p.append({"node_id": nid, "field": f, "value": val, "filled_by": "approved_proxy",
                                        "data_status": m["data_status"],
                                        "source_ref": m["source_ref"]})
                        any_proxy = True
                    if m["assumption"]:
                        m_out["assumptions"].append({"node_id": nid, "field": f, "value": val,
                                                     "data_status": m["data_status"], "source_ref": m["source_ref"]})
                    if m["source_ref"]:
                        source_refs.add(m["source_ref"])

            p_ws = t_ws * ws * bwd if bwd is not None else None
            p_dr = t_dr * dr * dys if (dys is not None and dr is not None) else None
            p_sv = t_sv * sv * cts * oa if (cts is not None and oa is not None and sv is not None) else None

            R = (p_ws + p_dr + p_sv) if (p_ws is not None and p_dr is not None and p_sv is not None) else None
            C = W * R if R is not None else None

            conf = {
                "loc_water": _min_conf([_meta(nd, f)["confidence"] for f in ("WS", "SV", "DR")]),
                "procurement": _meta(nd, "W")["confidence"] or "Low",
            }
            conf["material_param"] = _min_conf([
                _meta(nd if bwd_src == "node" else mat, "BWD")["confidence"] if bwd is not None else "Unknown",
                _meta(nd if dys_src == "node" else mat, "DYS")["confidence"] if dys is not None else "Unknown",
                _meta(nd if cts_src == "node" else mat, "CTS")["confidence"] if cts is not None else "Unknown",
            ])
            conf["season"] = _meta(nd if oa_src == "node" else mat, "OA")["confidence"] if oa is not None else "Unknown"
            overall = _min_conf(list(conf.values()))

            node_rows.append({
                "node_id": nid, "node_name": nd.get("node_name"),
                "W": W, "status_proc": _meta(nd, "W")["data_status"],
                "WS_norm": round(ws, 6), "SV_norm": round(sv, 6), "DR": dr,
                "BWD": bwd, "DYS": dys, "CTS": cts, "OA": oa,
                "Path_WS": None if p_ws is None else round(p_ws, 6),
                "Path_DR": None if p_dr is None else round(p_dr, 6),
                "Path_SV": None if p_sv is None else round(p_sv, 6),
                "R": None if R is None else round(R, 6),
                "C": None if C is None else round(C, 6),
                "node_status": "complete" if R is not None else "partial",
                "missing_fields": miss_p, "proxy_fields": proxy_p,
                "param_provenance": provenance,
                "confidence": {**conf, "overall": overall},
            })
            m_out["missing_fields"].extend([{"node_id": nid, "field": f} for f in miss_p])
            m_out["proxy_fields"].extend(proxy_p)

        # ---- Layer 4: material summary ----
        scored = [r for r in node_rows if r["R"] is not None]
        PRWI = sum(r["C"] for r in scored) if scored else None
        scored_cov = sum(r["W"] for r in scored)

        r_mmax = (t_ws * 1 + t_dr * 1 + t_sv * 1)
        prwi_lower = PRWI if PRWI is not None else 0.0
        prwi_upper = prwi_lower + U * r_mmax

        # Material-level path contribution is Σ(W × node_path), not Σ(C).
        tot_ws = sum(r["W"] * r["Path_WS"] for r in scored if r["Path_WS"] is not None)
        tot_dr = sum(r["W"] * r["Path_DR"] for r in scored if r["Path_DR"] is not None)
        tot_sv = sum(r["W"] * r["Path_SV"] for r in scored if r["Path_SV"] is not None)
        path_total = tot_ws + tot_dr + tot_sv
        if PRWI is not None and abs(path_total - PRWI) > 1e-9:
            m_out["warnings"].append(
                f"路径贡献校验失败：Σ路径贡献={path_total:.9f}，综合风险={PRWI:.9f}"
            )

        ranked = sorted(scored, key=lambda r: r["C"], reverse=True)
        for i, r in enumerate(ranked):
            r["rank"] = i + 1
            r["contribution_share"] = round(r["C"] / PRWI, 6) if PRWI else None
        for r in node_rows:
            r.setdefault("rank", None)
            r.setdefault("contribution_share", None)

        top3 = [{"node_id": r["node_id"], "node_name": r["node_name"],
                 "C": r["C"], "share": r["contribution_share"]} for r in ranked[:3]]

        p_w = [r["W"] for r in scored]
        proc_HHI = sum(w * w for w in p_w)
        risk_HHI = sum((r["C"] / PRWI) ** 2 for r in scored) if PRWI else None

        m_out.update({
            "status": "success" if len(scored) == len(active) else "partial",
            "PRWI": None if PRWI is None else round(PRWI, 6),
            "PRWI_lower": round(prwi_lower, 6),
            "PRWI_upper": round(prwi_upper, 6),
            "scored_coverage": round(scored_cov, 6),
            "path_contribution": {"WS": round(tot_ws, 6), "DR": round(tot_dr, 6), "SV": round(tot_sv, 6)},
            "path_share": ({k: round(v / PRWI, 6) for k, v in
                            {"WS": tot_ws, "DR": tot_dr, "SV": tot_sv}.items()} if PRWI else None),
            "top_nodes": top3,
            "procurement_HHI": round(proc_HHI, 6),
            "risk_HHI": None if risk_HHI is None else round(risk_HHI, 6),
            "overall_confidence": _min_conf([r["confidence"]["overall"] for r in scored]) if scored else "Unknown",
            "nodes": node_rows,
        })

        if m_out["status"] == "partial":
            m_out["calculation_mode"] = "partial"
            m_out["warnings"].append(
                f"{len(active) - len(scored)}/{len(active)} 个活动节点参数不完整；"
                f"PRWI 仅覆盖 scored_coverage={scored_cov:.2f} 的采购权重，非完整组合值")
            warnings.append(f"{mname}: partial，{m_out['warnings'][-1]}")
        else:
            m_out["calculation_mode"] = "proxy" if m_out["proxy_fields"] else "strict"
        mat_outputs.append(m_out)

    # ---- aggregate ----
    rank = {"error": 5, "conflict": 4, "insufficient": 3, "partial": 2, "success": 1}
    worst = max((m["status"] for m in mat_outputs), key=lambda s: rank[s], default="error")
    mode_map = {"success": "strict", "partial": "proxy" if any_proxy else "partial",
                "insufficient": "unscored", "conflict": "none", "error": "none"}
    if worst == "success" and any_proxy:
        mode = "proxy"
    else:
        mode = mode_map[worst]

    return {
        **base,
        "status": worst,
        "calculation_mode": mode,
        "materials": mat_outputs,
        "missing_fields": [mf for m in mat_outputs for mf in m["missing_fields"]],
        "proxy_fields": [pf for m in mat_outputs for pf in m["proxy_fields"]],
        "excluded_nodes": [e for m in mat_outputs for e in m["excluded_nodes"]],
        "warnings": warnings,
        "assumptions": [a for m in mat_outputs for a in m["assumptions"]],
        "source_refs": sorted(source_refs),
        "summary": {
            "materials_total": len(mat_outputs),
            "materials_success": sum(1 for m in mat_outputs if m["status"] == "success"),
            "materials_partial": sum(1 for m in mat_outputs if m["status"] == "partial"),
            "materials_insufficient": sum(1 for m in mat_outputs if m["status"] == "insufficient"),
        },
    }


def validate_baseline_request(request: dict) -> dict:
    """仅校验，不计算。返回 {ok, errors, conflicts}。"""
    errors = _validate_request(request)
    conflicts = _detect_conflicts(request) if not errors else []
    return {"ok": not errors and not conflicts, "errors": errors, "conflicts": conflicts}


if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 2:
        with open(sys.argv[1], "r", encoding="utf-8") as f:
            req = json.load(f)
        print(json.dumps(calculate_baseline(req), ensure_ascii=False, indent=2))
    else:
        print("用法: python baseline_api.py <request.json>")
