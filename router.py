from __future__ import annotations
import re

def route_intent(query: str) -> dict:
    q=(query or '').strip().lower()
    if not q:
        return {'intent':'explain','scenario_type':None,'confidence':0.4}
    scenario=None
    if any(k in q for k in ['失效','断供','停供','中断','failure']): scenario='NodeFailure'
    elif any(k in q for k in ['极端干旱','历史干旱','extreme drought']): scenario='ExtremeDrought'
    elif any(k in q for k in ['未来','2030','2050','2080','bau','悲观','乐观','future']): scenario='AqueductFuture'
    elif any(k in q for k in ['峰值季节','旺季','季节高峰','peak']): scenario='PeakSeason'
    if scenario:
        return {'intent':'scenario','scenario_type':scenario,'confidence':0.95}
    if any(k in q for k in ['baseline','基准','当前风险','prwi','风险最高','贡献最高','节点风险','分析风险','风险分析','风险评估','水风险分析','请分析','帮我分析','分析']):
        return {'intent':'baseline','scenario_type':None,'confidence':0.92}
    if any(k in q for k in ['缺失','缺什么','需要提供','哪些数据','准备什么','字段','映射','数据质量','coverage','unknown']):
        return {'intent':'data_audit','scenario_type':None,'confidence':0.90}
    if any(k in q for k in ['报告','简报','导出','建议','为什么','驱动','解释','管理']):
        return {'intent':'explain','scenario_type':None,'confidence':0.85}
    return {'intent':'explain','scenario_type':None,'confidence':0.65}
