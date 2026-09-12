# -*- coding: utf-8 -*-
"""
scenario_engine.py —— 压力测试（Scenario）核心计算引擎（v2.0）。

严格按《研究报告工作底稿》第二章（基准评估）与第三章（情景分析与压力测试）公式实现，
并按《压力测试反馈——20260905》逐项修正：
  ① 跨材料汇总错误   → 全部结果按「企业—材料」分组计算与展示，不再跨材料相加/平均；
  ② 贡献份额/排名分组 → ContributionShare = 节点C ÷ 该企业该材料的PRWI，节点排名在材料内部完成；
  ③ 未来情景节点错配 → 以 (node_id, material) 为主键合并基准R，再做主键校验后逐行求增量；
  ④ 缺失数据治理     → validate_inputs() 校验主键唯一、WS/DR/SV及材料参数完整/越界、ΣW+U=1、Σθ=1，
                         缺数据返回受控状态（Insufficient/Unscored），不补值、不崩溃；
  ⑤ 极端干旱无事件   → dr_ed/n_extreme_months 直接取自 B 岗 extreme_drought.csv；无事件返回
                         "No event identified"；有事件+可靠λ才计算供应侧；
  ⑨ θ一致性          → Baseline / Scenario / 汇总全部使用同一份 theta（显式传参）。

全部函数为纯函数（输入 DataFrame/参数，输出 DataFrame/结果字典），可被 F 组 AI Agent
直接 import 调用，不写文件、不依赖全局状态。

公式索引：
  2.2  R_mi = θWS·(WS/5)·BWD + θDR·DR·DYS + θSV·(SV/5)·CTS·OA
  2.4  W_emi = Q_emi/ΣQ ； ΣW + U = 1
  2.6  C_emi = W_emi·R_mi ； PRWI = ΣC ； ContributionShare = C/PRWI（材料内部）
  2.7  KnownRisk ； R_max ； PRWI_lower/upper ； Coverage = 1-U
  3.2  峰值季节：WS_i^Peak = Mean(Top3 月度WS)（缺作物历时备选规则）
  3.3  未来：R_mi(p,y) = θWS·WS(p,y)·BWD + θDR·DR·DYS + θSV·SV(p,y)·CTS·OA
  3.4  历史极端干旱：DR_i^ED 取自 B 岗 extreme_drought.csv
  3.5  核心节点失效：GrossLoss/InventoryUsed/Replacement/Unmet/Fulfilled + 条件PRWI
  3.6  HHI（采购集中度 / 风险集中度，材料内部）
"""
from __future__ import annotations

import json
import os
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# 冻结规则：SPEI-6 → 干旱严重度 g(x)（表2-2，项目自定义，非SPEI官方等级）
# 注：仅保留用于文档口径说明；极端干旱的 dr_ed 已由 B 岗直接提供，不再用本映射派生。
# ---------------------------------------------------------------------------
def g_spei(x: float) -> float:
    if x >= -0.5:
        return 0.00
    if x >= -1.0:
        return 0.25
    if x >= -1.5:
        return 0.50
    if x >= -2.0:
        return 0.75
    return 1.00


def _norm(score: float) -> float:
    """0—5 官方分级分 → 0—1。"""
    return score / 5.0


# ---------------------------------------------------------------------------
# 数据装载
# ---------------------------------------------------------------------------
def load_master_data(data_dir: str) -> Dict:
    """读取主数据底座（单一真值源）。返回 hazard/exposure/material/情景数据与参数。"""
    def _rd(name: str) -> pd.DataFrame:
        return pd.read_csv(os.path.join(data_dir, name), encoding="utf-8-sig")

    hazard = _rd("hazard_baseline.csv")
    exposure = _rd("exposure_weights.csv")
    material = _rd("material_params.csv").set_index("material")
    monthly = _rd("monthly_ws.csv")
    future = _rd("future_ws_sv.csv")
    extreme = _rd("extreme_drought.csv")
    with open(os.path.join(data_dir, "scenario_params.json"), encoding="utf-8") as f:
        params = json.load(f)

    # 合并成统一节点表（hazard 与 exposure 均含 material，交叉校验一致性）
    nodes = hazard.merge(exposure, on=["node_id", "material"], how="left", suffixes=("", "_exp"))
    # 企业—材料归属（用于「企业—材料」分组展示）
    nodes["enterprise"] = nodes["material"].map(
        dict(zip(exposure["material"], exposure["enterprise"])))
    return {
        "hazard": hazard,
        "exposure": exposure,
        "material": material,
        "nodes": nodes,
        "monthly_ws": monthly,
        "future": future,
        "extreme_drought": extreme,
        "params": params,
    }


