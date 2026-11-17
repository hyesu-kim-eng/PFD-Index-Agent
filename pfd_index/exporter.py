from __future__ import annotations

from collections import Counter, defaultdict
import copy
import csv
from datetime import datetime
from pathlib import Path
import re

import fitz
import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill

from .domain import HEADERS, Project, Symbol, description_for, normalize_size, validate


def inspect_template(path):
    w = openpyxl.load_workbook(path)
    s = w.active
    expected = {'B2': 'PLANT_NAME', 'E2': 'CMPNT_NAME', 'J2': 'CMPNT_FUNC_TYPE_DESC',
                'K2': 'CLIENT_PIDNO', 'L2': 'LINE_NUM'}
    for cell, value in expected.items():
        if s[cell].value != value:
            raise ValueError(f'템플릿 {cell}은 {value}여야 합니다. 기존 Instrument Index 형식을 선택하세요.')
    groups = defaultdict(Counter)
    for row in s.iter_rows(min_row=3):
        tag, desc = row[4].value, row[9].value
        if tag and desc and str(desc).strip() not in ('?', '확인 필요', 'Transmitter'):
            kind = str(tag).split('-')[0]
            groups[kind][str(desc)] += 1
    # Do not learn conflicting descriptions as if the most frequent were authoritative.
    rules = {kind: next(iter(counts)) for kind, counts in groups.items() if len(counts) == 1}
    return {'plant': s['B3'].value or '', 'unit': s['C3'].value or '', 'rules': rules}


def make_template(path):
    w = openpyxl.Workbook()
    s = w.active
    s.title = 'Instrument Index'
    for column, name in enumerate(HEADERS, 2):
        cell = s.cell(2, column, name)
        cell.font = Font(name='Calibri', size=10, bold=True, color='FFFFFF')
        cell.fill = PatternFill('solid', fgColor='173D55')
        cell.alignment = Alignment(vertical='center', wrap_text=True)
        s.column_dimensions[cell.column_letter].width = 21
        s.cell(3, column).font = Font(name='Calibri', size=10)
    s.column_dimensions['J'].width = 32
    s.row_dimensions[2].height = 32
    s.freeze_panes = 'F3'
    w.save(path)


def export_workbook(project, path):
    if project.template:
        inspect_template(project.template)
        w = openpyxl.load_workbook(project.template)
    else:
        raise ValueError('템플릿을 선택하세요.')
    s = w.active
    styles = {c.column: copy.copy(c._style) for c in s[3]}
    last = s.max_column
    height = s.row_dimensions[3].height or 17
    if s.max_row > 2:
        s.delete_rows(3, s.max_row-2)
    for merged in list(s.merged_cells.ranges):
        if merged.min_row >= 3:
            s.unmerge_cells(str(merged))
    active = sorted((x for x in project.symbols if not x.excluded),
                    key=lambda x: (x.page, round(x.y/35), x.x, x.y))
    for row, item in enumerate(active, 3):
        serial = item.tag.split('-')[-1]
        kind = item.kind
        is_valve = item.category == 'valve'
        func = kind if is_valve else {'F': 'FT', 'T': 'TT', 'P': 'PT', 'L': 'LT'}.get(kind[:1], kind)
        values = {2: project.plant, 3: project.unit, 4: f'{kind[:1]}-{serial}', 5: item.tag,
                  7: 'AO' if is_valve else 'AI', 8: 'DCS', 9: func,
                  10: description_for(item, project.rules), 11: item.page,
                  12: normalize_size(item.size, item.size_unit)}
        # Imported edited rows preserve the user's service, IO and description choices.
        for col, value in item.overrides.items():
            if int(col) not in (5, 11, 12):
                values[int(col)] = value
        # The existing user format may have optional traceability columns O/P/Q.
        optional = {15: ('PDF_PAGE', item.page), 16: ('CONTROLLER_TAG', item.controller_tag),
                    17: ('SOURCE_NOTE', 'valve symbol' if is_valve else 'bubble')}
        for col, (name, value) in optional.items():
            if s.cell(2, col).value == name:
                values[col] = value
        for col in range(1, last+1):
            cell = s.cell(row, col)
            if col in styles:
                cell._style = copy.copy(styles[col])
            cell.value = values.get(col)
        s.row_dimensions[row].height = height
    s.auto_filter.ref = f'B2:{openpyxl.utils.get_column_letter(last)}{max(2,len(active)+2)}'
    s.print_area = f'B2:N{len(active)+2}'
    s.freeze_panes = 'F3'
    if 'Review' in w.sheetnames:
        del w['Review']
    review = w.create_sheet('Review')
    review.append(['TAG', 'PDF_PAGE', 'LEVEL', 'CHECK', 'SIZE_EVIDENCE', 'CONFIDENCE', 'HUMAN_REVIEWED'])
    by_id = {s.id: s for s in project.symbols}
    for issue in validate(project):
        item = by_id[issue['id']]
        review.append([issue['tag'], issue['page'], issue['level'], issue['message'],
                       item.size_evidence, item.confidence, 'Y' if item.reviewed else 'N'])
    for cell in review[1]:
        cell.font = Font(bold=True, color='FFFFFF')
        cell.fill = PatternFill('solid', fgColor='173D55')
    for col, width in {'A': 18, 'B': 12, 'C': 12, 'D': 44, 'E': 80, 'F': 15, 'G': 20}.items():
        review.column_dimensions[col].width = width
    review.freeze_panes = 'A2'
    review.auto_filter.ref = review.dimensions
    w.save(path)


