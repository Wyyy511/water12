from __future__ import annotations
import importlib.util
import sys
from pathlib import Path
from typing import Any
import pandas as pd
import json, math
from core.paths import ENGINE_DIR
from tools.query_adapter import lookup_water_risk, lookup_material_parameters

# Load D's frozen deterministic API. Its internal import expects the engine directory on sys.path.
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))
spec = importlib.util.spec_from_file_location("d_baseline_api", ENGINE_DIR / "baseline_api.py")
dapi = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dapi)


_SOURCE_REGISTRY_PATH = Path(__file__).resolve().parents[1] / "data" / "source_registry.json"
def _source_registry():
    try:
        return json.loads(_SOURCE_REGISTRY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"sources":{}}

def _source_meta(key: str):
    return ((_source_registry().get("sources") or {}).get(key) or {}).copy()

def _integrity_checks(out: dict, tol: float = 5e-6) -> dict:
    """Fail closed if path/node contribution decomposition does not reconcile."""
    checks=[]
    data=out.get("data")
    if data is None:
        out["integrity_checks"]=checks
        return out
    s=data.get("summary"); n=data.get("nodes")
    if isinstance(s,list): s=pd.DataFrame(s)
    if isinstance(n,list): n=pd.DataFrame(n)
    failed=[]
    if s is not None and not getattr(s, "empty", True):
        for _,r in s.iterrows():
            mat=r.get("material")
            total=r.get("PRWI")
            vals=[r.get("path_contrib_WS"),r.get("path_contrib_DR"),r.get("path_contrib_SV")]
            if total is not None and all(v is not None and not pd.isna(v) for v in vals):
                path_sum=float(sum(float(v) for v in vals))
                ok=abs(path_sum-float(total)) <= tol
                share_sum=(path_sum/float(total)) if float(total)!=0 else (1.0 if path_sum==0 else float("inf"))
                checks.append({"material":mat,"check":"path_contribution_sum","ok":ok,
                               "total_risk":float(total),"path_sum":path_sum,"share_sum":share_sum})
                if not ok or (float(total)!=0 and abs(share_sum-1.0)>tol):
                    failed.append(f"{mat}: 三条风险来源贡献与综合风险不一致")
            if n is not None and not getattr(n,"empty",True) and "material" in n.columns and "C" in n.columns and total is not None:
                gn=n[n["material"]==mat]
                node_sum=float(pd.to_numeric(gn["C"],errors="coerce").fillna(0).sum())
                ok2=abs(node_sum-float(total)) <= tol
                checks.append({"material":mat,"check":"node_contribution_sum","ok":ok2,
                               "total_risk":float(total),"node_sum":node_sum})
                if not ok2:
                    failed.append(f"{mat}: 节点贡献之和与综合风险不一致")
    out["integrity_checks"]=checks
    if failed:
        out["status"]="error"
        out["data_gaps"]=list(dict.fromkeys((out.get("data_gaps") or [])+failed))
        out["warnings"]=list(dict.fromkeys((out.get("warnings") or [])+["内部一致性校验失败；已停止展示错误结果。"]))
        out["data"]=None
    return out


def _status_flags(data_status):
    status=str(data_status or '').upper().strip()
    return ('P' in status), (status == 'S' or 'A' in status)


def _meta(source_ref=None, data_status=None, confidence=None, approved_proxy=None, proxy_value=None, assumption=None):
    pflag, aflag = _status_flags(data_status)
    return {
        "source_ref": source_ref,
        "data_status": data_status,
        "confidence": confidence,
        "approved_proxy": pflag if approved_proxy is None else bool(approved_proxy),
        "proxy_value": proxy_value,
        "assumption": aflag if assumption is None else bool(assumption),
    }