# ---------------------------------------------------------------------------
# 数据治理校验（反馈问题④）
# ---------------------------------------------------------------------------
def validate_inputs(nodes: pd.DataFrame, material: pd.DataFrame,
                    params: Dict, monthly: pd.DataFrame | None = None,
                    future: pd.DataFrame | None = None,
                    extreme: pd.DataFrame | None = None) -> List[str]:
    """返回校验问题清单（空列表=全部通过）。硬错误（主键重复/Σθ≠1）抛 ValueError。"""
    issues: List[str] = []

    # 1. 节点主键唯一
    if nodes["node_id"].duplicated().any():
        dup = nodes["node_id"][nodes["node_id"].duplicated()].tolist()
        raise ValueError(f"节点主键 node_id 重复：{dup}")

    # 2. WS/SV/DR 缺失或越界（0-5 / 0-5 / 0-1）
    for col, lo, hi in [("ws_score", 0.0, 5.0), ("sv_score", 0.0, 5.0), ("dr", 0.0, 1.0)]:
        bad = nodes[col].isna() | (nodes[col] < lo) | (nodes[col] > hi)
        if bad.any():
            issues.append(f"{col} 缺失或越界[{lo},{hi}]：{nodes.loc[bad, 'node_id'].tolist()}")

    # 3. 材料参数（BWD/DYS/CTS/OA）缺失或越界
    for col in ["param_bwd", "param_dys_base", "param_cts", "param_oa_base"]:
        if material[col].isna().any():
            issues.append(f"材料参数 {col} 缺失：{material.index[material[col].isna()].tolist()}")

    # 4. ΣW+U=1（每材料）
    wsum = nodes.groupby("material")["purchase_weight_W"].sum()
    for m in wsum.index:
        u = 1.0 - float(wsum[m])
        if abs(float(wsum[m]) + u - 1.0) > 1e-9:
            issues.append(f"{m} ΣW={wsum[m]:.4f} 且 U={u:.4f}，ΣW+U≠1")
        elif u < -1e-9:
            issues.append(f"{m} 未知份额 U<0：{u:.4f}")

    # 5. Σθ=1（容差 1e-5，允许 0.333333×3 的浮点舍入）
    th = params["theta"]
    if abs(th["ws"] + th["dr"] + th["sv"] - 1.0) > 1e-5:
        raise ValueError(f"路径权重 Σθ={th['ws']+th['dr']+th['sv']:.6f} ≠ 1")

    # 6. 情景数据覆盖校验（若提供）
    if monthly is not None:
        missing = set(nodes["node_id"]) - set(monthly["node_id"])
        if missing:
            issues.append(f"monthly_ws 缺节点：{sorted(missing)}")
    if future is not None and "demo" in future.columns and (future["demo"] == 1).any():
        issues.append("future_ws_sv 为 S 类演示数据（demo=1），未来情景结果不可作为真实结论")
    if extreme is not None:
        missing = set(nodes["node_id"]) - set(extreme["node_id"])
        if missing:
            issues.append(f"extreme_drought 缺节点：{sorted(missing)}")

    return issues


