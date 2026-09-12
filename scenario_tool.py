from __future__ import annotations
import copy, importlib.util
import pandas as pd
from core.paths import ENGINE_DIR, DATA_DIR

spec=importlib.util.spec_from_file_location('scenario_v2', ENGINE_DIR/'scenario_engine.py')
se=importlib.util.module_from_spec(spec); spec.loader.exec_module(se)

def _resources():
    return se.load_master_data(str(DATA_DIR))

def run_scenario(baseline_result: dict, scenario_type: str, material: str,
                 year: int=2050, path: str='BAU', failure_fraction: float=1.0,
                 inventory: float=0.10) -> dict:
    if not baseline_result or baseline_result.get('data') is None:
        return {'status':'insufficient','data':None,'warnings':[],'data_gaps':['必须先运行 Baseline'],'model_version':'scenario_v2.0'}
    base=baseline_result['data']['nodes'].copy()
    if base.empty or material not in set(base['material']):
        return {'status':'insufficient','data':None,'warnings':[],'data_gaps':[f'Baseline 中没有材料 {material}'],'model_version':'scenario_v2.0'}
    # Scenario functions can operate on user baseline, while environmental scenario inputs come from registered B/E data.
    d=_resources(); params=copy.deepcopy(d['params']); th=params['theta']
    warnings=[]
    try:
        if scenario_type=='PeakSeason':
            out=se.scenario_peak_season(base,d['monthly_ws'],th)
            g=out[out.material==material].copy()
            pb=float(base[base.material==material]['C'].sum()); ps=float(g['C_peak'].sum())
            data={'scenario_type':'PeakSeason','material':material,'PRWI_baseline':pb,'PRWI_scenario':ps,'PRWI_delta':ps-pb,
                  'node_table':g[['node_id','node_name','R','R_peak','R_delta','C','C_peak','rank_peak']].copy()}
        elif scenario_type=='AqueductFuture':
            future_sub=d['future'][d['future']['node_id'].isin(set(base['node_id']))].copy()
            _,combo=se.scenario_future(base,future_sub,th)
            row=combo[(combo.material==material)&(combo.year==int(year))&(combo.path==path)]
            if row.empty: raise ValueError('指定未来组合不存在')
            data=row.iloc[0].to_dict(); data['scenario_type']='AqueductFuture'; data['demo']=1
            warnings.append('未来 WS/SV 当前为 S 类演示数据（demo=1），只能用于流程/敏感性演示，不能写成真实未来预测。')
        elif scenario_type=='ExtremeDrought':
            out=se.scenario_extreme_drought(base,d['extreme_drought'],params,th)
            g=out[out.material==material].copy()
            pb=float(base[base.material==material]['C'].sum()); ps=float(g['C_ed'].sum())
            data={'scenario_type':'ExtremeDrought','material':material,'PRWI_baseline':pb,'PRWI_scenario':ps,'PRWI_delta':ps-pb,
                  'node_table':g[['node_id','node_name','dr','dr_ed','event_status','R','R_ed','R_delta_ed','gross_supply_loss','lambda_source']].copy()}
            warnings.append('供应损失使用 λ=30% 文献参考值，仅示范 Supply-side 机制，不是逐作物真实减产预测。')
        elif scenario_type=='NodeFailure':
            params['node_failure']['failure_fraction_f']=float(failure_fraction)
            params['node_failure']['inventory_I']=float(inventory)
            allres=se.scenario_node_failure(base,params)
            if material not in allres: raise ValueError('材料无节点失效结果')
            r=allres[material]
            data={k:v for k,v in r.items() if k not in ['node_table','replacement_table']}
            data['scenario_type']='NodeFailure'; data['material']=material
            data['node_table']=r['node_table']; data['replacement_table']=r['replacement_table']
            warnings.append('库存与替代容量为 S 类/参考情景参数；真实企业应用需替换为企业实际数据。')
        else:
            return {'status':'insufficient','data':None,'warnings':[],'data_gaps':[f'未知情景 {scenario_type}'],'model_version':'scenario_v2.0'}
        return {'status':'success','data':data,'warnings':warnings,'data_gaps':[],
                'data_version':'2026-09-06-integrated-mvp','model_version':'scenario_v2.0'}
    except Exception as e:
        return {'status':'insufficient','data':None,'warnings':warnings,'data_gaps':[str(e)],'model_version':'scenario_v2.0'}
