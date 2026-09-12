"""Generate local synthetic export samples for visual acceptance; never calls AWS."""
import argparse
from pathlib import Path

from app.domain.models import Case, Factor, Totals
from app.domain.rules import default_rules
from app.domain.engine import review
from app.infrastructure.form_exports import TemplateFormRenderer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--template-dir', type=Path, default=Path('out_put_teamplate'))
    parser.add_argument('--out', type=Path, default=Path('.analysis/form-preview'))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    rules = default_rules()
    case = Case(id='synthetic-export', title='合成書表輸出驗證', subject_name='合成比準地',
        comparable_name='合成比較標的1', subject_section='TEST-A', comparable_section='TEST-B',
        revision=7, valuation_date='1150901', notes='合成資料，僅供版面驗證。',
        factors=[Factor(id=r['id'], subject='25', comparable='12', entered_rate=0,
                        subject_grade='稍優', comparable_grade='普通') for r in rules['rules']],
        totals=Totals(normal_price=123456, time_rate=0, adjusted_price=123456,
                      regional_carried=0, regional_detail=0, individual=0,
                      trial_price=123456, weight=100, absolute=0))
    renderer = TemplateFormRenderer(args.template_dir)
    result = review(case, rules)
    for kind in ['table3-xlsx', 'table4-xlsx', 'table5-xlsx']:
        artifact = renderer.render(case, result, rules, kind, '2026-09-12T00:00:00Z')
        output = args.out / artifact.filename
        output.write_bytes(artifact.data)
        print(output)


if __name__ == '__main__':
    main()
