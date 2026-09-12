from __future__ import annotations
import pandas as pd

PATH_CN={"WS":"长期缺水压力","DR":"历史干旱","SV":"季节性供水波动"}

def _missing(v):
    return v is None or (isinstance(v,float) and pd.isna(v))

def _fmt(v,n=4):
    if _missing(v): return "不可计算"
    try: return f"{float(v):.{n}f}"
    except Exception: return "不可计算"

def baseline_brief(result:dict, material:str|None=None)->str:
    if not result or result.get("data") is None:
        return "目前还没有足够的信息形成完整的风险结果。请补充或核对采购来源、地区和采购占比后继续。"
    s=result["data"]["summary"]; n=result["data"]["nodes"]
    if isinstance(s,list): s=pd.DataFrame(s)
    if isinstance(n,list): n=pd.DataFrame(n)
    if material and not s.empty and material in set(s.material):
        s=s[s.material==material]; n=n[n.material==material]
    paras=[]
    for _,r in s.iterrows():
        mat=str(r.get("material") or "该原材料"); ent=str(r.get("enterprise") or "")
        gn=n[n.material==r.get("material")] if not n.empty and "material" in n.columns else pd.DataFrame()
        topc=gn.sort_values("C",ascending=False).iloc[0] if len(gn) and "C" in gn.columns else None
        paths={"WS":float(r.get("path_contrib_WS") or 0),"DR":float(r.get("path_contrib_DR") or 0),"SV":float(r.get("path_contrib_SV") or 0)}
        total=sum(paths.values()); dom=max(paths,key=paths.get) if total>0 else None
        proc=float(r.get("Coverage") or 0); scored=r.get("scored_coverage"); cov=proc if _missing(scored) else float(scored)
        identity=result.get("data_identity") or {}
        lines=[f"### {(ent+' · ') if ent else ''}{mat}",
               f"**风险结论**：综合风险指数为 {_fmt(r.get('PRWI'))}。已识别采购覆盖 {proc*100:.1f}%，可完成风险评估的采购覆盖 {cov*100:.1f}%。该指数用于相对筛查，不代表损失概率或财务损失。"]
        if topc is not None:
            lines.append(f"**重点供应地**：{topc.get('node_name')}（{topc.get('node_id')}）对当前采购组合影响最大，贡献占比约 {float(topc.get('contribution_share') or 0)*100:.1f}%。")
        else:
            lines.append("**重点供应地**：当前没有足够节点数据判断。")
        if dom and total>0:
            lines.append(f"**主要风险来源**：{PATH_CN[dom]}，约占当前综合风险的 {paths[dom]/total*100:.2f}%；三类来源贡献合计为 100%。")
        else:
            lines.append("**主要风险来源**：当前不可计算。")
        data_note=f"总体证据可信度 {str(r.get('overall_confidence') or 'Unknown')}。"
        if identity.get("has_proxy") or identity.get("has_assumption"):
            data_note += " 本次结果含代理数据或假设参数；“可以完整计算”不等于所有输入都已真实核验。"
        else:
            data_note += " 当前没有检测到已标记的代理或假设项。"
        if float(r.get("unknown_share_U") or 0)>0:
            data_note += f" 仍有 {float(r.get('unknown_share_U'))*100:.1f}% 采购份额未识别。"
        lines.append("**数据可信度与限制**："+data_note)
        lines.append("**管理建议**：优先核实最大贡献供应地、真实采购占比和低置信度数据；如该节点对业务重要，可提前准备监测、库存缓冲或替代采购方案。")
        paras.append("\n\n".join(lines))
    return "\n\n".join(paras)

