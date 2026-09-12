#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Baseline Calculator v1.0
路径匹配型水风险基准评估计算模块

功能：
1. 读取 baseline_input.xlsx（统一主数据模板）
2. 按底稿公式执行节点级路径匹配型风险评估
3. 输出节点级结果、材料级汇总、数据缺口及Coverage结果
4. 严格区分"完整公式计算"与"模板代理计算"，不自行补值

交付内容：
- 01_正式输入文件_baseline_processed.csv
- 02_节点级计算结果_node_level.csv
- 03_企业材料级Baseline汇总_material_summary.csv
- 04_数据缺口及Coverage结果_data_gaps.csv

作者：D（Baseline计算模块负责人）
版本：v1.0
日期：2026-09-06
"""

import pandas as pd
import numpy as np
import os
import json
import sys
from datetime import datetime

# ==================== 常量定义 ====================
THETA_WS = 1/3
THETA_DR = 1/3
THETA_SV = 1/3

# ==================== DYS映射规则（底稿表2-5） ====================
def map_dys_score(l_m_percent):
    """
    将代表性产出损失L_m（%）映射为DYS评分（0-1）
    底稿规则：
        <10%      → 0.00
        10%-<20%  → 0.25
        20%-<35%  → 0.50
        35%-<50%  → 0.75
        ≥50%      → 1.00
    """
    if pd.isna(l_m_percent):
        return np.nan
    if l_m_percent < 10:
        return 0.00
    elif l_m_percent < 20:
        return 0.25
    elif l_m_percent < 35:
        return 0.50
    elif l_m_percent < 50:
        return 0.75
    else:
        return 1.00

# ==================== 证据可信度工具函数 ====================
def confidence_level_to_score(level):
    """High=3, Medium=2, Low=1, 其他=0"""
    if pd.isna(level):
        return 0
    level = str(level).strip().lower()
    if level == 'high':
        return 3
    elif level == 'medium':
        return 2
    elif level == 'low':
        return 1
    else:
        return 0

def score_to_confidence_label(score):
    """3=High, 2=Medium, 1=Low, 0=Unknown"""
    if score >= 3:
        return 'High'
    elif score >= 2:
        return 'Medium'
    elif score >= 1:
        return 'Low'
    else:
        return 'Unknown'

# ==================== 数据读取 ====================
def load_data(input_path):
    """读取Excel统一主数据模板"""
    # 主数据表（两层表头，跳过第一行）
    df = pd.read_excel(input_path, sheet_name='baseline_input', header=1)
    df.columns = [
        'material', 'node_id', 'node_name', 'spatial_level',
        'W_weight', 'basis', 'year', 'source_proc', 'conf_proc', 'status_proc',
        'notes',
        'WS_value', 'WS_unit', 'WS_period', 'WS_source', 'WS_conf', 'WS_status',
        'SV_value', 'SV_unit', 'SV_period', 'SV_source', 'SV_conf', 'SV_status',
        'DR_value', 'DR_unit', 'DR_period', 'DR_source', 'DR_conf', 'DR_status',
        'exp_WS', 'exp_SV', 'exp_DR', 'norm_risk',
        'DYS_raw', 'DYS_unit', 'DYS_period', 'DYS_source', 'DYS_conf', 'DYS_status',
        'CTS_raw', 'CTS_unit', 'CTS_period', 'CTS_source', 'CTS_conf', 'CTS_status',
        'OA_raw', 'OA_period', 'OA_source', 'OA_conf', 'OA_status',
        'reserved'
    ]

    # material_meta（跳过重复表头行）
    df_meta = pd.read_excel(input_path, sheet_name='material_meta', header=None, skiprows=1)
    df_meta.columns = ['material', 'node_count', 'sum_W', 'U_em', 'basis', 'year', 
                       'source', 'confidence', 'status', 'control_node', 'notes']

    return df, df_meta

# ==================== 输入校验 ====================
def validate_input(df, df_meta):
    """输入数据质量校验，返回问题列表"""
    issues = []

    # 校验1：各材料已知节点权重和是否为1
    for mat in df['material'].unique():
        mat_df = df[df['material'] == mat]
        active_nodes = mat_df[mat_df['W_weight'] > 0]
        sum_w = active_nodes['W_weight'].sum()
        if not np.isclose(sum_w, 1.0, atol=0.001):
            issues.append(f"[校验问题] 材料 '{mat}' 已知节点权重和={sum_w:.4f}，不等于1.0")

    # 校验2：地点水危险指标缺失检查
    for idx, row in df.iterrows():
        if pd.isna(row['WS_value']) or pd.isna(row['SV_value']) or pd.isna(row['DR_value']):
            issues.append(f"[数据缺失] {row['material']}-{row['node_id']} 地点水危险指标存在缺失")

    # 校验3：BWD列结构缺失
    if 'BWD_raw' not in df.columns:
        issues.append("[结构缺失] 输入文件缺少BWD（蓝水依赖）列，水压力路径完整计算受阻")

    # 校验4：OA缺失检查
    oa_missing = df[df['OA_raw'] == '_'].shape[0]
    if oa_missing > 0:
        issues.append(f"[数据缺失] 共{oa_missing}个节点的OA缺失，季节错配路径完整计算受阻")

    return issues

# ==================== 节点级计算 ====================
def calculate_node_level(df):
    """
    节点级Baseline计算

    同时输出：
    - 严格模式：按底稿2.2完整公式，缺失参数则标记为NaN
    - 代理模式：使用模板已有综合风险（norm_risk），对应材料参数暂按1处理
    """
    results = []

    for idx, row in df.iterrows():
        material = row['material']
        node_id = row['node_id']
        node_name = row['node_name']
        W = row['W_weight']

        # --- 地点水危险标准化 ---
        WS_norm = row['WS_value'] / 5.0 if not pd.isna(row['WS_value']) else np.nan
        SV_norm = row['SV_value'] / 5.0 if not pd.isna(row['SV_value']) else np.nan
        DR = row['DR_value'] if not pd.isna(row['DR_value']) else np.nan

        # --- 材料参数处理 ---
        # BWD：当前模板未提供此列，标记为缺失
        BWD_score = np.nan
        BWD_missing = True

        # DYS：按底稿映射规则转换
        DYS_raw = row['DYS_raw']
        DYS_score = map_dys_score(DYS_raw)

        # CTS：直接使用
        CTS_score = float(row['CTS_raw']) if not pd.isna(row['CTS_raw']) else np.nan

        # OA：模板中标记为"_"，缺失
        OA_raw = row['OA_raw']
        OA_score = np.nan
        OA_missing = (OA_raw == '_') or pd.isna(OA_raw)

        # --- 严格模式：底稿2.2完整公式 ---
        R_WS_full = THETA_WS * WS_norm * BWD_score if not (pd.isna(WS_norm) or pd.isna(BWD_score)) else np.nan
        R_DR_full = THETA_DR * DR * DYS_score if not (pd.isna(DR) or pd.isna(DYS_score)) else np.nan
        R_SV_full = THETA_SV * SV_norm * CTS_score * OA_score if not (pd.isna(SV_norm) or pd.isna(CTS_score) or pd.isna(OA_score)) else np.nan

        path_scores = [R_WS_full, R_DR_full, R_SV_full]
        available_paths = [p for p in path_scores if not pd.isna(p)]

        if len(available_paths) == 3:
            R_full = sum(path_scores)
            R_full_status = '完整计算'
        elif len(available_paths) > 0:
            R_full = np.nan  # 部分路径可计算，但完整R要求三条路径
            R_full_status = '部分路径缺失（BWD/OA缺失）'
        else:
            R_full = np.nan
            R_full_status = '无可计算路径'

        C_full = W * R_full if not pd.isna(R_full) else np.nan

        # --- 代理模式：使用模板已有综合风险 ---
        # 对应假设：BWD=1, DYS_mapped=1, CTS=1, OA=1（与模板公式一致）
        R_proxy = row['norm_risk'] if not pd.isna(row['norm_risk']) else (WS_norm + SV_norm + DR) / 3.0
        C_proxy = W * R_proxy

        # 代理模式路径分解（用于展示三条路径结构，明确标注为代理假设）
        R_WS_proxy = THETA_WS * WS_norm * 1.0
        R_DR_proxy = THETA_DR * DR * 1.0
        R_SV_proxy = THETA_SV * SV_norm * 1.0 * 1.0
        C_WS_proxy = W * R_WS_proxy
        C_DR_proxy = W * R_DR_proxy
        C_SV_proxy = W * R_SV_proxy

        # --- 证据可信度（底稿2.7最弱环节规则） ---
        ws_conf = confidence_level_to_score(row['WS_conf'])
        sv_conf = confidence_level_to_score(row['SV_conf'])
        dr_conf = confidence_level_to_score(row['DR_conf'])
        loc_water_conf = min(ws_conf, sv_conf, dr_conf)

        proc_conf = confidence_level_to_score(row['conf_proc'])

        dys_conf = confidence_level_to_score(row['DYS_conf'])
        cts_conf = confidence_level_to_score(row['CTS_conf'])
        mat_param_conf = min(0 if BWD_missing else 3, dys_conf, cts_conf, 0 if OA_missing else 3)

        season_conf = 0 if OA_missing else confidence_level_to_score(row['OA_conf'])

        overall_conf_score = min(loc_water_conf, proc_conf, mat_param_conf, season_conf)
        overall_conf_label = score_to_confidence_label(overall_conf_score)

        # --- 数据缺口记录 ---
        data_gaps = []
        if BWD_missing:
            data_gaps.append('BWD缺失')
        if OA_missing:
            data_gaps.append('OA缺失')
        if DYS_score == 0.00 and not pd.isna(DYS_raw):
            data_gaps.append(f'DYS映射后为0（原始值{DYS_raw}%<10%，需复核文献）')

        results.append({
            'material': material,
            'node_id': node_id,
            'node_name': node_name,
            'spatial_level': row['spatial_level'],
            'W_weight': W,
            'status_proc': row['status_proc'],
            'conf_proc': row['conf_proc'],

            'WS_raw': row['WS_value'],
            'WS_norm': WS_norm,
            'SV_raw': row['SV_value'],
            'SV_norm': SV_norm,
            'DR': DR,

            'BWD_score': BWD_score,
            'BWD_status': 'Missing' if BWD_missing else 'Available',
            'DYS_raw': DYS_raw,
            'DYS_score': DYS_score,
            'DYS_status': 'Mapped' if not pd.isna(DYS_raw) else 'Missing',
            'CTS_score': CTS_score,
            'CTS_status': 'Available' if not pd.isna(CTS_score) else 'Missing',
            'OA_score': OA_score,
            'OA_status': 'Missing' if OA_missing else 'Available',

            'R_WS_full': R_WS_full,
            'R_DR_full': R_DR_full,
            'R_SV_full': R_SV_full,
            'R_full': R_full,
            'R_full_status': R_full_status,
            'C_full': C_full,

            'R_proxy': R_proxy,
            'C_proxy': C_proxy,
            'C_WS_proxy': C_WS_proxy,
            'C_DR_proxy': C_DR_proxy,
            'C_SV_proxy': C_SV_proxy,

            'loc_water_conf': score_to_confidence_label(loc_water_conf),
            'proc_conf': score_to_confidence_label(proc_conf),
            'mat_param_conf': score_to_confidence_label(mat_param_conf),
            'season_conf': score_to_confidence_label(season_conf),
            'overall_conf': overall_conf_label,

            'data_gaps': '; '.join(data_gaps) if data_gaps else '无',
            'gap_count': len(data_gaps),
        })

    return pd.DataFrame(results)

# ==================== 材料级汇总 ====================
def calculate_material_summary(node_df, df_meta):
    """企业—材料级Baseline汇总"""
    summaries = []

    for material in node_df['material'].unique():
        mat_nodes = node_df[node_df['material'] == material]
        active_nodes = mat_nodes[mat_nodes['W_weight'] > 0]

        node_count = len(active_nodes)
        sum_W = active_nodes['W_weight'].sum()
        U_em = 1 - sum_W
        coverage = 1 - U_em

        # 代理模式PRWI（当前数据状态下可用）
        PRWI_proxy = active_nodes['C_proxy'].sum()

        # 严格模式PRWI
        valid_full = active_nodes[active_nodes['C_full'].notna()]
        if len(valid_full) > 0:
            PRWI_full = valid_full['C_full'].sum()
            PRWI_full_status = '部分节点完整计算'
        else:
            PRWI_full = np.nan
            PRWI_full_status = '无节点可完整计算（参数缺失）'

        KnownRisk = active_nodes['C_proxy'].sum()

        # R_mmax理论最大值（代理值，假设所有参数=1且地点水危险=1）
        R_mmax = THETA_WS * 1.0 * 1.0 + THETA_DR * 1.0 * 1.0 + THETA_SV * 1.0 * 1.0 * 1.0

        PRWI_lower = KnownRisk
        PRWI_upper = KnownRisk + U_em * R_mmax

        total_C_WS = active_nodes['C_WS_proxy'].sum()
        total_C_DR = active_nodes['C_DR_proxy'].sum()
        total_C_SV = active_nodes['C_SV_proxy'].sum()

        path_ws_share = total_C_WS / PRWI_proxy if PRWI_proxy > 0 else 0
        path_dr_share = total_C_DR / PRWI_proxy if PRWI_proxy > 0 else 0
        path_sv_share = total_C_SV / PRWI_proxy if PRWI_proxy > 0 else 0

        sorted_nodes = active_nodes.sort_values('C_proxy', ascending=False).reset_index(drop=True)
        top3 = sorted_nodes.head(3)
        top1_node = top3.iloc[0]['node_id'] if len(top3) > 0 else 'N/A'
        top1_share = top3.iloc[0]['C_proxy'] / PRWI_proxy if PRWI_proxy > 0 and len(top3) > 0 else 0
        top3_share = top3['C_proxy'].sum() / PRWI_proxy if PRWI_proxy > 0 else 0

        p = active_nodes['W_weight'].values
        proc_HHI = np.sum(p ** 2)

        c = active_nodes['C_proxy'].values / PRWI_proxy if PRWI_proxy > 0 else np.zeros_like(p)
        risk_HHI = np.sum(c ** 2) if PRWI_proxy > 0 else 0

        conf_scores = active_nodes['overall_conf'].map({'High':3, 'Medium':2, 'Low':1, 'Unknown':0})
        overall_mat_conf = score_to_confidence_label(conf_scores.min())

        gap_nodes = active_nodes[active_nodes['gap_count'] > 0]
        gap_node_count = len(gap_nodes)
        gap_details = gap_nodes[['node_id', 'data_gaps']].to_dict('records')

        summaries.append({
            'material': material,
            'node_count': node_count,
            'sum_W': sum_W,
            'U_em': U_em,
            'coverage_procurement': coverage,
            'PRWI_proxy': PRWI_proxy,
            'PRWI_full': PRWI_full,
            'PRWI_full_status': PRWI_full_status,
            'PRWI_lower': PRWI_lower,
            'PRWI_upper': PRWI_upper,
            'R_mmax': R_mmax,
            'total_C_WS': total_C_WS,
            'total_C_DR': total_C_DR,
            'total_C_SV': total_C_SV,
            'path_ws_share': path_ws_share,
            'path_dr_share': path_dr_share,
            'path_sv_share': path_sv_share,
            'top1_node': top1_node,
            'top1_share': top1_share,
            'top3_share': top3_share,
            'proc_HHI': proc_HHI,
            'risk_HHI': risk_HHI,
            'overall_conf': overall_mat_conf,
            'gap_node_count': gap_node_count,
            'gap_details': json.dumps(gap_details, ensure_ascii=False),
        })

    return pd.DataFrame(summaries)

# ==================== 数据缺口报告 ====================
def generate_data_gap_report(node_df, df_meta):
    """数据缺口及Coverage结果"""
    gaps = []

    for material in node_df['material'].unique():
        mat_nodes = node_df[node_df['material'] == material]
        active_nodes = mat_nodes[mat_nodes['W_weight'] > 0]

        sum_W = active_nodes['W_weight'].sum()
        U_em = 1 - sum_W
        coverage = 1 - U_em

        total_params = 4  # BWD, DYS, CTS, OA

        for idx, row in active_nodes.iterrows():
            missing_params = []
            if row['BWD_status'] == 'Missing':
                missing_params.append('BWD')
            if row['DYS_status'] == 'Missing':
                missing_params.append('DYS')
            if row['CTS_status'] == 'Missing':
                missing_params.append('CTS')
            if row['OA_status'] == 'Missing':
                missing_params.append('OA')

            param_completeness = (total_params - len(missing_params)) / total_params

            gaps.append({
                'material': material,
                'node_id': row['node_id'],
                'node_name': row['node_name'],
                'W_weight': row['W_weight'],
                'spatial_level': row['spatial_level'],
                'status_proc': row['status_proc'],
                'proc_confidence': row['conf_proc'],
                'coverage_procurement': coverage,
                'U_em': U_em,
                'missing_parameters': ', '.join(missing_params) if missing_params else '无',
                'param_completeness': param_completeness,
                'data_gaps_detail': row['data_gaps'],
                'overall_evidence_conf': row['overall_conf'],
                'loc_water_conf': row['loc_water_conf'],
                'proc_conf': row['proc_conf'],
                'mat_param_conf': row['mat_param_conf'],
                'season_conf': row['season_conf'],
            })

    return pd.DataFrame(gaps)

# ==================== 主程序 ====================
def main(input_path, output_dir):
    """主入口函数"""
    print("="*60)
    print("Baseline Calculator v1.0")
    print("路径匹配型水风险基准评估计算模块")
    print("="*60)

    os.makedirs(output_dir, exist_ok=True)

    # 1. 读取数据
    print("\n[1/5] 读取输入数据...")
    df, df_meta = load_data(input_path)
    print(f"      主数据表: {len(df)} 行")
    print(f"      材料元数据: {len(df_meta)} 种材料")

    # 2. 输入校验
    print("\n[2/5] 执行输入校验...")
    issues = validate_input(df, df_meta)
    if issues:
        for issue in issues:
            print(f"      ⚠️ {issue}")
    else:
        print("      ✅ 基础校验通过")

    # 3. 节点级计算
    print("\n[3/5] 执行节点级计算...")
    node_results = calculate_node_level(df)
    print(f"      完成 {len(node_results)} 个节点计算")

    # 4. 材料级汇总
    print("\n[4/5] 执行材料级汇总...")
    mat_summary = calculate_material_summary(node_results, df_meta)
    print(f"      完成 {len(mat_summary)} 种材料汇总")

    # 5. 数据缺口报告
    print("\n[5/5] 生成数据缺口报告...")
    gap_report = generate_data_gap_report(node_results, df_meta)
    print(f"      完成 {len(gap_report)} 条缺口记录")

    # 6. 输出文件
    print("\n[输出文件]")

    # 正式输入文件
    formal_input = df[['material', 'node_id', 'node_name', 'spatial_level', 
                       'W_weight', 'status_proc', 'conf_proc',
                       'WS_value', 'SV_value', 'DR_value',
                       'DYS_raw', 'DYS_unit', 'DYS_source', 'DYS_conf',
                       'CTS_raw', 'CTS_source', 'CTS_conf',
                       'OA_raw', 'OA_source', 'OA_conf']].copy()
    formal_input.columns = ['material', 'node_id', 'node_name', 'spatial_level',
                            'W_weight', 'proc_status', 'proc_confidence',
                            'WS_raw', 'SV_raw', 'DR_raw',
                            'DYS_raw', 'DYS_unit', 'DYS_source', 'DYS_confidence',
                            'CTS_raw', 'CTS_source', 'CTS_confidence',
                            'OA_raw', 'OA_source', 'OA_confidence']
    formal_input.to_csv(f'{output_dir}/01_正式输入文件_baseline_processed.csv', index=False, encoding='utf-8-sig')
    print("      ✅ 01_正式输入文件_baseline_processed.csv")

    node_results.to_csv(f'{output_dir}/02_节点级计算结果_node_level.csv', index=False, encoding='utf-8-sig')
    print("      ✅ 02_节点级计算结果_node_level.csv")

    mat_summary.to_csv(f'{output_dir}/03_企业材料级Baseline汇总_material_summary.csv', index=False, encoding='utf-8-sig')
    print("      ✅ 03_企业材料级Baseline汇总_material_summary.csv")

    gap_report.to_csv(f'{output_dir}/04_数据缺口及Coverage结果_data_gaps.csv', index=False, encoding='utf-8-sig')
    print("      ✅ 04_数据缺口及Coverage结果_data_gaps.csv")

    # 打印关键摘要
    print("\n" + "="*60)
    print("【Baseline汇总摘要】")
    print("="*60)
    for _, row in mat_summary.iterrows():
        print(f"\n材料: {row['material']}")
        print(f"  PRWI(代理)={row['PRWI_proxy']:.6f} | 严格模式={row['PRWI_full_status']}")
        print(f"  Coverage={row['coverage_procurement']:.1%} | 首位节点={row['top1_node']}({row['top1_share']:.1%})")
        print(f"  证据可信度={row['overall_conf']} | 缺口节点={row['gap_node_count']}/{row['node_count']}")

    print("\n" + "="*60)
    print("计算完成。所有结果已输出至:", output_dir)
    print("="*60)

    return node_results, mat_summary, gap_report

if __name__ == '__main__':
    if len(sys.argv) >= 3:
        input_path = sys.argv[1]
        output_dir = sys.argv[2]
    else:
        input_path = 'baseline_input.xlsx'
        output_dir = 'output'

    main(input_path, output_dir)
