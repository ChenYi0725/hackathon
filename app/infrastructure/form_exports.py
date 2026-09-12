"""Fill the supplied worksheets and export Excel workbooks.

Only presentation mappings live here. No valuation arithmetic or Excel formulas
are executed. Missing fields stay explicit; the original templates are read-only.
"""
import io
import hashlib
import os
import warnings
from copy import copy
from functools import lru_cache
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import BadZipFile

from app.application.export_contracts import ExportArtifact, ExportUnavailable

STATUS = {'pass': '通過', 'error': '疑似錯誤', 'pending': '待確認', 'missing': '資料不足'}
TEMPLATES = {'3': ('表3*.xlsx', '表3區段勘查表', 46, 22),
             '4': ('表4*.xlsx', '表4比較法調查估價表', 37, 18),
             '5': ('表5*.xlsx', '表5-1區域因素明細表(住)', 44, 13)}
INDIVIDUAL = dict(zip(range(9, 28), (
    'area', 'width', 'depth', 'shape', 'frontage', 'terrain', 'road_type',
    'road_width', 'school', 'market', 'park', 'station', 'business', 'nuisance',
    'parking', 'zoning', 'coverage', 'far', 'restriction')))
REGIONAL = {5: 'r_plan', 6: 'r_zoning', 7: 'r_coverage', 8: 'r_far',
    9: 'r_ban', 10: 'r_restriction', 12: 'r_road_width', 13: 'r_avg_width',
    14: 'r_station', 15: 'r_bus', 16: 'r_interchange', 17: 'r_development',
    19: 'r_sunlight', 20: 'r_landscape', 21: 'r_slope', 22: 'r_drainage',
    23: 'r_terrain', 25: 'r_improvement', 27: 'r_school', 28: 'r_market',
    29: 'r_park', 30: 'r_tourism', 31: 'r_parking', 32: 'r_service',
    34: 'r_utility', 35: 'r_funeral', 36: 'r_waste', 38: 'r_pollution', 40: 'r_other'}
SURVEY = {'H4': 'r_plan', 'H5': 'r_zoning', 'H6': 'r_coverage', 'H7': 'r_far',
    'H8': 'r_ban', 'H9': 'r_restriction', 'J11': 'r_road_width', 'G12': 'r_avg_width',
    'J19': 'r_interchange', 'I23': 'r_development', 'I24': 'r_sunlight',
    'I25': 'r_landscape', 'I26': 'r_slope', 'I27': 'r_drainage', 'I28': 'r_terrain',
    'I29': 'r_wind', 'I30': 'r_soil', 'R38': 'r_customers', 'R39': 'r_shops'}


def text(value):
    return '待補' if value is None or value == '' else str(value)


def put(ws, address, value):
    """Write literal text, including strings starting '='; never spreadsheet code."""
    from openpyxl.styles import Alignment
    from openpyxl.cell.cell import MergedCell
    cell = ws[address]
    if isinstance(cell, MergedCell):
        raise ExportUnavailable('書表模板合併儲存格與填值契約不符。')
    numeric = isinstance(value, (int, float)) and not isinstance(value, bool)
    cell.value = value if numeric else text(value)
    cell.data_type = 'n' if numeric else 's'
    cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
    font = copy(cell.font)
    font.color = '8A5200' if '待' in str(cell.value) or '未提供' in str(cell.value) else '174E44'
    cell.font = font


@lru_cache(maxsize=1)
def pdf_font():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfbase.ttfonts import TTFError
    candidates = [os.getenv('PDF_FONT_PATH'),
                  '/System/Library/Fonts/Supplemental/Arial Unicode.ttf',
                  str(Path(os.getenv('WINDIR', 'C:/Windows')) / 'Fonts/msjh.ttc'),
                  '/usr/share/fonts/truetype/arphic/uming.ttc']
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            try:
                pdfmetrics.registerFont(TTFont('ExportChinese', candidate))
            except TTFError as error:
                raise ExportUnavailable('PDF_FONT_PATH 字型無法嵌入；請使用 TrueType 輪廓的繁體中文字型。') from error
            return 'ExportChinese'
    raise ExportUnavailable('PDF 中文字型未設定；請以 PDF_FONT_PATH 指定支援繁體中文的 TrueType 字型。')


