from __future__ import annotations
import importlib.util
from core.paths import ENGINE_DIR
spec=importlib.util.spec_from_file_location('baseline_v2', ENGINE_DIR/'baseline_water_risk_v2.py')
b=importlib.util.module_from_spec(spec); spec.loader.exec_module(b)

def get_material_dependency(material: str) -> dict:
    if material not in b.MATERIAL_PARAMS:
        return {'status':'insufficient','data':None,'data_gaps':[f'未验证材料：{material}'],'warnings':[]}
    p=b.MATERIAL_PARAMS[material]
    return {
        'status':'success',
        'data':{'material':material,'BWD':p['BWD'],'DYS_low':p['DYS_min'],'DYS_base':p['DYS_mid'],'DYS_high':p['DYS_max'],'CTS':p['CTS'],'OA':p['OA'],
                'confidence':{'BWD':p['BWD_confidence'],'DYS':p['DYS_confidence'],'CTS':p['CTS_confidence'],'OA':p['OA_confidence']}},
        'warnings':['OA=0.75 当前仍为 S 类假设/Low confidence，应在结果中披露。'],
        'data_gaps':[]
    }
