# ACK Project Instrument Index Agent

ACK 프로젝트의 PFD에서 계기·밸브 목록을 만들고, 기존 Instrument Index 형식으로 검토·출력하는 Windows 데스크톱 도구입니다.

**입력:** PFD PDF + 사용자가 수정한 Instrument Index XLSX + 페이지 범위.

**출력:** 태그 PDF, Instrument Index XLSX, 검토 목록, 다시 열 수 있는 프로젝트 JSON.

현재 버전은 AI 판독 후보를 사람이 검토하는 도구입니다. 도면 전체의 검출 완전성, 계기 문자 판독, 밸브 형식 및 배관 추적의 정확도를 보증하는 무검토 제출 도구는 아닙니다. 가상 예제는 알려진 정답을 불러오는 예제이며 AI가 자동 판독한 결과로 표시하지 않습니다.

## 실행

Python 3.11 이상, Windows의 Tkinter가 필요합니다. 현재 작업 PC에서는 설치된 Python으로 `start.cmd`를 더블클릭하면 됩니다.

다른 PC에서는 `install.cmd`를 실행한 뒤 `start_venv.cmd`를 실행하세요. 또는:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe run.py
```

프로그램은 항상 빈 화면으로 시작합니다. 이전 프로젝트·도면·태그를 자동으로 복원하지 않으며, 기존 회사 작업을 불러오는 전용 버튼도 없습니다.

1. **PFD PDF**를 직접 선택합니다. 다른 PDF를 선택하면 이전 도면의 검토 목록과 상세 편집 항목을 비웁니다.
2. 태그 데이터가 없는 ACK 기본 엑셀 양식이 준비됩니다. 필요하면 **엑셀 템플릿**에서 사용자가 직접 기존 양식을 선택합니다.
3. 페이지를 `1-5`, `1,3,5-7`처럼 지정합니다. 선택하지 않은 페이지는 PDF에 남지만 새 태그를 넣지 않습니다.
4. 새 도면을 AI로 읽으려면 API 키를 입력하고 **AI 판독 · 이미지 전송**을 누릅니다.
5. 표의 태그를 선택해 도면 위치, 기호, J열 설명, L열 구경 원문·단위·근거, 제어계기 연결을 검토합니다.
6. 누락된 기호는 도면의 해당 위치를 더블클릭해 추가합니다. 종류·기호를 정하고 **번호 다시 부여**를 누릅니다.
7. 중복/연결 오류를 수정한 뒤 **PDF + INDEX 출력**을 누릅니다. 경고는 Review 시트에 남습니다.

저장한 작업을 다시 열려면 사용자가 **프로젝트 열기**로 JSON을 직접 선택해야 합니다. `가상 예제`는 회사 자료와 무관하게 코드로 생성한 도면만 사용합니다. 새로 입력·분석한 실제 자료는 로컬 프로젝트·API 캐시·출력물에 남을 수 있으므로 프로그램 폴더 전체를 공유하지 말고, 소스 패키징 도구가 만든 ZIP만 공유하세요.

## ACK 엑셀 형식

기존 파일의 2행 헤더와 B~N열 배치를 사용합니다. 템플릿의 헤더·기본 행 스타일과 일관된 기능 설명을 읽습니다.

| 열 | 필드 | 처리 |
|---|---|---|
| B/C | PLANT_NAME / UNIT_NAME | 선택한 ACK 템플릿 값, 화면에서 변경 가능 |
| D | LOOP_NAME | 계기 계열 문자 + 일련번호 |
| E | CMPNT_NAME | 중복 검증한 태그 |
| F | CMPNT_SERV | 가져온 사용자 행의 값 유지 |
| G/H/I | IO / SYSTEM / FUNCTION TYPE | 기본 매핑, 가져온 사용자 수정값 우선 |
| J | CMPNT_FUNC_TYPE_DESC | 사용자 템플릿의 일관된 분류 우선 |
| K | CLIENT_PIDNO | PDF 파일 내 페이지 번호 |
| L | LINE_NUM | 근거가 있는 인치 값 + B, 예: 3/4B, 1 1/2B |
| M/N | PO / AREA | 가져온 사용자 행의 값 유지 |

기본 기능 설명은 F 계기=`Flow Transmitter`, PI/PIC=`Pressure Transmitter`, TI/TIC=`Temperature Transmitter`, LI/LIC=`Level Transmitter`입니다. 연결된 FV/TV는 `Control Valve-Globe`라는 기존 업무 분류를 사용합니다. 이 이름은 실제 밸브 바디 형상을 도면만으로 확정했다는 뜻이 아닙니다. 템플릿의 `Flow Transmitter - DP` 같은 사용자 수정값은 우선합니다.

AI·PQI·SHQ 등은 글자만으로 확정하지 않습니다. 설명을 확정하지 못하면 `확인 필요`를 표시합니다. 기존 워크북의 `?`도 검토 대상으로 유지합니다.

## 태그와 구경 규칙

- 페이지가 바뀌어도 번호가 이어집니다. 기존에 고정한 태그는 유지합니다.
- FIC/FICQ/FQC는 연결 FV의 번호가 충돌하지 않도록 제어 유량 일련번호를 공유합니다. 따라서 각 접두어별로 중간 번호가 비어 있을 수 있습니다.
- FIC→FV, TIC→TV, PIC→PV, LIC→LV, HC→HV, WIC→WV. 연결은 신호선 근거가 있을 때만 적용합니다.
- 하나의 제어계기에 여러 밸브가 연결돼 동일 태그가 생기면 임의로 다른 번호를 붙이지 않고 오류로 표시합니다. 캐스케이드 계기에 가상 밸브를 추가하지 않습니다.
- `6"/8"`는 `6B/8B`로 둘 다 남깁니다. `3/4`는 분수로 처리합니다.
- `80Φ`, `270Φ`는 원문을 유지합니다. 실제 mm 직경을 호칭 인치 B로 임의 환산하지 않습니다.
- 용기·모터 직접 측정 및 미표기 배관은 `-`로 표시합니다. 구경 미상과 비배관 항목은 프로젝트의 단위/Review에서 구분합니다.
- 밸브의 배관과 연결 계기의 측정 배관은 서로 다를 수 있습니다. 가까운 숫자를 자동 복사하는 규칙은 사용하지 않습니다.

## AI 연동과 현재 검증 범위

OpenAI Responses API에 전체 페이지와 겹침 확대 이미지를 보내 기호·위치·구경 근거를 구조화된 JSON으로 받습니다. 이후 별도 호출로 제어계기와 밸브 연결을 대조합니다. 좌표 중복 제거, 번호, Excel/PDF 생성은 로컬 코드가 수행합니다.

```powershell
$env:OPENAI_API_KEY = "your-key"
$env:OPENAI_MODEL = "gpt-6-astra"
python run.py --analyze drawing.pdf --template index.xlsx --pages 1-5 --export outputs
```

키는 화면에서만 입력해도 되며 프로젝트/로그에 저장하지 않습니다. `.env.example`은 설정 예시이고 `.env`를 자동 로드하지 않습니다. 선택 페이지 이미지는 API로 전송되며 사용량에 따른 API 비용이 발생합니다. 요청에는 `store:false`를 사용합니다. 이것이 서비스 전체의 무보관을 보장하는 설정은 아닙니다.

API 키나 네트워크가 없어도 기존 프로젝트 검토, 수동 입력, 가상 예제, PDF/Excel 출력은 가능합니다. 실제 API 호출은 키가 있어야 하며, 이 버전의 개발 검증에서는 API 실호출 정확도를 측정하지 않았습니다. 네트워크 계층은 모의 응답으로 검증합니다.

중지는 다음 요청 전에 적용됩니다. 진행 중인 네트워크 요청은 최대 180초의 타임아웃까지 기다릴 수 있습니다. 완료된 판독 구역은 로컬 캐시에 저장되어 재시도에 재사용됩니다. 완료 페이지의 중간 프로젝트는 `local_data/cache/.../partial_project.json`에서 열 수 있습니다.

공식 API 문서: [이미지 입력](https://developers.openai.com/api/docs/guides/images-vision), [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs).

## 오프라인 예제 · 테스트

```powershell
python run.py --demo --export outputs
python -m unittest discover -s tests -v
```

가상 도면, 겹침 구역 좌표 변환, 페이지 간 번호, 밸브 번호 충돌, 템플릿 설명/서식 보존, Excel/PDF 태그 일치, API 거절·미완료 처리 등을 확인합니다.

기존 수정본과 태그 좌표 파일을 프로젝트로 가져오려면:

```powershell
python tools/import_reviewed.py --pdf drawing.pdf --workbook index.xlsx --register register.json --output local_data/current_project.json
```

좌표 레지스터는 `tag`, `page`, `x`, `y`, `kind`, `source` 필드를 가진 배열이며 x/y는 화면에 표시된 PDF 페이지의 point 좌표입니다. 도면이 다르면 기존 좌표를 재사용하지 마세요.

## GitHub

저장소 권장 이름은 `ack-project-instrument-index-agent`, 공개 범위 기본값은 **Private**입니다. 실행 자료와 API 키를 제외하는 `.gitignore` 및 허용 목록 기반 소스 패키징 도구를 포함합니다.

```powershell
python tools/package_source.py
```

패키지에는 소스·문서·테스트만 들어갑니다. 실제 PDF, XLSX, 스크린샷, 로컬 프로젝트 JSON, API 캐시, 출력물은 포함되지 않습니다.

Git/GitHub CLI가 설치되고 로그인되어 있다면 `tools/publish_github.ps1`로 비공개 새 저장소를 만들고 올릴 수 있습니다. 이 스크립트는 자동 실행하지 않습니다. GitHub 업로드는 로컬 프로젝트 생성과 별개이며, 저장소 URL이 나오기 전에는 업로드 완료가 아닙니다.

라이선스는 아직 지정하지 않았습니다. 이 프로젝트는 비공개 개발용이며 오픈소스 사용 권한을 별도로 부여하지 않습니다. PyMuPDF의 AGPL/상용 라이선스 등 의존성 조건은 배포 방식에 맞게 확인해야 합니다.
