"""Bridge an edited Index plus a coordinate register into a reviewable project.

Input drawing/workbook/register remain local; never commit them.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import openpyxl
from pfd_index.domain import Project,Symbol
from pfd_index.exporter import inspect_template


def import_reviewed(pdf,workbook,register,output):
    raw=json.loads(Path(register).read_text(encoding='utf-8-sig'))
    coordinates={item['tag']:item for item in raw}
    book=openpyxl.load_workbook(workbook);sheet=book.active
    template=inspect_template(workbook)
    project=Project(pdf=str(Path(pdf).resolve()),template=str(Path(workbook).resolve()),
                    plant=template['plant'],unit=template['unit'],rules=template['rules'],
                    extraction={'status':'imported_edited_workbook','source':'Existing edited workbook and coordinate register; not a new AI extraction'})
    for row in sheet.iter_rows(min_row=3):
        tag=row[4].value
        if not tag:continue
        if tag not in coordinates:raise ValueError(f'{tag}: 좌표 레지스터에 없습니다.')
        record=coordinates[tag];kind=str(tag).split('-')[0]
        valve=record.get('source') in ('control valve','valve symbol')
        size=str(row[11].value or '-').strip()
        if size=='-':
            unit='not_applicable' if kind in ('AI','SIC','SHQ','PQI','WIC','LI','LA') else 'unknown'
            raw_size=''
        elif 'Φ' in size or 'φ' in size:unit,raw_size='mm',size
        else:unit,raw_size='inch',size
        item=Symbol(page=int(row[10].value),x=record['x'],y=record['y'],kind=kind,
                    category='valve' if valve else 'instrument',raw_text=kind,confidence=.75,
                    tag=str(tag),tag_locked=True,size=raw_size,size_unit=unit,
                    size_evidence='기존 사용자 워크북 L열에서 가져옴. 자동 판독의 독립 검증 결과가 아님.' if size!='-' else '',
                    description=str(row[9].value or ''),notes='기존 작업에서 가져온 항목. 도면 기호/위치/연결은 검토 필요.',
                    controller_tag=str(row[15].value or '') if len(row)>15 else '',
                    overrides={str(c.column):c.value for c in row if c.value is not None and 2<=c.column<=14})
        project.symbols.append(item)
    by_tag={s.tag:s for s in project.symbols}
    for item in project.symbols:
        if item.controller_tag:
            if item.controller_tag not in by_tag:raise ValueError(f'{item.tag}: 연결 계기가 워크북에 없습니다.')
            item.controller_id=by_tag[item.controller_tag].id
    project.selected_pages=sorted({s.page for s in project.symbols})
    project.save(output)
    return project


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['pdf','workbook','register','output']:p.add_argument('--'+name,required=True)
    args=p.parse_args()
    result=import_reviewed(**vars(args));print('Imported',len(result.symbols),'symbols')
