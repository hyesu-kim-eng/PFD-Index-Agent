from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
import json
import math
import re
import uuid


CONTROL_POOLS = {'FICQ': 'FIC', 'FQC': 'FIC'}
VALVE_KIND = {'FIC': 'FV', 'FICQ': 'FV', 'FQC': 'FV', 'TIC': 'TV',
              'PIC': 'PV', 'LIC': 'LV', 'HC': 'HV', 'WIC': 'WV'}
HEADERS = ['PLANT_NAME', 'UNIT_NAME', 'LOOP_NAME', 'CMPNT_NAME', 'CMPNT_SERV',
           'CMPNT_SYS_IO_TYPE_NAME', 'SYSTEM_1', 'CMPNT_FUNC_TYPE_NAME',
           'CMPNT_FUNC_TYPE_DESC', 'CLIENT_PIDNO', 'LINE_NUM',
           'SPEC_CMPNT_PO_NO', 'ELECTRICAL_AREA_CALSSIFICATION']


@dataclass
class Symbol:
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    page: int = 1
    x: float = 0
    y: float = 0
    kind: str = 'UNKNOWN'
    category: str = 'instrument'
    raw_text: str = ''
    confidence: float = 0.5
    tag: str = ''
    tag_locked: bool = False
    controller_id: str = ''
    controller_tag: str = ''
    size: str = ''
    size_unit: str = 'unknown'
    size_evidence: str = ''
    description: str = ''
    notes: str = ''
    reviewed: bool = False
    excluded: bool = False
    overrides: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data):
        allowed = cls.__dataclass_fields__
        return cls(**{k: v for k, v in data.items() if k in allowed})