class TemplateFormRenderer:
    def __init__(self, template_dir):
        self.template_dir = Path(template_dir)

    def workbook(self, case, result, rules, number, generated_at):
        from openpyxl import load_workbook
        pattern, sheet_name, rows, cols = TEMPLATES[number]
        paths = sorted(self.template_dir.glob(pattern))
        if len(paths) != 1:
            raise ExportUnavailable(f'請在 FORM_TEMPLATE_DIR 放入唯一的表{number} Excel 模板。')
        source = paths[0].read_bytes()
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            try:
                wb = load_workbook(io.BytesIO(source), keep_links=False)
            except BadZipFile as error:
                raise ExportUnavailable(f'表{number} 模板不是有效的 XLSX 檔案。') from error
        if sheet_name not in wb:
            raise ExportUnavailable(f'表{number} 模板缺少指定工作表。')
        ws = wb[sheet_name]
        ws.sheet_state = 'visible'
        from openpyxl.utils import get_column_letter
        # Keep the source workbook's original sheets, formulas, names, links,
        # dimensions and print layout.  We only write the mapped input cells;
        # this is a filled copy of the supplied blank form, rather than a new
        # workbook assembled from cells.
        factors = {f.id: f for f in case.factors}
        def factor(fid, side):
            f = factors.get(fid)
            return None if f is None else getattr(f, side)
        note = (f'{case.title}｜案件 {case.id}｜版本 {case.revision}｜{case.locality} {case.land_use}｜'
                f'基準 {rules["id"]}/{rules["version"]}｜原填值草稿；待補／未確認值不得視為已核准')
        if number == '3':
            side = 'subject'
            put(ws, 'B3', case.valuation_date)
            put(ws, 'G3', getattr(case, side + '_section'))
            subject_location = case.subject_address or getattr(case, side + '_name')
            comparable_location = case.comparable_address or case.comparable_name
            put(ws, 'L3', f'{case.locality} {subject_location}；比較標的：{comparable_location}；範圍待核對')
            for address, fid in SURVEY.items():
                put(ws, address, factor(fid, side))
                # Facility type/name is not represented by the legacy case. Do not
                # turn a generic station distance into a high-speed-rail distance.
            for address in ['F11', 'F13', 'F14', 'F15', 'F16', 'F17', 'G18',
                    'F19', 'I20', 'I21', 'I22', 'E31', 'E32', 'E33', 'E34',
                    'F35', 'F36', 'F37', 'F38', 'F39', 'F40', 'F41', 'F42', 'F43', 'F44',
                    'R4', 'R6', 'R8', 'R10', 'R11', 'R12', 'R14', 'R16',
                    'R18', 'R19', 'R20', 'R21', 'R22', 'R23', 'R24', 'R25',
                    'R26', 'R27', 'R28', 'R29', 'S30', 'S32', 'S34', 'S36',
                    'R42', 'R43', 'Q44']:
                put(ws, address, '待補（見填值明細）')
            put(ws, 'L40', f'版本 {case.revision}｜草稿；完整資料見明細')
        elif number == '4':
            put(ws, 'L1', case.valuation_date)
            put(ws, 'O1', '案號：' + text(case.case_number))
            for address, value in {'F2': case.subject_name, 'J2': case.comparable_name,
                'D4': case.subject_name, 'G4': case.comparable_name,
                'D8': case.subject_section, 'G8': case.comparable_section,
                'G5': case.totals.normal_price, 'J6': case.totals.time_rate,
                'G7': case.totals.adjusted_price, 'J8': case.totals.regional_carried,
                'G29': case.totals.individual, 'G30': case.totals.absolute,
                'G31': case.totals.trial_price, 'I31': case.totals.weight,
                'G32': '待確認（未有獨立比準地比較價格欄位）', 'G6': '交易日期待補',
                'D33': case.notes, 'D34': note}.items():
                put(ws, address, value)
            for row, fid in INDIVIDUAL.items():
                for col, side in [('D', 'subject'), ('G', 'comparable'), ('J', 'entered_rate')]:
                    put(ws, f'{col}{row}', factor(fid, side))
            for col in ('K', 'O'):
                for row in range(4, 30):
                    put(ws, f'{col}{row}', '未提供標的')
            for address in ('N2', 'R2', 'K30', 'O30', 'K31', 'O31', 'D28', 'G28', 'J28'):
                put(ws, address, '未提供')
        else:
            put(ws, 'A2', '案號：' + text(case.case_number))
            put(ws, 'G2', case.comparable_name)
            put(ws, 'C3', case.subject_section)
            put(ws, 'E3', case.comparable_section)
            residential = '住宅' in case.land_use
            for row, fid in REGIONAL.items():
                for col, side in [('C', 'subject_grade'), ('E', 'comparable_grade'), ('G', 'entered_rate')]:
                    put(ws, f'{col}{row}', factor(fid, side) if residential else '基準不適用')
                for col in ('H', 'J', 'K', 'M'):
                    put(ws, f'{col}{row}', '未提供')
            for row in (11, 18, 24, 26, 33, 37, 39, 41):
                put(ws, f'E{row}', '小計待確認')
                put(ws, f'H{row}', '未提供')
                put(ws, f'K{row}', '未提供')
            put(ws, 'E42', case.totals.regional_detail if residential else '基準不適用')
            put(ws, 'H42', '未提供')
            put(ws, 'K42', '未提供')
            put(ws, 'B42', '各主要項目總修正數')
            put(ws, 'C43', case.subject_name)
            put(ws, 'E43', case.comparable_name)
            put(ws, 'C44', note + ('；此住宅表不適用商業案件' if not residential else ''))
        for sheet in wb:
            sheet.print_area = f'A1:{get_column_letter(cols)}{rows}'
            sheet.page_setup.orientation = 'portrait' if number in ('3', '5') else 'landscape'
            sheet.page_setup.paperSize = sheet.PAPERSIZE_A3
            sheet.page_setup.fitToWidth = 1
            sheet.page_setup.fitToHeight = 1
            sheet.sheet_properties.pageSetUpPr.fitToPage = True
        if number == '3' and case.additional_comparisons:
            primary = wb.copy_worksheet(ws)
            primary.title = '表3-比較標的1'
            put(primary, 'G3', case.comparable_section)
            put(primary, 'L3', f'{case.locality} {case.comparable_name}；範圍待核對')
            for address, fid in SURVEY.items():
                put(primary, address, factor(fid, 'comparable'))
        # Extend the existing confirmed column mappings; never omit extra comparisons.
        for index, comparison in enumerate(case.additional_comparisons, 2):
            extra = {f.id: f for f in comparison.factors}
            get = lambda fid, side: getattr(extra[fid], side) if fid in extra else None
            if number == '3':
                sheet = wb.copy_worksheet(ws)
                sheet.title = f'表3-比較標的{index}'
                put(sheet, 'G3', comparison.section)
                put(sheet, 'L3', f'{case.locality} {comparison.name}；範圍待核對')
                for address, fid in SURVEY.items():put(sheet, address, get(fid, 'comparable'))
            elif number == '4':
                col, rate, weight = ('K','N','M') if index == 2 else ('O','R','Q')
                for address,value in {rate+'2':comparison.name,col+'4':comparison.name,col+'8':comparison.section,
                    col+'5':comparison.totals.normal_price,rate+'6':comparison.totals.time_rate,
                    col+'7':comparison.totals.adjusted_price,rate+'8':comparison.totals.regional_carried,
                    col+'29':comparison.totals.individual,col+'30':comparison.totals.absolute,
                    col+'31':comparison.totals.trial_price,weight+'31':comparison.totals.weight}.items():put(ws,address,value)
                for row,fid in INDIVIDUAL.items():
                    put(ws,f'{col}{row}',get(fid,'comparable'))
                    put(ws,f'{rate}{row}',get(fid,'entered_rate'))
            else:
                col,rate = ('H','J') if index == 2 else ('K','M')
                put(ws,rate+'2',comparison.name);put(ws,col+'3',comparison.section);put(ws,col+'43',comparison.name)
                for row,fid in REGIONAL.items():
                    put(ws,f'{col}{row}',get(fid,'comparable_grade') if residential else '基準不適用')
                    put(ws,f'{rate}{row}',get(fid,'entered_rate') if residential else '基準不適用')
                for row in (11,18,24,26,33,37,39,41):put(ws,f'{col}{row}','小計待確認')
                put(ws,col+'42',comparison.totals.regional_detail if residential else '基準不適用')
        detail = wb.create_sheet('填值與審核明細')
        detail.append(['模板', paths[0].name, 'SHA256', hashlib.sha256(source).hexdigest()])
        for row in self.detail_rows(case, result, rules, generated_at):
            detail.append([text(v) for v in row])
        for row in detail:
            for cell in row:
                cell.data_type = 's'
        return wb

    @staticmethod
    def detail_rows(case, result, rules, generated_at):
        yield ['案件', case.title, '版本', case.revision]
        yield ['比準地地址', case.subject_address, '比較標的地址', case.comparable_address]
        yield ['基準', rules['id'], '基準版本', rules['version']]
        yield ['產出時間', generated_at, '狀態', '原填值草稿；詳見審核結果']
        yield ['案件備註', case.notes]
        yield ['限制', f'本案 {1+len(case.additional_comparisons)} 筆比較標的；表3設施名稱等缺值待補。']
        if result.get('run_id'):yield ['檢核快照', result['run_id']]
        yield ['因素', '比準地原填', '比較標的原填', '原填修正率', '確認', '來源頁', '引用／備註']
        names = {r['id']: r['name'] for r in rules['rules']}
        for f in case.factors:
            yield [names.get(f.id, f.id), f.subject, f.comparable, f.entered_rate,
                   '已確認' if f.confirmed else '待確認', f.evidence.page, f.evidence.quote + ' ' + f.note]
        for comparison in case.additional_comparisons:
            yield ['比較標的',comparison.id,comparison.name,comparison.section]
            for f in comparison.factors:
                yield [names.get(f.id,f.id),f.subject,f.comparable,f.entered_rate,
                       '已確認' if f.confirmed else '待確認',f.evidence.page,f.evidence.quote+' '+f.note]
        for decision in result.get('dispositions', []):
            yield ['人工處置',decision['check_id'],decision['decision'],decision['reason'],decision['at'],
                   '目前結果' if decision['run_id']==result.get('run_id') else '歷史處置',decision['technical_status']]
        yield ['檢核項目', '狀態', '原填值', '預期值', '說明', '原文頁', '基準頁']
        for r in result['checks']:
            yield [r['title'], STATUS[r['status']], r.get('actual'), r.get('expected'),
                   r['message'], r.get('page'), r.get('rule_page')]

    def review_workbook(self, case, result, rules, generated_at):
        """Build a locality-neutral workbook from the saved case snapshot."""

        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill

        wb = Workbook()
        summary = wb.active
        summary.title = '案件摘要'
        summary_rows = [
            ['欄位', '內容'],
            ['案件名稱', case.title],
            ['案件編號', case.case_number],
            ['案件版本', case.revision],
            ['估價基準日', case.valuation_date],
            ['適用地區', case.locality],
            ['用地類別', case.land_use],
            ['比準地', case.subject_name],
            ['比準地地址', case.subject_address],
            ['比較標的', case.comparable_name],
            ['比較標的地址', case.comparable_address],
            ['評價基準', f'{rules["name"]} / {rules["version"]}'],
            ['基準來源', rules['source']],
            ['產出時間', generated_at],
            ['審查狀態', '完成' if result['complete'] else '尚有待確認或資料不足'],
        ]
        for row in summary_rows:
            _append_literal_row(summary, row)

        factors = {factor.id: factor for factor in case.factors}
        for scope, title in (('regional', '區域因素'), ('individual', '個別因素')):
            sheet = wb.create_sheet(title)
            _append_literal_row(sheet, [
                '因素', '主要項目', '比準地原值', '比準地等級', '比較標的原值',
                '比較標的等級', '修正率(%)', '確認狀態', '來源頁', '引用／備註',
            ])
            for rule in rules['rules']:
                if rule['scope'] != scope:
                    continue
                factor = factors.get(rule['id'])
                _append_literal_row(sheet, [
                    rule['name'], rule['group'],
                    None if factor is None else factor.subject,
                    None if factor is None else factor.subject_grade,
                    None if factor is None else factor.comparable,
                    None if factor is None else factor.comparable_grade,
                    None if factor is None else factor.entered_rate,
                    '已確認' if factor is not None and factor.confirmed else '待確認',
                    rule['source_page'] if factor is None else factor.evidence.page,
                    '' if factor is None else (factor.evidence.quote + ' ' + factor.note).strip(),
                ])

        checks = wb.create_sheet('審查結果')
        _append_literal_row(checks, ['檢核項目', '狀態', '原填值', '預期值', '說明', '原文頁', '基準頁'])
        for item in result['checks']:
            _append_literal_row(checks, [
                item['title'], STATUS[item['status']], item.get('actual'),
                item.get('expected'), item['message'], item.get('page'),
                item.get('rule_page'),
            ])

        header_fill = PatternFill('solid', fgColor='E8F0EA')
        for sheet in wb.worksheets:
            sheet.freeze_panes = 'A2'
            sheet.auto_filter.ref = sheet.dimensions
            for cell in sheet[1]:
                cell.font = Font(bold=True, color='174E44')
                cell.fill = header_fill
            for row in sheet.iter_rows():
                for cell in row:
                    cell.alignment = Alignment(vertical='top', wrap_text=True)
            for column in sheet.columns:
                letter = column[0].column_letter
                width = min(55, max(12, max(len(str(cell.value or '')) for cell in column) + 2))
                sheet.column_dimensions[letter].width = width
        return wb

    def render(self, case, result, rules, kind, generated_at):
        if kind == 'review-xlsx':
            wb = self.review_workbook(case, result, rules, generated_at)
        elif kind in ('table3-xlsx', 'table4-xlsx', 'table5-xlsx'):
            wb = self.workbook(case, result, rules, kind[5], generated_at)
        else:
            raise KeyError(kind)
        stream = io.BytesIO()
        wb.save(stream)
        return ExportArtifact(
            stream.getvalue(), f'{kind.rsplit("-", 1)[0]}-{case.id}-r{case.revision}.xlsx',
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', case.revision)

    @staticmethod
    def report_pdf(case, result, rules, generated_at):
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.platypus import SimpleDocTemplate, Paragraph, LongTable, TableStyle, Spacer
        font = pdf_font()
        style = ParagraphStyle('Chinese', fontName=font, fontSize=9, leading=13, wordWrap='CJK')
        p = lambda value: Paragraph(escape(text(value)).replace('\n', '<br/>'), style)
        stream = io.BytesIO()
        doc = SimpleDocTemplate(stream, pagesize=landscape(A4), leftMargin=28, rightMargin=28,
                                topMargin=28, bottomMargin=28, title=case.title)
        rows = [[p(v) for v in ['檢核項目', '狀態', '原填值', '預期值', '依據與說明']]]
        for r in result['checks']:
            evidence = r.get('evidence', {})
            locator = (f"文件 {evidence['document_id']} / {evidence.get('sheet') or ''} {evidence.get('cell') or ''} / p.{evidence.get('page')}"
                       if evidence.get('document_id') else '人工輸入／程式重算，見案件快照')
            located = {}
            labels = dict(subject='比準地條件', comparable='比較標的條件', entered_rate='修正率',
                          subject_grade='比準地等級', comparable_grade='比較標的等級')
            for side, source in r.get('input_sources', {}).items():
                if source.get('document_id'):
                    key = (source['document_id'], source.get('sheet') or '', source.get('cell') or '', source.get('page'))
                    located.setdefault(key, []).append(labels.get(side, side))
            if located:
                locator = '\n'.join('/'.join(sides) + f'：文件 {docid} / {sheet} {cell} / p.{page}'
                                    for (docid, sheet, cell, page), sides in located.items())
            rows.append([p(v) for v in [r['title'], STATUS[r['status']], r.get('actual'), r.get('expected'),
                f'{r["message"]}\n{locator}\n基準 p.{text(r.get("rule_page"))} / {r.get("formula_id", "程式規則")}']])
        table = LongTable(rows, colWidths=[132, 58, 65, 65, 465], repeatRows=1, splitInRow=1)
        table.setStyle(TableStyle([('GRID', (0, 0), (-1, -1), .3, '#9DAFA8'),
                                  ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                                  ('BACKGROUND', (0, 0), (-1, 0), '#EAF3EF')]))
        story = [p('地衡｜逐項審查結果'), p(case.title),
            p(f'案件 {case.id}｜版本 {case.revision}｜基準 {rules["id"]}/{rules["version"]}'),
            p(f'比準地 {case.subject_name}／比較標的 {case.comparable_name}｜基準日 {case.valuation_date}'),
            p('輔助審查草稿；' + ('全部檢核通過' if result['complete'] else '尚有疑點或待確認項目')),
            p(case.notes), p(generated_at)]
        if result.get('run_id'):story.append(p('檢核快照：'+result['run_id']))
        for comparison in case.additional_comparisons:story.append(p(f'比較標的 {comparison.id} / {comparison.name} / {comparison.section}'))
        story.extend([Spacer(1,12),table,Spacer(1,12),p('人工處置（不改變程式技術判定）')])
        for decision in result.get('dispositions', []):
            story.append(p(f"{decision['check_id']} / {decision['decision']} / {decision['reason']} / {decision['at']} / "+
                           ('目前結果' if decision['run_id']==result.get('run_id') else '歷史處置')))
        def footer(canvas, doc):
            canvas.saveState();canvas.setFont(font,8);canvas.drawRightString(805,14,f'案件版本 {case.revision} / 第 {doc.page} 頁');canvas.restoreState()
        doc.build(story,onFirstPage=footer,onLaterPages=footer)
        return stream.getvalue()


def _append_literal_row(sheet, values):
    sheet.append(list(values))
    for cell in sheet[sheet.max_row]:
        if isinstance(cell.value, str):
            cell.data_type = 's'
