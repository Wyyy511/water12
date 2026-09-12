from __future__ import annotations
import csv
from collections import Counter
from pathlib import Path
from typing import Any

from core.paths import DATA_DIR

DICT_PATH = DATA_DIR / 'field_dictionary.csv'
GAP_PATH = DATA_DIR / 'field_gap_register.csv'

# E 组字段表作为“数据合同/缺口登记”使用；它不覆盖 D/C 已冻结的计算公式和变量语义。
# 当前 Baseline 的最小企业私有输入仍按总报告/确定性程序要求执行。
MIN_BASELINE_INPUT = [
    ('material', '原材料'),
    ('supplier_node', '供应节点/地区'),
    ('W', '节点采购数量/份额'),
]
RECOMMENDED_USER_INPUT = [
    ('enterprise_name', '企业名称'),
    ('procurement_year', '采购年份/参考期'),
    ('procurement_basis', '采购口径（数量/金额）'),
    ('U', 'Unknown/未映射采购份额（若已知）'),
]

# 与当前冻结研究口径存在差异的地方必须显式保留，不能让字段表覆盖模型。
COMPATIBILITY_NOTES = [
    'E 组字段字典中的 DR 单位标为 0–5；当前 Baseline 引擎使用 0–1 的历史干旱负担 DR。计算时以冻结 Baseline Schema 为准。',
    'E 组字段字典中 CTS/OA 的中文释义与研究报告冻结定义不完全一致；计算时 CTS=关键期时序敏感性，OA=关键期—高压力月份重合系数。',
    'Future/Extreme-drought 字段用于情景数据治理；最终场景枚举、时间尺度和阈值以 E/D 冻结情景规范为准。',
]


