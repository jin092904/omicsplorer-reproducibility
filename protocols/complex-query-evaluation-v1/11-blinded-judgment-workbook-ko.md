# 단일 판정자용 비공개 판정 워크북 안내

버전: v1

고정 seed: `20260902`

판정자: Hojin Lee

관련 프로토콜: `10-protocol-amendment-02-single-annotator.md`

## 이 단계에서 하는 일

세 검색 시스템이 반환한 후보를 GEO Series 단위로 합친 뒤 중복을 제거한다. 시스템명, 원래 순위, 점수와 몇 개 시스템이 같은 후보를 반환했는지는 숨긴다. 판정자는 질의와 사전 고정 조건, 후보의 공개 metadata만 보고 관련성을 기록한다.

생성 코드는 후보를 자동으로 관련 또는 무관으로 판정하지 않는다. 제목·설명 등을 정해진 규칙으로 옮기고 순서를 무작위화하는 역할만 한다.

## 생성되는 파일

판정자가 열어도 되는 파일:

- `judgment-workbook-ko.csv`: 1차 관련성 판정표
- `session-log-ko.csv`: 세션별 시작·종료 시각과 완료 범위 기록표
- `workbook-manifest.json`: 후보 수, 입력 checksum, 워크북 checksum과 무작위화 정보
- `PRIVATE-SHA256SUMS`: 생성 파일이 바뀌지 않았는지 확인하는 checksum

1차 판정이 모두 고정될 때까지 열면 안 되는 파일:

- `pool-key.restricted.csv`: 후보 코드와 시스템·원래 순위를 연결하는 숨김 key
- `pool-manifest.restricted.json`: 비공개 salt와 숨김 파일 checksum
- `retest-selection.restricted.csv`: 최소 7일 뒤 다시 판정할 10% 표본

파일명에 `restricted`가 있으면 판정 중에는 열지 않는다. 이 파일들은 GitHub, 원고 폴더 또는 공개 저장소에 올리지 않는다.

## 워크북 생성 명령

아래 경로는 실행 환경에 맞게 바꾼다. `--salt`를 생략하면 강한 무작위 salt가 자동 생성되어 제한 파일에만 저장된다.

```bash
uv run python scripts/build_complex_query_judgment_workbook.py \
  --run /private/path/confirmatory-v1/run \
  --queries protocols/complex-query-evaluation-v1/01-query-authoring-sheet.csv \
  --criteria protocols/complex-query-evaluation-v1/02-expected-criteria-sheet.csv \
  --review-ko protocols/complex-query-evaluation-v1/05-query-and-criteria-review-ko.md \
  --output /private/path/confirmatory-v1/judgment-workbook-v1
```

생성기는 다음을 먼저 검사하고 하나라도 맞지 않으면 파일 생성을 중단한다.

- 사전 고정 질의와 조건이 각각 60개인지
- 세 시스템 × 60개 질의의 응답 180개가 모두 있는지
- 실패 응답과 HTTP 오류가 없는지
- 실제 전송 질의가 사전 고정 영어 질의와 정확히 같은지
- 각 응답이 최대 10개이며 동일 응답 안 accession 중복이 없는지

## 판정 방법

가급적 외부 공유가 없는 로컬 Excel 또는 LibreOffice에서 작업용 사본을 연다. 온라인 스프레드시트로 업로드하면 비공개 평가 파일이 제3자 서비스에 복사될 수 있다.

빈 원본 `judgment-workbook-ko.csv`와 `session-log-ko.csv`는 수정하지 않고 보존한다. 각각 `judgment-workbook-ko.in-progress.csv`와 `session-log-ko.in-progress.csv`라는 사본을 만들어 그 사본만 작성한다. 최종 저장 형식도 UTF-8 CSV로 유지한다.

한 세션은 `세션묶음` 한 개씩 진행하며 100행을 넘지 않는다. 시작 전과 종료 후 작업용 `session-log-ko.in-progress.csv`에 한국 표준시와 완료한 `검토순서` 범위를 적는다.

관련성은 다음 기준으로 기록한다.

- `3`: 필수 조건과 핵심 연구 설계를 명확히 모두 만족
- `2`: 주요 조건 대부분을 만족해 실제 검토 후보로 유용
- `1`: 주제 일부만 관련되고 핵심 조건 또는 설계가 부족
- `0`: 무관하거나 제외 조건을 위반하거나, 공개 metadata로 관련성을 지지할 근거가 없음

`관련성_0_3` 외에도 질의에서 요구한 각 조건을 `1` 또는 `0`으로 기록한다. 요구하지 않은 항목은 생성 시 `NA`로 채워져 있으며 바꾸지 않는다.

- 조건이 공개 metadata에서 확인되면 `1`
- 조건에 맞지 않는 근거가 있으면 `0`
- 필요한 근거가 부족하면 해당 조건을 임의로 `1`로 두지 않고 `근거부족_yes_no`를 `yes`로 기록
- 제외 조건이 있는 질의는 위반 여부를 `yes`, `no` 또는 판단 불가 시 `NA`로 기록
- 판단 근거가 애매하거나 원본 GEO 페이지를 확인했다면 `판정근거_메모`에 짧게 남김

후보를 확인하기 위해 `원본_GEO_링크`는 열 수 있다. 다만 후보 accession을 OmicsPlorer, NCBI 검색 또는 OmicsDI에서 다시 검색해 어느 시스템이 반환했는지 추정하지 않는다.

## 세션 뒤 자동 확인

각 세션을 저장한 뒤 `partial` 검사로 현재 완료 행 수와 누락된 입력을 확인한다. 이 검사에는 `restricted` 파일이 전혀 필요하지 않다.

```bash
uv run python scripts/validate_complex_query_judgment_workbook.py \
  --workbook /private/path/judgment-workbook-ko.in-progress.csv \
  --template /private/path/judgment-workbook-ko.csv \
  --manifest /private/path/workbook-manifest.json \
  --session-log /private/path/session-log-ko.in-progress.csv \
  --mode partial
```

검사기는 다음만 확인한다.

- 무작위 행 순서, 질의와 후보 metadata가 바뀌지 않았는지
- 관련성 값이 `0`–`3`인지
- 요구된 조건에 `0` 또는 `1`이 입력됐는지
- 요구하지 않은 조건의 `NA`가 유지됐는지
- 제외 조건과 근거 부족 값의 형식이 맞는지
- 완료 행과 남은 행이 몇 개인지

이는 관련성 판단이 맞는지 평가하는 검사가 아니다. 사람의 판단은 그대로 두고 입력 누락과 형식 오류만 찾는다.

## 1차 판정 완료 뒤

1. 모든 행의 필수 입력이 채워졌는지 `--mode complete`로 검사한다. 이때 `session-log-ko.in-progress.csv`의 8개 세션 기록도 모두 작성되어야 한다.
2. 완성된 판정표의 SHA-256을 기록하고 읽기 전용 사본을 만든다.
3. 첫 판정은 주 분석 값으로 고정한다.
4. 시스템 정보는 아직 공개하지 않는다.
5. 첫 판정 완료일로부터 최소 7일 후 제한된 재판정 목록 74개를 별도 무작위 순서로 제시한다.
6. 재판정 완료 후에만 숨김 key를 사용해 시스템별 성능을 계산한다.

재판정 값은 첫 판정을 덮어쓰지 않는다. 두 값은 판정자 내 반복 일치도 계산에만 사용한다.
