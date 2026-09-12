from tools.field_governance import contract_summary, evaluate_user_records


def test_field_contract_loaded():
    s=contract_summary()
    assert s['field_count'] == 51
    assert s['gap_count'] == 10
    assert '采购 Exposure' in s['categories']


def test_missing_procurement_weight_is_blocking():
    r=evaluate_user_records([{'material':'甘蔗','node_id':'SC01','purchase_weight':None}])
    assert r['status']=='insufficient'
    assert 'W' in r['missing_fields']


def test_unknown_share_preserved():
    r=evaluate_user_records([{'material':'甘蔗','node_id':'SC01','purchase_weight':0.7}])
    assert r['status']=='partial'
    assert abs(r['unknown_share_by_material']['甘蔗']-0.3)<1e-9
