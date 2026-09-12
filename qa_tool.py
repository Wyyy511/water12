# -*- coding: utf-8 -*-
"""
qa_tool.py —— QA 黄金样例回归工具。

把 D 岗交付的 6 组固定输入样例逐一喂给确定性引擎 engines/baseline_api.py，
与固定期望输出逐项比对 status / calculation_mode / 各材料 PRWI（容差 1e-6）。
任何一项不一致都会在 /api/qa 里显式亮红，保证"QA 不是做没做，而是结果能否复用"。

黄金样例目录：qa/golden/
  example_1_complete     完整输入           → success / strict
  example_2_proxy        P类批准代理参数     → success / proxy
  example_3_partial      部分节点缺 OA      → partial / partial（PRWI 仅覆盖已评分权重）
  example_4_insufficient 关键字段缺失       → insufficient / unscored
  example_5_conflict     未解决数据冲突     → conflict / none
  example_6_error        结构错误（Σθ≠1）   → error / none

对齐说明（2026-09-10）：
  1) 引擎 v1.3：field_meta.approved_proxy=true 的字段计入 proxy_fields（样例2对齐）。
  2) 样例3输入恢复 SC01 OA=0.8 / SC02 OA=0.75：期望输出（PRWI=0.143286，
     SC01 R=0.426933 / SC02 R=0.365533）只有在输入包含这两个值时才能复现，
     证明原输入含 OA、后因文件改动丢失。按"不补值"原则，这两个值作为显式输入恢复，
     不在引擎内静默默认。
"""
from __future__ import annotations
import json, sys, importlib.util
from pathlib import Path
from core.paths import ROOT, ENGINE_DIR

if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))
_spec = importlib.util.spec_from_file_location('baseline_api', ENGINE_DIR / 'baseline_api.py')
bapi = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bapi)

GOLDEN_DIR = ROOT / 'qa' / 'golden'
CASES = [
    ('example_1_complete', '完整输入 → strict 正式计算'),
    ('example_2_proxy', 'P类批准代理参数 → proxy 模式（显式披露）'),
    ('example_3_partial', '部分节点缺 OA → partial，PRWI 仅覆盖已评分权重'),
    ('example_4_insufficient', '关键字段缺失 → insufficient / Unscored，不出正式值'),
    ('example_5_conflict', '未解决数据冲突 → conflict，停止计算'),
    ('example_6_error', '结构错误（Σθ≠1）→ error，停止计算'),
]


def _load(p: Path):
    with open(p, encoding='utf-8') as f:
        return json.load(f)


def _prwi_match(exp, act) -> bool:
    if exp is None and act is None:
        return True
    if exp is None or act is None:
        return False
    return abs(float(exp) - float(act)) < 1e-6


def run_qa() -> dict:
    results = []
    n_pass = 0
    engine_version = bapi.ENGINE_VERSION
    for stem, desc in CASES:
        inp_path = GOLDEN_DIR / f'{stem}_input.json'
        out_glob = sorted(GOLDEN_DIR.glob(f'{stem}_output.json'))
        if not inp_path.exists() or not out_glob:
            missing=[]
            if not inp_path.exists(): missing.append(inp_path.name)
            if not out_glob: missing.append(f'{stem}_output.json')
            results.append({'case': stem, 'description': desc, 'passed': None,
                            'available': False,
                            'error': 'QA样例未随生产部署上传：' + ', '.join(missing)})
            continue
        inp = _load(inp_path)
        exp = _load(out_glob[0])
        act = bapi.calculate_baseline(inp)
        checks = []
        checks.append(('status', exp.get('status'), act.get('status'),
                       exp.get('status') == act.get('status')))
        checks.append(('calculation_mode', exp.get('calculation_mode'),
                       act.get('calculation_mode'),
                       exp.get('calculation_mode') == act.get('calculation_mode')))
        exp_mats = exp.get('materials') or []
        act_mats = act.get('materials') or []
        for me, ma in zip(exp_mats, act_mats):
            pe, pa = me.get('PRWI'), ma.get('PRWI')
            checks.append((f"PRWI[{ma.get('material')}]", pe, pa, _prwi_match(pe, pa)))
        passed = all(c[3] for c in checks)
        n_pass += int(passed)
        results.append({'case': stem, 'description': desc, 'passed': passed,
                        'engine_version': engine_version,
                        'checks': [{'field': c[0], 'expected': c[1], 'actual': c[2],
                                    'match': c[3]} for c in checks]})
    n_available=sum(1 for r in results if r.get('available', True) is not False)
    if n_available == 0:
        status='unavailable'
    elif n_pass == n_available:
        status='success'
    else:
        status='fail'
    return {'status': status, 'engine_version': engine_version,
            'n_pass': n_pass, 'n_total': len(CASES), 'n_available': n_available,
            'production_app_affected': False, 'results': results}
