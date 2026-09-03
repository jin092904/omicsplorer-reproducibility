# 사람이 읽기 쉬운 블라인드 판정 자료

결정일: 2026-09-03

## 변경 이유

원래 `judgment-workbook-ko.csv`는 질의, 사전 조건, 후보 metadata와 판정 열을 한 행에 보존하므로 38열이다. 이는 무결성 검사와 최종 분석 입력에는 적합하지만 한 화면에서 읽고 판정하기 어렵다.

첫 판정이 시작되기 전에 같은 블라인드 내용을 세션별 세 종류의 파일로 나눴다. 평가 대상, 무작위 순서, 판정 기준과 시스템 blinding은 바꾸지 않는다.

## 세션별 파일

- `session-XX-review-ko.md`: 한국어 질의·조건과 후보의 수집 당시 공개 metadata 원문
- `session-XX-links-ko.md`: 후보코드와 원본 GEO record 링크
- `session-XX-scores-ko.csv`: 식별 열, 관련성, 조건 충족, 제외 조건, 근거 부족과 메모만 포함한 짧은 입력표

후보 제목과 설명은 번역 과정이 관련성 판단에 영향을 주지 않도록 임의 번역하지 않는다. 문서 표제, 질의와 사전 고정 조건은 한글로 제공한다.

검토 Markdown에는 원본 GEO 링크를 넣지 않고 링크 문서에만 둔다. 점수표에는 후보 제목, 설명과 링크를 넣지 않는다. 판정자는 판정ID 또는 후보코드로 세 파일을 대응시킨다.

## 변하지 않는 조건

- 60개 질의와 739개 질의-후보 쌍
- 기존 seed와 비공개 salt로 정한 순서
- 세션별 행 수와 후보 배정
- 시스템명, 원래 순위, 검색 점수와 반환 시스템 수의 비공개 상태
- 관련성 0–3 및 조건별 1·0·NA 기준
- 단일 판정자와 최소 7일 뒤 74개 재판정 계획

## 생성과 병합

분리 자료는 빈 원본 판정표의 SHA-256과 구조 검사가 통과해야만 생성된다. 기존 출력 폴더가 비어 있지 않으면 덮어쓰지 않는다.

```bash
uv run python scripts/build_complex_query_review_pack.py \
  --template /private/path/judgment-workbook-ko.csv \
  --manifest /private/path/workbook-manifest.json \
  --output /private/path/review-pack-v1
```

작성한 8개 점수표는 식별 열이 원본과 같은지 확인한 뒤 739행 워크북에 합친다. 병합 결과는 기존 `partial` 또는 `complete` validator를 다시 통과해야 하며, 실패한 결과 파일은 보존하지 않는다.

```bash
uv run python scripts/merge_complex_query_score_sheets.py \
  --template /private/path/judgment-workbook-ko.csv \
  --manifest /private/path/workbook-manifest.json \
  --scores /private/path/review-pack-v1 \
  --output /private/path/judgment-workbook-ko.in-progress.csv \
  --session-log /private/path/session-log-ko.in-progress.csv \
  --mode partial
```

실제 검토 Markdown, 링크, 점수와 병합 워크북은 비공개 평가 자료다. GitHub에는 생성·검사 코드와 이 절차만 공개한다.
