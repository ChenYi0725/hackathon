from copy import deepcopy
from decimal import Decimal
import pytest
from app.engine import classify, review
from app.rules import default_rules
from app.sample import sample_case
from app.main import validate_ruleset


def rule(key):return next(r for r in default_rules()['rules'] if r['id']==key)


@pytest.mark.parametrize('key,value,expected',[
    ('width','4.99','劣'),('width','5','稍劣'),('width','10','普通'),
    ('depth','39.99','稍優'),('depth','40','優'),('depth','99.99','優'),('depth','100','劣'),
    ('school','199.99','優'),('school','200','稍優'),('school','無','劣'),
    ('nuisance','99.99','劣'),('nuisance','100','稍劣'),('nuisance','500','優'),('nuisance','無','優'),
    ('r_market','區段內有','優'),('r_market','0','稍優'),('r_market','500','普通'),
    ('far','240','稍優'),('r_far','240','優'),('terrain','緩坡','普通')])
def test_boundaries_and_scopes(key,value,expected):
    r=rule(key);assert r['bands'][classify(value,r)]['label']==expected


@pytest.mark.parametrize('value',[None,'','-','—','NaN','Infinity','-1','5 m','不存在的類型'])
def test_missing_invalid_and_nonfinite_do_not_become_zero(value):assert classify(value,rule('width')) is None


def test_absence_not_in_source_requires_review():assert classify('無',rule('r_waste')) is None


def test_original_example_has_no_unsubstantiated_errors():
    result=review(sample_case(),default_rules())
    assert result['counts']['error']==0
    assert result['computed']['individual']==13
    assert result['computed']['regional'] is None
    assert not result['complete']
    for key in ['adjusted','trial','r_bus','r_tourism']:
        assert next(x for x in result['checks'] if x['id']==key)['status']=='pending'


def test_positive_negative_and_absolute_sum():
    c=sample_case();f=next(f for f in c.factors if f.id=='road_width')
    f.subject,f.comparable=f.comparable,f.subject;f.entered_rate=-5
    c.totals.individual=3;c.totals.absolute=15
    checks={r['id']:r for r in review(c,default_rules())['checks']}
    assert checks['road_width']['expected']==-5
    assert checks['norm_individual']['status']=='pass'
    assert checks['absolute']['status']=='pass'


def test_demo_catches_injected_faults_and_defers_missing_data():
    checks={r['id']:r for r in review(sample_case(True),default_rules())['checks']}
    assert checks['road_width']['status']=='error'
    assert checks['road_width']['expected']==5
    assert checks['school']['status']=='missing'
    assert checks['sum_individual']['status']=='error'
    assert checks['cross']['status']=='error'
    assert checks['norm_individual']['status']=='pending'


def test_unconfirmed_and_exemption_never_auto_pass():
    c=sample_case();c.factors[0].confirmed=False
    c.factors[1].exempt=True;c.factors[1].note='特殊情形'
    checks={r['id']:r for r in review(c,default_rules())['checks']}
    assert checks['area']['status']=='pending'
    assert checks['width']['status']=='pending'
    assert checks['norm_individual']['status']=='pending'


def test_scope_mismatch_blocks_factor_decisions():
    c=sample_case();c.land_use='農業用地'
    result=review(c,default_rules())
    assert all(r['status']=='pending' for r in result['checks'] if r.get('factor_id'))


def test_missing_regional_grade_and_inconsistent_same_section():
    c=sample_case();next(f for f in c.factors if f.id=='r_coverage').subject_grade=None
    next(f for f in c.factors if f.id=='r_road_width').comparable='6'
    checks={r['id']:r for r in review(c,default_rules())['checks']}
    assert checks['r_coverage']['status']=='missing'
    assert checks['r_road_width']['status']=='error'
    assert checks['norm_regional_detail']['status']=='pending'


def test_special_adjustment_explanation_requires_human_judgment():
    c=sample_case();c.factors[7].entered_rate=2;c.factors[7].note='特殊情形調整'
    result=review(c,default_rules())
    assert next(r for r in result['checks'] if r['id']=='road_width')['status']=='pending'


def test_rule_validation_rejects_ambiguous_ranges_and_bad_matrix():
    r=default_rules();assert len(validate_ruleset(r)['rules'])==47
    bad=deepcopy(r);bad['rules'][0]['bands'][0]['low']=80
    with pytest.raises(ValueError,match='重疊'):validate_ruleset(bad)
    bad=deepcopy(r);bad['rules'][0]['matrix'][0]=[0]
    with pytest.raises(ValueError,match='矩陣'):validate_ruleset(bad)
    bad=deepcopy(r);bad['rules'][0]['matrix'][0][1]=float('inf')
    with pytest.raises(ValueError):validate_ruleset(bad)


@pytest.mark.parametrize('confirmed,price,expected', [(True, 100, 102), (False, 100, None), (True, None, None)])
def test_empty_calculated_output_keeps_suggestion_only_with_confirmed_inputs(confirmed, price, expected):
    case = sample_case()
    case.totals.normal_price = price
    case.totals.time_rate = 2
    case.totals.adjusted_price = None
    case.totals_confirmed = confirmed
    check = next(row for row in review(case, default_rules())['checks'] if row['id'] == 'adjusted')
    assert check['actual'] is None
    assert check['expected'] == expected
    assert check['status'] == ('error' if expected is not None else 'pending')
    assert case.totals.adjusted_price is None