def label_candidates(x, y, width, height):
    for dx, dy in [(6, 5), (6, -14), (-width-6, 5), (-width/2, 8),
                   (-width/2, -16), (6, 17), (-width-6, -14)]:
        yield fitz.Rect(x+dx, y+dy, x+dx+width, y+dy+height)


def export_pdf(project, path):
    with fitz.open(project.pdf) as doc:
        for page in doc:
            for a in list(page.annots() or []):
                if a.info.get('title') == 'PFD Index Agent':
                    page.delete_annot(a)
        placed = defaultdict(list)
        obstacles = defaultdict(list)
        for item in project.symbols:
            if not item.excluded:
                obstacles[item.page].append(fitz.Rect(item.x-5,item.y-5,item.x+5,item.y+5))
        for item in project.symbols:
            if item.excluded:
                continue
            page = doc[item.page-1]
            if not page.rect.contains(fitz.Point(item.x,item.y)):
                raise ValueError(f'{item.tag}: 페이지 범위 밖의 좌표입니다.')
            width = fitz.get_text_length(item.tag, fontsize=6)+5
            candidates = [r for r in label_candidates(item.x,item.y,width,10) if page.rect.contains(r)]
            if not candidates:
                raise ValueError(f'{item.tag}: 글상자 위치를 페이지 안으로 옮겨주세요.')
            rect = min(candidates, key=lambda r: sum((r & p).get_area()*5 for p in placed[item.page])+
                       sum((r & p).get_area()*10 for p in obstacles[item.page]))
            placed[item.page].append(rect)
            # Rendering/review coordinates are rotated page coordinates; annotations use unrotated coordinates.
            actual = rect * page.derotation_matrix
            a = page.add_freetext_annot(actual, item.tag, fontsize=6, text_color=(0,0,0),
                                        fill_color=(1,1,1), rotate=(360-page.rotation)%360)
            a.set_info(title='PFD Index Agent', subject=item.controller_tag or item.kind)
            doc.xref_set_key(a.xref, 'BS/W', '0.7')
        first = Path(path).with_suffix('.stage.pdf')
        doc.save(first, garbage=4, deflate=True)
    # Final saved appearance patch: preserve editable FreeText and a red border.
    with fitz.open(first) as doc:
        for page in doc:
            for a in page.annots() or []:
                if a.info.get('title') != 'PFD Index Agent':
                    continue
                ap = int(doc.xref_get_key(a.xref, 'AP/N')[1].split()[0])
                stream = doc.xref_stream(ap).replace(b'0 0 0 RG', b'1 0 0 RG')
                doc.update_stream(ap, stream)
        doc.save(path, garbage=4, deflate=True)
    first.unlink()


def export_bundle(project, output_root):
    issues = validate(project)
    errors = [i for i in issues if i['level'] == 'error']
    if errors:
        raise ValueError('출력 전 오류를 수정하세요: ' + '; '.join(i['tag']+': '+i['message'] for i in errors[:6]))
    if not any(not s.excluded for s in project.symbols):
        raise ValueError('출력할 태그가 없습니다.')
    # New folder every time: never overwrite the user's edited template or previous deliverable.
    folder = Path(output_root)/datetime.now().strftime('export_%Y%m%d_%H%M%S_%f')
    folder.mkdir(parents=True, exist_ok=False)
    try:
        export_workbook(project, folder/'Instrument_Index.xlsx')
        export_pdf(project, folder/'PFD_Tagged.pdf')
        project.save(folder/'project.json')
        with (folder/'Review.csv').open('w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['level','tag','page','message','id'])
            writer.writeheader()
            writer.writerows(issues)
        (folder/'export_status.txt').write_text(
            f'Tags: {sum(not s.excluded for s in project.symbols)}\nWarnings: {len(issues)}\n'
            'AI extraction is not a completeness or engineering accuracy certification.\n'
            'Resolve the Review sheet and verify the drawing before submission.\n', encoding='utf-8')
    except Exception:
        (folder/'INCOMPLETE.txt').write_text('Export failed. This folder is not a complete deliverable.',encoding='utf-8')
        raise
    return folder
