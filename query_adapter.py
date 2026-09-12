from __future__ import annotations
from pathlib import Path
import difflib
import pandas as pd
from core.paths import DATA_DIR


def _read(name: str) -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / name, encoding='utf-8-sig')


def resolve_location(location_text: str, material: str | None = None) -> dict:
    """MVP location resolver using the currently registered local node snapshot.

    Later this module can be replaced by Song Ziming's formal data query kernel
    without changing the Agent-side tool contract.
    """
    q=(location_text or '').strip()
    if not q:
        return {'status':'insufficient','data':None,'warnings':[],'missing_fields':['location_text']}
    h=_read('hazard_baseline.csv')
    if material:
        h=h[h['material'].astype(str)==str(material)]
    # exact id/name
    exact=h[(h['node_id'].astype(str)==q)|(h['node_name'].astype(str)==q)]
    if len(exact):
        r=exact.iloc[0]
        return {'status':'success','data':{'node_id':r.node_id,'node_name':r.node_name,'material':r.material,'pfaf_id':r.pfaf_id,'match_score':1.0},'warnings':[]}
    scored=[]
    for _,r in h.iterrows():
        nm=str(r.node_name)
        base=nm.split('(')[0]
        s=max(difflib.SequenceMatcher(None,q,nm).ratio(),difflib.SequenceMatcher(None,q,base).ratio())
        if q in nm or base in q: s=max(s,0.92)
        scored.append((s,r))
    if not scored:
        return {'status':'insufficient','data':None,'warnings':[],'missing_fields':['location_match']}
    s,r=max(scored,key=lambda x:x[0])
    if s<0.55:
        return {'status':'insufficient','data':None,'warnings':['当前注册表没有可靠地点匹配'],'missing_fields':['location_match']}
    status='success' if s>=0.90 else 'partial'
    return {'status':status,'data':{'node_id':r.node_id,'node_name':r.node_name,'material':r.material,'pfaf_id':r.pfaf_id,'match_score':round(float(s),4)},'warnings':([] if status=='success' else ['地点为模糊匹配，建议人工确认'])}


def lookup_water_risk(node_id: str, year: str | int | None = None, indicators: list[str] | None = None, data_release_id: str='integrated-mvp-2026-09-06') -> dict:
    h=_read('hazard_baseline.csv')
    row=h[h['node_id'].astype(str)==str(node_id)]
    if row.empty:
        return {'status':'insufficient','data':None,'missing_fields':['node_water_risk'],'warnings':[], 'data_release_id':data_release_id}
    r=row.iloc[0]
    wanted=set(indicators or ['WS','DR','SV'])
    vals={}
    if 'WS' in wanted: vals['WS']={'value':float(r.ws_score),'unit':'score_0_5'}
    if 'DR' in wanted: vals['DR']={'value':float(r.dr),'unit':'ratio_0_1'}
    if 'SV' in wanted: vals['SV']={'value':float(r.sv_score),'unit':'score_0_5'}
    return {
        'status':'success',
        'data':{
            'node_id':r.node_id,'node_name':r.node_name,'material':r.material,'pfaf_id':r.pfaf_id,
            'reference_period':r.reference_period,'values':vals,'data_type':r.data_type,'confidence':r.confidence,
            'source_ref':r.source_ref,
        },
        'warnings':[], 'data_release_id':data_release_id
    }


def lookup_material_parameters(material: str, region: str | None=None, year: str | int | None=None, data_release_id: str='integrated-mvp-2026-09-06') -> dict:
    m=_read('material_params.csv')
    row=m[m['material'].astype(str)==str(material)]
    if row.empty:
        return {'status':'insufficient','data':None,'missing_fields':['material_parameters'],'warnings':[], 'data_release_id':data_release_id}
    r=row.iloc[0]
    return {
        'status':'partial' if str(r.oa_type)=='S' else 'success',
        'data':{
            'material':r.material,
            'BWD':float(r.param_bwd),'DYS':float(r.param_dys_base),'DYS_low':float(r.param_dys_low),'DYS_high':float(r.param_dys_high),
            'CTS':float(r.param_cts),'OA':float(r.param_oa_base),
            'confidence':{'BWD':r.bwd_confidence,'DYS':r.dys_confidence,'CTS':r.cts_confidence,'OA':r.oa_confidence},
            'data_type':{'BWD':r.bwd_type,'DYS':r.dys_type,'CTS':r.cts_type,'OA':r.oa_type},
            'source_ref':r.source_ref,
        },
        'warnings':(['OA 当前为 S 类假设，正式企业应用需替换或重新核验。'] if str(r.oa_type)=='S' else []),
        'data_release_id':data_release_id
    }


def supported_locations(material: str | None=None) -> dict:
    h=_read('hazard_baseline.csv')
    if material:
        h=h[h['material'].astype(str)==str(material)]
    records=[]
    for _,r in h.iterrows():
        records.append({
            'node_id':str(r.node_id),'node_name':str(r.node_name),'material':str(r.material),
            'pfaf_id':str(r.pfaf_id),'reference_period':str(r.reference_period),
            'data_type':str(r.data_type),'confidence':str(r.confidence),'source_ref':str(r.source_ref),
        })
    return {'status':'success','count':len(records),'records':records,
            'note':'当前 MVP 只对项目已登记节点提供自动匹配；未登记地区不会被静默替换为其他地区。'}