@dataclass
class Project:
    pdf: str = ''
    template: str = ''
    plant: str = 'ACK'
    unit: str = 'UNIT'
    selected_pages: list[int] = field(default_factory=list)
    symbols: list[Symbol] = field(default_factory=list)
    rules: dict = field(default_factory=dict)
    extraction: dict = field(default_factory=dict)

    def save(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(path)

    @classmethod
    def load(cls, path):
        data = json.loads(Path(path).read_text(encoding='utf-8-sig'))
        symbols = [Symbol.from_dict(s) for s in data.pop('symbols', [])]
        obj = cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        obj.symbols = symbols
        return obj


def parse_pages(text, page_count):
    if not text.strip():
        return list(range(1, page_count + 1))
    result = set()
    for part in text.split(','):
        part = part.strip()
        if not re.fullmatch(r'\d+(?:\s*-\s*\d+)?', part):
            raise ValueError('페이지는 1-5 또는 1,3,5-7 형식으로 입력하세요.')
        bits = [int(x.strip()) for x in part.split('-')]
        start, end = bits[0], bits[-1]
        if not 1 <= start <= end <= page_count:
            raise ValueError(f'페이지 범위는 1~{page_count} 안이어야 합니다.')
        result.update(range(start, end + 1))
    return sorted(result)


def normalize_size(raw, unit):
    """Never infer a nominal pipe size from a metric physical diameter."""
    raw = str(raw or '').strip()
    if not raw or raw == '-' or unit in ('unknown', 'not_applicable'):
        return '-'
    if unit == 'mm':
        match = re.fullmatch(r'(?:[ΦφØø]\s*)?(\d+(?:\.\d+)?)\s*(?:mm|[ΦφØø])?', raw, re.I)
        return match[1] + 'Φ' if match else raw
    if unit != 'inch':
        raise ValueError('구경 단위는 inch, mm, unknown, not_applicable 중 하나입니다.')
    raw = raw.replace('″', '"').replace('”', '"').replace('“', '"')
    raw = re.sub(r'\b(?:inch|inches)\b', '', raw, flags=re.I).strip()
    # Slash without quotes/B is a fraction, not two alternative integer sizes.
    if re.fullmatch(r'\d+(?:\s+\d+/\d+|/\d+|\.\d+)?', raw):
        parts = raw.split('/')
        if len(parts) > 1 and int(parts[-1]) == 0:
            raise ValueError('구경 분모는 0일 수 없습니다.')
        return raw + 'B'
    segments = re.split(r'\s*(?:/|,|\bor\b)\s*', raw)
    if all(re.fullmatch(r'\d+(?:\.\d+)?\s*(?:B|")', p) for p in segments):
        return '/'.join(re.sub(r'[B"\s]', '', p) + 'B' for p in segments)
    if re.fullmatch(r'\d+(?:\s+\d+/\d+|/\d+|\.\d+)?\s*(?:B|")', raw):
        return re.sub(r'[B"]', '', raw).strip() + 'B'
    raise ValueError(f'구경 표기를 확인하세요: {raw!r} (예: 3/4, 1 1/2, 6"/8")')


def deduplicate(symbols, distance=5.0):
    result = []
    for s in sorted(symbols, key=lambda a: -a.confidence):
        near = next((r for r in result if r.page == s.page and r.category == s.category
                     and math.hypot(r.x - s.x, r.y - s.y) < distance), None)
        if near is None:
            result.append(s)
        elif near.kind != s.kind:
            near.notes += f' [판독 충돌: {near.kind}/{s.kind}]'
            near.confidence = min(near.confidence, 0.5)
    return sorted(result, key=lambda s: (s.page, round(s.y / 35), s.x, s.y))


def number_symbols(symbols):
    active = [s for s in symbols if not s.excluded]
    by_id = {s.id: s for s in active}
    used = {s.tag for s in active if s.tag_locked and s.tag}
    if len(used) != sum(bool(s.tag_locked and s.tag) for s in active):
        raise ValueError('사용자가 고정한 태그가 중복됩니다. 먼저 수정하세요.')
    counters = defaultdict(int)
    # Keep the controller pools ahead of all locked related valve numbers.
    for tag in used:
        match = re.fullmatch(r'([A-Z]+)-(\d+)', tag)
        if match:
            kind, number = match[1], int(match[2])
            counters[CONTROL_POOLS.get(kind, kind)] = max(counters[CONTROL_POOLS.get(kind, kind)], number)
            reverse = {'FV': 'FIC', 'TV': 'TIC', 'PV': 'PIC', 'LV': 'LIC', 'WV': 'WIC', 'HV': 'HC'}
            if kind in reverse:
                counters[reverse[kind]] = max(counters[reverse[kind]], number)

    ordered = sorted(active, key=lambda s: (s.page, round(s.y / 35), s.x, s.y))
    for s in ordered:
        if s.tag_locked and s.tag:
            continue
        if s.category == 'valve':
            continue
        pool = CONTROL_POOLS.get(s.kind, s.kind)
        while True:
            counters[pool] += 1
            candidate = f'{s.kind}-{counters[pool]:03d}'
            linked_prefix = VALVE_KIND.get(s.kind)
            linked_tag = f'{linked_prefix}-{counters[pool]:03d}' if linked_prefix else ''
            if candidate not in used and linked_tag not in used:
                break
        s.tag = candidate
        used.add(candidate)
    for s in ordered:
        if s.category != 'valve' or not s.controller_id:
            continue
        parent = by_id.get(s.controller_id)
        if not parent or parent.category != 'instrument' or parent.kind not in VALVE_KIND:
            raise ValueError(f'{s.tag or s.id}: 연결 계기를 확인하세요.')
        match = re.fullmatch(r'[A-Z]+-(\d+)', parent.tag)
        if not match:
            raise ValueError(f'계기 태그 형식 오류: {parent.tag}')
        expected_kind = VALVE_KIND[parent.kind]
        expected = f'{expected_kind}-{match[1]}'
        if s.tag_locked and s.tag:
            if s.tag != expected:
                raise ValueError(f'{s.tag}: 연결 계기 {parent.tag}와 번호/종류가 다릅니다.')
        else:
            if expected in used:
                raise ValueError(f'하나의 제어계기에 밸브가 여러 개 연결되어 {expected}가 중복됩니다. 연결을 검토하세요.')
            s.kind, s.tag = expected_kind, expected
            used.add(expected)
        s.controller_tag = parent.tag
    # Allocate independent valves after the linked valve tags have been reserved.
    for s in ordered:
        if s.category != 'valve' or s.controller_id or (s.tag_locked and s.tag):
            continue
        while True:
            counters[s.kind] += 1
            candidate = f'{s.kind}-{counters[s.kind]:03d}'
            if candidate not in used:
                break
        s.tag = candidate
        s.controller_tag = ''
        used.add(candidate)
    return symbols


def description_for(s, learned=None):
    if s.description:
        return s.description
    if learned and s.kind in learned:
        return learned[s.kind]
    if s.category == 'valve':
        if s.kind == 'UNKNOWN':
            return '확인 필요'
        if s.kind == 'HV' and not s.controller_id:
            return 'Manual Valve'
        return {'RV': 'Rotary Valve', 'SV': 'Slide Gate Valve', 'DV': 'Diverter Valve',
                'XV': 'On/Off Valve'}.get(s.kind, 'Control Valve-Globe')
    if s.kind.startswith('F'):
        return 'Flow Transmitter'
    if s.kind.startswith('P') and s.kind in ('PI', 'PIC', 'PA'):
        return 'Pressure Transmitter'
    if s.kind in ('TI', 'TIC'):
        return 'Temperature Transmitter'
    if s.kind in ('LI', 'LIC', 'LA'):
        return 'Level Transmitter'
    return {'HC': 'Hand Controller'}.get(s.kind, '확인 필요')


def validate(project):
    issues = []
    active = [s for s in project.symbols if not s.excluded]
    counts = Counter(s.tag for s in active)
    id_counts = Counter(s.id for s in active)
    by_id = {s.id: s for s in active}
    for s in active:
        def issue(level, message):
            issues.append({'level': level, 'tag': s.tag, 'page': s.page, 'message': message, 'id': s.id})
        if not re.fullmatch(r'[A-Z]+-\d{3,}', s.tag):
            issue('error', '태그 형식 오류/미부여')
        if counts[s.tag] > 1:
            issue('error', '중복 태그')
        if id_counts[s.id] > 1:
            issue('error', '중복 항목 ID')
        if s.tag and s.tag.split('-')[0] != s.kind:
            issue('error', '태그 접두어와 계기/밸브 종류가 다름')
        if not math.isfinite(s.x) or not math.isfinite(s.y) or s.x < 0 or s.y < 0:
            issue('error', '유효하지 않은 좌표')
        if s.page not in project.selected_pages:
            issue('error', '선택 범위 밖의 태그')
        if project.extraction.get('model') and set(project.extraction.get('completed_pages', [])) != set(project.selected_pages):
            issue('error', '선택 페이지의 AI 판독이 일부만 완료됨: 재시도하거나 페이지 범위를 수정하세요.')
        if not re.fullmatch(r'[A-Z]{1,10}', s.kind) or s.kind == 'UNKNOWN':
            issue('warning', '기호 판독 필요')
        if s.confidence < 0.85 and not s.reviewed:
            issue('warning', '기호/위치 신뢰도 검토 필요')
        if not s.reviewed:
            issue('warning', '사람 검토 미완료')
        if s.category == 'valve' and s.controller_id:
            parent = by_id.get(s.controller_id)
            if parent is None:
                issue('error', '연결 계기가 없거나 제외됨')
            elif parent.kind not in VALVE_KIND or s.tag != f"{VALVE_KIND[parent.kind]}-{parent.tag.split('-')[-1]}":
                issue('error', '제어계기와 밸브 태그가 불일치')
        try:
            size = normalize_size(s.size, s.size_unit)
            if size != '-' and not s.size_evidence.strip():
                issue('warning', '구경 근거 누락')
            if s.size_unit == 'unknown':
                issue('warning', '배관 구경 확인 필요')
            if s.size_unit == 'mm':
                issue('warning', '미터계 구경: 호칭 인치로 임의 환산하지 않음')
        except ValueError as exc:
            issue('error', str(exc))
        if description_for(s, project.rules) in ('확인 필요', '?', ''):
            issue('warning', '계기 기능 설명 확인 필요')
    return issues