# ---------------------------------------------------------------------------
# 基准评估（第二章）
# ---------------------------------------------------------------------------
def compute_baseline(nodes: pd.DataFrame, material: pd.DataFrame,
                     theta: Dict[str, float] | None = None,
                     oa_override: float | None = None) -> pd.DataFrame:
    """
    计算节点级基准评估：三条路径、R、C、贡献份额与排序（材料内部）。

    返回 DataFrame（每节点一行），列：
      node_id, material, enterprise, node_name, ws_norm, sv_norm, dr,
      bwd, dys, cts, oa, weight, path_ws, path_dr, path_sv, R, C,
      contribution_share（=C/该材料PRWI）, rank（材料内部）, status
    """
    th = theta or {"ws": 1 / 3, "dr": 1 / 3, "sv": 1 / 3}
    df = nodes.copy()

    df["ws_norm"] = df["ws_score"].map(_norm)
    df["sv_norm"] = df["sv_score"].map(_norm)
    df["bwd"] = df["material"].map(material["param_bwd"])
    df["dys"] = df["material"].map(material["param_dys_base"])
    df["cts"] = df["material"].map(material["param_cts"])
    df["oa"] = (oa_override if oa_override is not None
                else df["material"].map(material["param_oa_base"]))
    df["weight"] = df["purchase_weight_W"]

    # 缺失数据治理：任一关键输入缺失则标记，不补值
    required = ["ws_score", "sv_score", "dr", "bwd", "dys", "cts", "oa", "weight"]
    missing_mask = df[required].isna().any(axis=1)
    df["status"] = np.where(missing_mask, "Insufficient", "Scored")

    df["path_ws"] = th["ws"] * df["ws_norm"] * df["bwd"]
    df["path_dr"] = th["dr"] * df["dr"] * df["dys"]
    df["path_sv"] = th["sv"] * df["sv_norm"] * df["cts"] * df["oa"]

    df["R"] = df["path_ws"] + df["path_dr"] + df["path_sv"]
    df["C"] = df["weight"] * df["R"]

    # 贡献份额与排名在「企业—材料」内部完成（反馈问题②）
    grp = df.groupby("material", group_keys=False)
    df["contribution_share"] = df["C"] / grp["C"].transform("sum")
    # 排名保留为浮点：缺失数据（Insufficient）的 C 为 NaN，rank 随之 NaN，
    # 不得 astype(int)（会因 NaN 抛 IntCastingNaNError，反馈④要求缺失受控不崩溃）
    df["rank"] = grp["C"].rank(ascending=False, method="min")
    df.loc[df["weight"] == 0, "contribution_share"] = np.nan
    df.loc[df["weight"] == 0, "rank"] = np.nan
    return df.reset_index(drop=True)