def build_baseline_request(df: pd.DataFrame, *, run_id: str = "agent_run", data_version: str = "integrated-mvp-2026-09-06") -> tuple[dict, list[str]]:
    warnings: list[str] = []
    if df is None or df.empty:
        return {"run_id": run_id, "enterprise_id": "USER_ENTERPRISE", "data_version": data_version, "materials": []}, ["没有已确认采购数据"]

    enterprise = str(df.iloc[0].get("enterprise") or "USER_ENTERPRISE")
    materials = []
    for mat, g in df.groupby("material", dropna=False):
        mat = str(mat or "").strip()
        if not mat:
            continue
        weights = pd.to_numeric(g["purchase_weight"], errors="coerce")
        sum_w = float(weights.fillna(0).sum())
        U = max(0.0, 1.0 - sum_w)
        mp = lookup_material_parameters(mat)
        mpd = mp.get("data") or {}
        warnings.extend(mp.get("warnings", []))
        m_field_meta = {}
        for f in ["BWD", "DYS", "CTS", "OA"]:
            m_field_meta[f] = _meta(
                source_ref=mpd.get("source_ref"),
                data_status=(mpd.get("data_type") or {}).get(f),
                confidence=(mpd.get("confidence") or {}).get(f),
            )
        nodes = []
        for _, r in g.iterrows():
            nid = str(r.get("node_id") or "").strip()
            wr = lookup_water_risk(nid)
            wrd = wr.get("data") or {}
            warnings.extend(wr.get("warnings", []))
            vals = wrd.get("values") or {}
            def value(name):
                return (vals.get(name) or {}).get("value")
            nd = {
                "node_id": nid or None,
                "node_name": str(r.get("node_name") or wrd.get("node_name") or ""),
                "reference_period": wrd.get("reference_period") or str(r.get("year") or ""),
                "W": None if pd.isna(r.get("purchase_weight")) else float(r.get("purchase_weight")),
                "WS": value("WS"), "WS_unit": "aqueduct_score_0_5",
                "SV": value("SV"), "SV_unit": "aqueduct_score_0_5",
                "DR": value("DR"),
                "field_meta": {
                    "W": _meta(source_ref="user_confirmed_input", data_status="V", confidence=str(r.get("confidence") or "High")),
                    "WS": _meta(source_ref=wrd.get("source_ref"), data_status=wrd.get("data_type"), confidence=wrd.get("confidence")),
                    "SV": _meta(source_ref=wrd.get("source_ref"), data_status=wrd.get("data_type"), confidence=wrd.get("confidence")),
                    "DR": _meta(source_ref=wrd.get("source_ref"), data_status=wrd.get("data_type"), confidence=wrd.get("confidence")),
                },
                "source_detail": {
                    "node_id": nid or None, "node_name": wrd.get("node_name") or str(r.get("node_name") or ""),
                    "pfaf_id": wrd.get("pfaf_id"), "reference_period": wrd.get("reference_period"),
                    "source_ref": wrd.get("source_ref"), "data_release_id": wr.get("data_release_id"),
                    "data_type": wrd.get("data_type"), "confidence": wrd.get("confidence"),
                    "source_org": _source_meta("hazard_ws_sv").get("source_org"),
                    "original_url": _source_meta("hazard_ws_sv").get("original_url"),
                    "method_doi": _source_meta("hazard_ws_sv").get("method_doi"),
                    "secondary_source_org": _source_meta("hazard_dr").get("source_org"),
                    "secondary_method_doi": _source_meta("hazard_dr").get("method_doi"),
                    "provenance_note": "WS/SV 参考 WRI Aqueduct 4.0；DR 参考 SPEI v2.0。节点最终值以项目冻结主数据表为准。",
                    "source_status": "project_registered_reference; exact upstream download record pending final B-source table",
                },
            }
            nodes.append(nd)
        materials.append({
            "material": mat,
            "U": U,
            "material_params": {
                "BWD": mpd.get("BWD"), "DYS": mpd.get("DYS"), "CTS": mpd.get("CTS"), "OA": mpd.get("OA"),
            },
            "field_meta": m_field_meta,
            "source_detail": {
                "source_ref": mpd.get("source_ref"), "data_release_id": mp.get("data_release_id"),
                "data_type": mpd.get("data_type"), "confidence": mpd.get("confidence"),
                "reference_period": None,
                "source_org": _source_meta("material_bwd").get("source_org"),
                "original_url": _source_meta("material_bwd").get("original_url"),
                "method_doi": _source_meta("material_bwd").get("method_doi"),
                "secondary_source_org": (_source_meta("sugarcane_vulnerability").get("source_org") if mat=="甘蔗" else None),
                "secondary_method_doi": (_source_meta("sugarcane_vulnerability").get("method_doi") if mat=="甘蔗" else None),
                "provenance_note": ("甘蔗材料参数来自 C 组证据表；BWD 参考全球水足迹研究，DYS/CTS 参考甘蔗水分胁迫文献；OA=0.75 为 S 类演示假设。"
                                    if mat=="甘蔗" else
                                    "材料参数来自 C 组证据表；BWD 有全球水足迹研究支撑，具体 DYS/CTS/OA 原始条目仍以 C 组最终证据表为准。"),
                "source_status": "project_registered_reference; per-parameter final citation pending C-source freeze",
            },
            "nodes": nodes,
        })
    request = {
        "run_id": run_id,
        "enterprise_id": enterprise,
        "data_version": data_version,
        "theta": {"WS": 1/3, "DR": 1/3, "SV": 1/3},
        "materials": materials,
    }
    return request, list(dict.fromkeys(warnings))