def scenario_brief(result:dict)->str:
    if not result or result.get("data") is None:
        return "这项比较目前还缺少必要信息，暂时不能形成可靠结论。"
    d=result["data"]; typ=d.get("scenario_type")
    if typ=="NodeFailure":
        text=(f"### 主要供应地中断\n\n"
              f"**风险结论**：受影响供应地为 {d.get('target_node_name')}（{d.get('target_node_id')}），本次设定影响比例为 {float(d.get('failure_fraction_f') or 0)*100:.0f}%。"
              f"预计供应损失 {_fmt(d.get('gross_loss'))}，库存可缓冲 {_fmt(d.get('inventory_used'))}，替代供应 {_fmt(d.get('replacement_allocated'))}，仍未满足的需求 {_fmt(d.get('unmet_demand'))}。\n\n"
              f"**重点供应地**：{d.get('target_node_name')}（{d.get('target_node_id')}）是本次压力测试的目标节点。\n\n"
              f"**主要风险来源**：本次变化来自该节点供应中断以及库存、替代供应对缺口的吸收。剩余供应综合风险为 {_fmt(d.get('conditional_PRWI'))}，采购集中度 {_fmt(d.get('procurement_hhi'))}，风险集中度 {_fmt(d.get('risk_hhi'))}。\n\n"
              "**数据可信度与限制**：这是压力测试，不是事件预测；结果取决于中断比例、库存和替代能力等设定。零冲击时供应损失和未满足需求应为 0。\n\n"
              "**管理建议**：不要只看总风险是否下降，应同时看未满足需求和采购是否变得更集中；对关键节点应预先准备替代供应和库存策略。")
    elif typ in ["PeakSeason","ExtremeDrought"]:
        delta=d.get("PRWI_delta"); direction="上升" if (delta or 0)>0 else ("下降" if (delta or 0)<0 else "基本不变")
        title="关键用水期压力升高" if typ=="PeakSeason" else "严重干旱再次发生"
        text=(f"### {title}\n\n"
              f"**风险结论**：当前综合风险指数为 {_fmt(d.get('PRWI_baseline'))}，在这种情况下为 {_fmt(d.get('PRWI_scenario'))}，变化 {_fmt(delta)}，整体风险{direction}。\n\n"
              "**重点供应地**：请结合本次结果中的节点明细判断贡献最大的供应来源。\n\n"
              "**主要风险来源**：本次变化来自设定的水压力条件变化，不表示该事件一定发生。\n\n"
              "**数据可信度与限制**：这是压力测试；演示或代理参数必须单独标记，不应写成现实预测。\n\n"
              "**管理建议**：优先检查变化最大的供应地，并准备监测、库存或替代采购安排。")
    elif typ=="AqueductFuture":
        text=(f"### 未来水环境发生变化\n\n"
              f"**风险结论**：在 {d.get('year')} / {d.get('path')} 的设定下，当前综合风险指数为 {_fmt(d.get('PRWI_baseline'))}，变化后为 {_fmt(d.get('PRWI_future'))}，变化 {_fmt(d.get('PRWI_delta'))}。\n\n"
              "**重点供应地**：请结合节点明细判断对组合变化贡献最大的地区。\n\n"
              "**主要风险来源**：来自未来水压力和季节波动设定的变化。\n\n"
              "**数据可信度与限制**：当前未来数据属于压力测试用途，不能当成确定预测。\n\n"
              "**管理建议**：用结果识别需要优先监测和准备替代方案的供应地，而不是把单一未来分数当作预测值。")
    else:
        text=("**风险结论**：不同情况下的比较已经完成。\n\n"
              "**重点供应地**：请查看节点结果。\n\n"
              "**主要风险来源**：请查看本次设定。\n\n"
              "**数据可信度与限制**：结果取决于当前输入和假设。\n\n"
              "**管理建议**：结合供应缺口、集中度和数据可信度共同决策。")
    if result.get("warnings"): text += "\n\n**需要注意**："+"；".join(result["warnings"])
    return text

def data_audit_brief(validation:dict)->str:
    if not validation: return "还没有完成资料检查。"
    out=["### 资料完整性检查"]; cov=validation.get("coverage",{})
    if isinstance(cov,dict) and cov: out.append("- 已识别采购信息："+"；".join(f"{k} {float(v)*100:.1f}%" for k,v in cov.items()))
    for title,key in [("需要你确认","issues"),("提示","warnings"),("还缺的信息","data_gaps")]:
        vals=validation.get(key,[])
        if vals: out.append(f"- **{title}**："+"；".join(map(str,vals)))
    out.append("- 未识别的采购份额不会被当成 0，也不会自动把已知部分放大到 100%。")
    return "\n".join(out)