def _read(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open('r', encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def field_rows() -> list[dict[str, str]]:
    return _read(DICT_PATH)


def gap_rows() -> list[dict[str, str]]:
    return _read(GAP_PATH)


def contract_summary() -> dict[str, Any]:
    fields = field_rows(); gaps = gap_rows()
    cats = Counter(r.get('category','') for r in fields)
    priorities = Counter(r.get('priority','') for r in gaps)
    blocking = [r for r in gaps if r.get('affected_status') == 'insufficient']
    return {
        'status': 'success' if fields else 'insufficient',
        'field_count': len(fields),
        'gap_count': len(gaps),
        'categories': dict(cats),
        'gap_priorities': dict(priorities),
        'blocking_gap_ids': [r.get('gap_id') for r in blocking],
        'compatibility_notes': COMPATIBILITY_NOTES,
    }


def _val(row: dict, *names: str):
    for name in names:
        v = row.get(name)
        if v not in (None, ''):
            return v
    return None


def evaluate_user_records(records: list[dict] | None) -> dict[str, Any]:
    """Use E's field contract to audit user-owned inputs without changing model formulas.

    Only truly enterprise-owned blocking fields are enforced here. Upstream/model gaps are
    preserved as governance warnings and are handled by the registered data/query tools.
    """
    records = records or []
    missing: list[dict[str, Any]] = []
    warnings: list[str] = []
    if not records:
        return {
            'status': 'insufficient', 'missing_fields': ['material','supplier_node','W'],
            'missing_details': ['未提供采购/供应链记录'], 'warnings': [], 'unknown_share_by_material': {},
            'source': 'field_dictionary.csv + field_gap_register.csv'
        }

    sums: dict[str, float] = {}
    for idx, row in enumerate(records, start=1):
        mat = str(_val(row, 'material','material_id') or '').strip()
        node = str(_val(row, 'node_id','supplier_node_id','node_name') or '').strip()
        w = _val(row, 'purchase_weight','W')
        if not mat:
            missing.append({'row': idx, 'field': 'material', 'field_id': 'EXP-003', 'message': '缺少原材料'})
        if not node:
            missing.append({'row': idx, 'field': 'supplier_node', 'field_id': 'EXP-004', 'message': '缺少供应节点/地区'})
        try:
            wf = float(w)
            if wf < 0 or wf > 1:
                missing.append({'row': idx, 'field': 'W', 'field_id': 'EXP-005', 'message': '采购份额必须在 0–1'})
            if mat:
                sums[mat] = sums.get(mat, 0.0) + wf
        except Exception:
            missing.append({'row': idx, 'field': 'W', 'field_id': 'EXP-005', 'message': '缺少或无法识别采购份额'})

    unknown = {}
    for mat, total in sums.items():
        if total > 1.0001:
            missing.append({'row': None, 'field': 'W', 'field_id': 'EXP-005', 'message': f'{mat} 采购份额合计 {total:.4f}>1'})
        elif total < 0.9999:
            unknown[mat] = round(max(0.0, 1.0-total), 6)
            warnings.append(f'{mat} 已知采购份额合计 {total:.4f}，Unknown={unknown[mat]:.4f}；系统不会自动归一化。')

    status = 'insufficient' if missing else ('partial' if warnings else 'success')
    return {
        'status': status,
        'missing_fields': sorted(set(x['field'] for x in missing)),
        'missing_details': [x['message'] if x['row'] is None else f"第{x['row']}行：{x['message']}" for x in missing],
        'warnings': warnings,
        'unknown_share_by_material': unknown,
        'source': 'field_dictionary.csv + field_gap_register.csv',
    }


def gaps_for_task(task: str = 'baseline', scenario_type: str | None = None) -> list[dict[str, str]]:
    gaps = gap_rows()
    relevant_ids: set[str] = set()
    if task == 'baseline':
        relevant_ids |= {'EXP-005','LOC-005','HAZ-001','MAT-001','META-003','LOC-001'}
    if task == 'scenario':
        relevant_ids |= {'EXP-005','LOC-005','HAZ-001','MAT-001','META-003','LOC-001'}
        if scenario_type == 'PeakSeason': relevant_ids |= {'PK-003'}
        elif scenario_type == 'AqueductFuture': relevant_ids |= {'FUT-001'}
        elif scenario_type == 'ExtremeDrought': relevant_ids |= {'EXT-002','EXT-004'}
        elif scenario_type == 'NodeFailure': relevant_ids |= {'EXP-005'}
    return [r for r in gaps if r.get('field_id') in relevant_ids]


def user_requirements_text() -> str:
    gaps = gap_rows()
    wgap = next((g for g in gaps if g.get('gap_id') == 'GAP-001'), None)
    lines = [
        '如果你想得到与你企业采购结构相关的结果，我最少需要三类信息：',
        '1）要分析的原材料；2）主要采购来源或供应地区；3）各来源的采购量或采购占比。',
        '如果有的话，也建议提供企业名称、采购年份，以及采购量是按数量还是金额统计。',
        '只掌握部分供应来源也没关系，我会把未识别的部分单独保留，不会擅自补成 100%。',
        '地区风险和原材料相关信息会由系统后台补充；当前 MVP 只会自动匹配项目已登记的供应节点，未登记地区不会被当作已有数据。',
        '如果关键资料还不够，我会直接告诉你缺什么，而不会猜一个结果。',
    ]
    if wgap:
        lines.append('其中，各供应来源的采购占比属于企业自己的信息，公共数据无法替代；没有这项信息时，我会先请你补充。')
    return '\n'.join(lines)


def deepseek_context(task: str='baseline', scenario_type: str | None=None) -> dict[str, Any]:
    return {
        'field_contract': contract_summary(),
        'user_input_minimum': [x[1] for x in MIN_BASELINE_INPUT],
        'recommended_user_input': [x[1] for x in RECOMMENDED_USER_INPUT],
        'relevant_gaps': [
            {k: r.get(k) for k in ['gap_id','field_id','field_name_cn','impact','affected_status','mitigation','priority','status']}
            for r in gaps_for_task(task, scenario_type)
        ],
        'rule': '字段合同只用于数据治理；与冻结模型语义冲突时，以研究报告/确定性程序 Schema 为准。',
    }