def _wrapper_from_d(raw: dict, request: dict, extra_warnings: list[str]) -> dict:
    rows = []
    summaries = []
    req_node_meta = {}
    for mat in request.get("materials", []):
        for nd in mat.get("nodes", []):
            req_node_meta[(mat.get("material"), nd.get("node_id"))] = nd
    for m in raw.get("materials", []):
        path = m.get("path_contribution") or {}
        summaries.append({
            "material": m.get("material"), "enterprise": raw.get("enterprise_id"),
            "PRWI": m.get("PRWI"), "KnownRisk": m.get("PRWI"),
            "R_max": 1.0, "PRWI_lower": m.get("PRWI_lower"), "PRWI_upper": m.get("PRWI_upper"),
            "Coverage": m.get("procurement_coverage"), "scored_coverage": m.get("scored_coverage"),
            "unknown_share_U": m.get("unknown_share"),
            "path_contrib_WS": path.get("WS", 0), "path_contrib_DR": path.get("DR", 0), "path_contrib_SV": path.get("SV", 0),
            "n_nodes": len(m.get("nodes", [])), "overall_confidence": m.get("overall_confidence"),
            "calculation_mode": m.get("calculation_mode"),
        })
        for nd in m.get("nodes", []):
            source = req_node_meta.get((m.get("material"), nd.get("node_id")), {})
            paths = {"WS": nd.get("Path_WS"), "DR": nd.get("Path_DR"), "SV": nd.get("Path_SV")}
            dom = max(paths, key=lambda k: paths[k] if paths[k] is not None else -1)
            rows.append({
                "material": m.get("material"), "enterprise": raw.get("enterprise_id"),
                "node_id": nd.get("node_id"), "node_name": nd.get("node_name"), "pfaf_id": None,
                "data_type": (source.get("field_meta") or {}).get("WS", {}).get("data_status"),
                "ws_norm": nd.get("WS_norm"), "sv_norm": nd.get("SV_norm"), "dr": nd.get("DR"),
                "bwd": nd.get("BWD"), "dys": nd.get("DYS"), "cts": nd.get("CTS"), "oa": nd.get("OA"),
                "weight": nd.get("W"), "path_ws": nd.get("Path_WS"), "path_dr": nd.get("Path_DR"), "path_sv": nd.get("Path_SV"),
                "R": nd.get("R"), "C": nd.get("C"), "dominant_path": dom,
                "overall_confidence": (nd.get("confidence") or {}).get("overall"),
                "contribution_share": nd.get("contribution_share"), "rank_contribution": nd.get("rank"), "rank_risk": None,
                "status": nd.get("node_status"),
            })
    nodes = pd.DataFrame(rows)
    if not nodes.empty:
        nodes["rank_risk"] = nodes.groupby("material")["R"].rank(ascending=False, method="min")
    summary = pd.DataFrame(summaries)
    source_details=[]
    for mat in request.get("materials", []):
        if mat.get("source_detail"):
            source_details.append({"kind":"material_parameter","material":mat.get("material"), **mat["source_detail"]})
        for nd in mat.get("nodes", []):
            if nd.get("source_detail"):
                source_details.append({"kind":"water_risk","material":mat.get("material"), **nd["source_detail"]})
    proxy_fields=raw.get("proxy_fields") or []
    assumptions=raw.get("assumptions") or []
    data_identity={
        "has_proxy":bool(proxy_fields), "has_assumption":bool(assumptions),
        "label":"含代理/假设" if (proxy_fields or assumptions) else "当前输入未标记代理/假设",
        "note":"完整公式计算仅表示字段足够运行公式，不代表所有输入均为真实企业核验值。",
    }
    return {
        "status": raw.get("status"),
        "calculation_mode": raw.get("calculation_mode"),
        "data": None if raw.get("status") in {"error", "conflict", "insufficient"} and not summaries else {"summary": summary, "nodes": nodes, "raw": raw},
        "warnings": list(dict.fromkeys((raw.get("warnings") or []) + extra_warnings)),
        "data_gaps": raw.get("missing_fields") or raw.get("errors") or raw.get("conflicts") or [],
        "source_refs": raw.get("source_refs") or [],
        "source_details": source_details,
        "proxy_fields": proxy_fields,
        "assumptions": assumptions,
        "data_identity": data_identity,
        "data_version": raw.get("data_version"),
        "model_version": raw.get("engine_version"),
        "engine_version": raw.get("engine_version"),
        "formula_version": raw.get("formula_version"),
        "parameter_version": raw.get("parameter_version"),
        "input_hash": raw.get("input_hash"),
        "run_id": raw.get("run_id"),
        "raw": raw,
    }


def calculate_baseline(df: pd.DataFrame, *, run_id: str = "agent_run") -> dict:
    request, warnings = build_baseline_request(df, run_id=run_id)
    raw = dapi.calculate_baseline(request)
    out = _wrapper_from_d(raw, request, warnings)
    out["request"] = request
    return _integrity_checks(out)