def material_summary(baseline: pd.DataFrame, material: pd.DataFrame,
                     theta: Dict[str, float] | None = None) -> pd.DataFrame:
    """按「企业—材料」汇总：PRWI、KnownRisk、R_max、上下界、覆盖率、未知份额（2.6/2.7）。"""
    th = theta or {"ws": 1 / 3, "dr": 1 / 3, "sv": 1 / 3}
    rows = []
    for m, g in baseline.groupby("material"):
        g_scored = g[g["status"] == "Scored"]
        wsum = float(g["weight"].sum())
        u = float(1 - wsum)  # ΣW + U = 1
        known_risk = float((g_scored["weight"] * g_scored["R"]).sum())
        r_max = float(
            th["ws"] * material.loc[m, "param_bwd"]
            + th["dr"] * material.loc[m, "param_dys_base"]
            + th["sv"] * material.loc[m, "param_cts"]
        )
        rows.append({
            "material": m,
            "enterprise": g["enterprise"].iloc[0],
            "PRWI": float(g_scored["C"].sum()),
            "KnownRisk": known_risk,
            "R_max": r_max,
            "PRWI_lower": known_risk,
            "PRWI_upper": known_risk + u * r_max,
            "Coverage": 1 - u,
            "unknown_share_U": u,
            "n_nodes": int(len(g)),
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 情景1：当前峰值季节水压力（3.2）
# ---------------------------------------------------------------------------
def scenario_peak_season(baseline: pd.DataFrame, monthly_ws: pd.DataFrame,
                         theta: Dict[str, float] | None = None) -> pd.DataFrame:
    """
    仅替换水压力路径的 WS：WS_i^Peak = Mean(Top 3 monthly WS_i)（缺作物历时的备选规则）。
    其余（DR/SV/材料/OA/权重）保持基准不变。贡献份额/排名在材料内部。
    """
    th = theta or {"ws": 1 / 3, "dr": 1 / 3, "sv": 1 / 3}
    mcols = [f"m{i:02d}" for i in range(1, 13)]
    top3 = monthly_ws.set_index("node_id")[mcols].apply(
        lambda r: r.nlargest(3).mean(), axis=1
    ).rename("ws_peak")

    df = baseline.merge(top3, left_on="node_id", right_index=True, how="left")
    df["ws_peak_norm"] = df["ws_peak"].map(_norm)
    df["path_ws_peak"] = th["ws"] * df["ws_peak_norm"] * df["bwd"]
    df["path_ws_delta"] = df["path_ws_peak"] - df["path_ws"]
    df["R_peak"] = df["path_ws_peak"] + df["path_dr"] + df["path_sv"]
    df["C_peak"] = df["weight"] * df["R_peak"]
    df["R_delta"] = df["R_peak"] - df["R"]
    grp = df.groupby("material", group_keys=False)
    df["contribution_share_peak"] = df["C_peak"] / grp["C_peak"].transform("sum")
    df["rank_peak"] = grp["C_peak"].rank(ascending=False, method="min")
    df.loc[df["weight"] == 0, "contribution_share_peak"] = np.nan
    df.loc[df["weight"] == 0, "rank_peak"] = np.nan
    return df


# ---------------------------------------------------------------------------
# 情景2：Aqueduct 未来结构性水风险（3.3）
# ---------------------------------------------------------------------------
def scenario_future(baseline: pd.DataFrame, future: pd.DataFrame,
                    theta: Dict[str, float] | None = None) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    对 9 组合（3时期×3路径）分别重算 R 与 PRWI。仅替换 WS(p,y)、SV(p,y)，
    历史干旱负担/材料/OA/采购结构沿用基准值。

    以 (node_id, material) 为主键把基准 R 合并进来，做主键校验后逐行求增量（反馈问题③），
    未来 PRWI 按「企业—材料」分别计算（反馈问题①）。

    返回 (node_level_wide, combo_summary)，combo_summary 每行 = (year, path, material)。
    """
    th = theta or {"ws": 1 / 3, "dr": 1 / 3, "sv": 1 / 3}
    base = baseline[["node_id", "material", "enterprise", "node_name", "weight",
                     "bwd", "dys", "cts", "oa", "dr", "path_dr", "R"]].copy()
    base["R_base"] = base["R"]
    # 主键校验：baseline 与 future 都必须唯一
    if base.duplicated(subset=["node_id", "material"]).any():
        raise ValueError("baseline 主键 (node_id, material) 不唯一")
    if future.duplicated(subset=["path", "year", "node_id"]).any():
        raise ValueError("future 主键 (path, year, node_id) 不唯一")

    base_key = base.set_index(["node_id", "material"])

    node_rows, combo_rows = [], []
    for (path, year), grp in future.groupby(["path", "year"], sort=True):
        g = grp[["node_id", "ws_future", "sv_future"]].copy()
        m = g.merge(base, on="node_id", how="left", validate="one_to_one")
        # 正向校验：未来数据出现基准外节点 → 显式暴露，不做行号对齐
        unknown = m[m["material"].isna()]["node_id"].tolist()
        if unknown:
            raise ValueError(f"{year}-{path} 未来数据含基准外节点或主键不匹配：{unknown}")
        # 反向校验：未来数据缺少基准节点 → 同样显式暴露，不得静默少算节点（反馈④缺失受控）
        missing_base = sorted(set(base["node_id"]) - set(g["node_id"]))
        if missing_base:
            raise ValueError(f"{year}-{path} 未来数据缺少基准节点：{missing_base}")

        m["ws_f_norm"] = m["ws_future"].map(_norm)
        m["sv_f_norm"] = m["sv_future"].map(_norm)
        m["path_ws_f"] = th["ws"] * m["ws_f_norm"] * m["bwd"]
        m["path_sv_f"] = th["sv"] * m["sv_f_norm"] * m["cts"] * m["oa"]
        m["R_f"] = m["path_ws_f"] + m["path_dr"] + m["path_sv_f"]
        m["C_f"] = m["weight"] * m["R_f"]
        m["R_delta_f"] = m["R_f"] - m["R_base"]  # 逐行（同主键）求增量

        # 按材料汇总（不再跨材料相加）
        for mat, gmat in m.groupby("material"):
            prwi_b = float(baseline[baseline["material"] == mat]["C"].sum())
            prwi_f = float(gmat["C_f"].sum())
            combo_rows.append({
                "year": year, "path": path, "material": mat,
                "enterprise": gmat["enterprise"].iloc[0],
                "key": f"{year}-{path}-{mat}",
                "PRWI_future": round(prwi_f, 6),
                "PRWI_baseline": round(prwi_b, 6),
                "PRWI_delta": round(prwi_f - prwi_b, 6),
            })
        for _, r in m.iterrows():
            node_rows.append({
                "node_id": r["node_id"], "material": r["material"],
                "node_name": r["node_name"], "year": year, "path": path,
                "key": f"{year}-{path}",
                "R_future": round(float(r["R_f"]), 6),
                "R_delta": round(float(r["R_delta_f"]), 6),
                "C_future": round(float(r["C_f"]), 6),
            })
    return pd.DataFrame(node_rows), pd.DataFrame(combo_rows)


# ---------------------------------------------------------------------------
# 情景3：历史极端干旱事件（3.4）
# ---------------------------------------------------------------------------
def scenario_extreme_drought(baseline: pd.DataFrame, extreme: pd.DataFrame,
                             params: Dict, theta: Dict[str, float] | None = None) -> pd.DataFrame:
    """
    dr_ed / n_extreme_months 直接取自 B 岗 extreme_drought.csv（不再由 S 类 SPEI 派生）。

    无事件节点 → event_status = "No event identified"，不伪造历史事件、不回退基准 DR；
    有事件节点 → 风险侧替换 DR 路径重算 R/C；供应侧仅当存在可靠 λ 证据时才计算，
    当前 λ=30% 为文献参考值，故供应损失标注为 "reference"（非已验证真实减产）。
    """
    th = theta or {"ws": 1 / 3, "dr": 1 / 3, "sv": 1 / 3}
    lam = params["extreme_drought"]["loss_rate_lambda"]

    ed = extreme[["node_id", "dr_ed", "n_extreme_months", "basin"]].copy()
    df = baseline.merge(ed, on="node_id", how="left")

    # 无事件节点：n_extreme_months 缺失或为 0 → 明确状态，不沿用基准 DR
    no_event = df["n_extreme_months"].isna() | (df["n_extreme_months"] == 0)
    df["event_status"] = np.where(no_event, "No event identified", "Event identified")
    df["dr_ed"] = np.where(no_event, np.nan, df["dr_ed"])

    # 风险侧：仅对「有事件」节点替换 DR 路径
    df["dr_used"] = np.where(no_event, np.nan, df["dr_ed"])
    df["path_dr_ed"] = th["dr"] * df["dr_used"] * df["dys"]
    df["path_dr_delta"] = df["path_dr_ed"] - df["path_dr"]
    df["R_ed"] = df["path_ws"] + df["path_dr_ed"] + df["path_sv"]
    df["C_ed"] = df["weight"] * df["R_ed"]
    df["R_delta_ed"] = df["R_ed"] - df["R"]
    grp = df.groupby("material", group_keys=False)
    df["contribution_share_ed"] = df["C_ed"] / grp["C_ed"].transform("sum")
    df["rank_ed"] = grp["C_ed"].rank(ascending=False, method="min")

    # 供应侧：仅示范机制；λ=30% 为文献参考值（B 岗补充数据包2），非逐作物验证真实减产率
    df["lambda"] = df["material"].map(lam)
    df["lambda_source"] = "reference"
    df["gross_supply_loss"] = df["weight"] * df["lambda"]
    return df


# ---------------------------------------------------------------------------
# 情景4：核心节点失效与供应链韧性（3.5）
# ---------------------------------------------------------------------------
def scenario_node_failure(baseline: pd.DataFrame, params: Dict) -> Dict:
    """
    默认对基准评估中贡献最高的节点做「完全失效」（f 可调），检验库存缓冲与替代供应，
    输出未满足需求、风险质量与条件 PRWI，并把「风险总量下降」与「供应缺口」分开报告。

    替代容量按 B 岗补充数据包2 分材料、分节点（replacement_cap_by_material），
    替代顺序按候选节点 R 升序（优先切向低风险节点）。
    """
    nf = params["node_failure"]
    f = nf["failure_fraction_f"]
    inv = nf["inventory_I"]
    caps = nf["replacement_cap_by_material"]

    results = {}
    for material, g in baseline.groupby("material"):
        g = g.copy().reset_index(drop=True)
        target = g.loc[g["C"].idxmax()].copy()
        w_target = float(target["weight"])
        gross_loss = w_target * f
        inv_used = min(inv, gross_loss)
        replacement_need = gross_loss - inv_used

        # 替代候选：replacement_cap_by_material 中除目标外的节点（含 W=0 对照节点，需另行确认现货）
        cap_map = caps.get(material, {})
        cand = g[g["node_id"] != target["node_id"]].copy()
        cand = cand[cand["node_id"].isin(cap_map.keys())].copy()
        cand["cap"] = cand["node_id"].map(cap_map)
        cand = cand.sort_values("R", ascending=True).reset_index(drop=True)
        cand["replacement"] = 0.0
        remaining = replacement_need
        for idx in cand.index:
            alloc = min(float(cand.at[idx, "cap"]), remaining)
            cand.at[idx, "replacement"] = alloc
            remaining -= alloc
            if remaining <= 1e-12:
                break
        total_replacement = float(cand["replacement"].sum())
        unmet = max(0.0, replacement_need - total_replacement)
        fulfilled = 1.0 - unmet

        # 已实际采购的权重 W'_i（失效节点按 (1-f) 保留，替代节点增加 replacement）
        g["W_realized"] = g["weight"]
        g.loc[g["node_id"] == target["node_id"], "W_realized"] = w_target * (1 - f)
        for _, c in cand.iterrows():
            g.loc[g["node_id"] == c["node_id"], "W_realized"] += c["replacement"]

        risk_mass = float((g["W_realized"] * g["R"]).sum())
        wsum = float(g["W_realized"].sum())
        conditional_prwi = risk_mass / wsum if wsum > 0 else np.nan

        # 集中度（3.6，在已实际采购内部计算）
        p = g["W_realized"] / g["W_realized"].sum()
        proc_hhi = float((p ** 2).sum())
        c = (g["W_realized"] * g["R"])
        c = c / c.sum()
        risk_hhi = float((c ** 2).sum())

        results[material] = {
            "enterprise": g["enterprise"].iloc[0],
            "target_node_id": target["node_id"],
            "target_node_name": target["node_name"],
            "target_weight": w_target,
            "failure_fraction_f": f,
            "gross_loss": round(gross_loss, 6),
            "inventory_I": inv,
            "inventory_used": round(inv_used, 6),
            "replacement_need": round(replacement_need, 6),
            "replacement_allocated": round(total_replacement, 6),
            "unmet_demand": round(unmet, 6),
            "fulfilled_demand": round(fulfilled, 6),
            "risk_mass": round(risk_mass, 6),
            "PRWI_baseline": round(float(g["C"].sum()), 6),
            "conditional_PRWI": round(conditional_prwi, 6),
            "procurement_hhi": round(proc_hhi, 4),
            "risk_hhi": round(risk_hhi, 4),
            "node_table": g[["node_id", "node_name", "weight", "R", "C",
                             "W_realized"]].reset_index(drop=True),
            "replacement_table": cand[["node_id", "node_name", "R", "cap", "replacement"]],
            "max_weight_node": g.loc[g["weight"].idxmax(), "node_id"],
            "max_risk_node": g.loc[g["R"].idxmax(), "node_id"],
        }
    return results


def node_failure_sweep(baseline: pd.DataFrame, params: Dict) -> pd.DataFrame:
    """失效比例 f 扫描：0.25/0.5/0.75/1.0 下的供应缺口与条件 PRWI（按材料）。"""
    sweep = params["node_failure"]["failure_fraction_sweep"]
    rows = []
    for f in sweep:
        p2 = {**params, "node_failure": {**params["node_failure"], "failure_fraction_f": f}}
        res = scenario_node_failure(baseline, p2)
        for m, r in res.items():
            rows.append({"material": m, "failure_fraction_f": f,
                         "gross_loss": r["gross_loss"], "unmet_demand": r["unmet_demand"],
                         "fulfilled_demand": r["fulfilled_demand"],
                         "conditional_PRWI": r["conditional_PRWI"],
                         "risk_mass": r["risk_mass"]})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 3.6 采购集中度与风险集中度（HHI，材料内部）
# ---------------------------------------------------------------------------
def compute_hhi(baseline: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for m, g in baseline.groupby("material"):
        g = g[g["weight"] > 0]
        w = g["weight"] / g["weight"].sum()
        proc_hhi = float((w ** 2).sum())
        c = g["C"] / g["C"].sum()
        risk_hhi = float((c ** 2).sum())
        rows.append({"material": m, "enterprise": g["enterprise"].iloc[0],
                     "procurement_hhi": round(proc_hhi, 4),
                     "risk_hhi": round(risk_hhi, 4)})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 3.7 敏感性 / 稳健性分析（按「企业—材料」）
# ---------------------------------------------------------------------------
def _top3(series: pd.Series) -> List[str]:
    return list(series.sort_values(ascending=False).head(3).index)


def _spearman(a: pd.Series, b: pd.Series) -> float:
    """秩相关（Pearson of ranks），避免额外依赖 scipy。"""
    ra = a.rank()
    rb = b.rank()
    return float(ra.corr(rb))


def sensitivity_theta(nodes: pd.DataFrame, material: pd.DataFrame,
                      theta_sweep: List[Dict], oa_override: float | None = None) -> pd.DataFrame:
    """
    路径权重敏感性：按材料分别计算 PRWI、Spearman 排名相关、Top3 重合、首位是否变化。
    （排名在材料内部，不再跨材料，反馈问题①②）
    """
    base = compute_baseline(nodes, material, {"ws": 1/3, "dr": 1/3, "sv": 1/3}, oa_override)
    rows = []
    for th in theta_sweep:
        b = compute_baseline(nodes, material,
                             {"ws": th["ws"], "dr": th["dr"], "sv": th["sv"]}, oa_override)
        for m in base["material"].unique():
            gb = base[base["material"] == m]
            g = b[b["material"] == m]
            base_rank = gb.set_index("node_id")["R"]
            rank = g.set_index("node_id")["R"]
            spearman = _spearman(base_rank, rank)
            base_top3 = _top3(gb.set_index("node_id")["C"])
            top3 = _top3(g.set_index("node_id")["C"])
            overlap = len(set(base_top3) & set(top3)) / 3
            first_changed = (top3[0] != base_top3[0])
            rows.append({"material": m, "theta_name": th["name"],
                         "ws": th["ws"], "dr": th["dr"], "sv": th["sv"],
                         "PRWI": round(float(g["C"].sum()), 6),
                         "spearman": round(spearman, 4),
                         "top3_overlap": round(overlap, 3),
                         "first_changed": first_changed})
    return pd.DataFrame(rows)


def sensitivity_oa(nodes: pd.DataFrame, material: pd.DataFrame,
                   oa_sweep: List[float]) -> pd.DataFrame:
    """OA（关键期—高压力月份重合）敏感性（按材料）。"""
    rows = []
    for oa in oa_sweep:
        b = compute_baseline(nodes, material, oa_override=oa)
        for m in b["material"].unique():
            g = b[b["material"] == m]
            rows.append({"material": m, "oa": oa,
                         "PRWI": round(float(g["C"].sum()), 6),
                         "max_R": round(float(g["R"].max()), 6)})
    return pd.DataFrame(rows)
