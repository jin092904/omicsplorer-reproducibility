# 복합 질의 결과 수집 입력 준비 안내

상태: 수집 입력 변환기 준비, 실제 외부 서비스 호출 전

## 목적

동결된 `01-query-authoring-sheet.csv`의 영어 질의 60개를 기존 외부 서비스 수집기가 읽는 JSONL 형식으로 기계적으로 변환한다. 변환 과정에서는 질의를 번역·축약·확장하거나 서비스별 문법에 맞게 고치지 않는다.

## 변환기가 확인하는 사항

- 질의와 기대 조건이 각각 60개인지
- simple, medium와 complex가 각각 20개인지
- 질의 ID가 중복되지 않고 두 CSV에서 일치하는지
- 질의 작성자가 Hojin Lee로 기록되어 있는지
- 원래 작성 언어가 한국어인지
- 질의와 기대 조건이 결과를 보기 전에 작성되었다고 확인됐는지
- 기대 조건에 Hojin Lee의 사람 검토 완료 기록이 있는지
- JSONL의 영어 문장이 CSV의 `query_en`과 글자 단위로 같은지

## 오프라인 입력 생성

다음 명령은 외부 서비스에 접속하지 않는다. 생성물은 Git에서 제외되는 `build/` 아래에 둔다.

```bash
uv run python scripts/export_complex_query_run_input.py \
  --query-csv protocols/complex-query-evaluation-v1/01-query-authoring-sheet.csv \
  --criteria-csv protocols/complex-query-evaluation-v1/02-expected-criteria-sheet.csv \
  --output build/complex-query-evaluation-v1
```

생성물은 다음 두 파일이다.

- `queries_en.confirmatory.jsonl`: 세 서비스에 동일하게 전달할 영어 free-text 질의 60개
- `queries_en.confirmatory.manifest.json`: 원본 CSV와 출력 JSONL의 SHA-256, 개수와 난이도 분포

## 실제 수집 전에 필요한 값

- `OMICSPLORER_API_BASE`: 평가할 OmicsPlorer API 주소
- `NCBI_EMAIL`: NCBI E-utilities 정책에 사용할 연구자 이메일
- `NCBI_API_KEY`: 선택 사항이며 사용 여부만 실행 manifest에 남김
- 출력 경로: raw 응답이 공개 Git에 들어가지 않는 별도 보관 위치
- 실행 코드 commit과 clean Git 상태

환경변수의 실제 값이나 API key는 Git 파일, 명령 출력 또는 실행 manifest에 저장하지 않는다.

## 실제 수집 명령 형태

아래 명령은 세 서비스에 실제 요청을 보내므로 실행 조건을 최종 확인한 뒤 사용한다.

```bash
uv run python -m genofinder_eval.external \
  --queries build/complex-query-evaluation-v1/queries_en.confirmatory.jsonl \
  --output /private/path/complex-query-run-v1 \
  --repo . \
  --systems omicsplorer_geo ncbi_geo omicsdi_geo \
  --top-k 10 \
  --seed 20260902
```

수집기는 질의 순서를 고정 seed로 섞고 시스템 시작 순서를 교대한다. 성공 응답뿐 아니라 timeout, HTTP 오류와 재시도도 보존한다. 한 번 완료된 응답은 `--force`를 주지 않는 한 다시 요청하지 않으므로 중단 후 이어서 실행할 수 있다.

## 수집 이후 순서

1. 60개 × 3개 서비스의 성공·실패 수와 manifest를 확인
2. raw 응답의 체크섬과 안전한 비공개 보관 위치를 확정
3. 같은 GSE를 합쳐 시스템명과 원래 순위를 가린 후보 판정표 생성
4. 관련성 판정 시작 전에 판정자 수와 절차를 별도 amendment로 고정

판정 계획이 확정되기 전에는 후보의 관련성 점수를 작성하지 않는다.
