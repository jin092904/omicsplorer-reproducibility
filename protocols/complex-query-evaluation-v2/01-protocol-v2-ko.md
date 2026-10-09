# 복합 질의 블라인드 평가 v2 사전 고정 프로토콜 (2026-10-08 고정)

상태: **2026-10-08 Hojin Lee 승인으로 고정**(Discord, 키워드 검색식 규칙·60개 목록, 수집 순서, POE 규칙). 이 파일과 `02-keyword-concepts.csv`, `03-keyword-queries.csv`의 SHA-256은 `SHA256SUMS`에 있고, 첫 v2 수집 전에 커밋했다.
상위 계획: `../../02-strategy/evaluation-v2-plan-ko.md`. v1 기록: `../complex-query-evaluation-v1/`.

## 1. 목적

v1(2026-09-02 수집)은 긴 자연어 문장을 세 서비스에 그대로 넣었고, OmicsPlorer 결과는 색인 필드 형식 문제로 어휘 후보 없이 생성됐다. v2는 같은 60개 질의로 다음 세 질문에 답한다.

1. 각 서비스 문법에 맞춘 키워드 검색과 비교해도 OmicsPlorer가 관련 후보를 더 찾는가, 그리고 서로 다른 후보를 찾는가.
2. 같은 질의에서 의미 검색 도구(POE)와 비교하면 어떤가.
3. 어휘 후보를 되살린 하이브리드 경로(설계대로의 OmicsPlorer)는 v1의 dense+재순위화 결과와 어떻게 다른가.

v1 결과는 바꾸지 않고 "당시 설정의 결과"로 보존한다. v2는 별도 평가로 보고한다.

## 2. 고정하는 것

- 질의 60개와 필수·제외 조건: v1 그대로(`../complex-query-evaluation-v1/01-query-authoring-sheet.csv`, `02-expected-criteria-sheet.csv`, v1 `SHA256SUMS`).
- 판정 척도·관련 기준: v1 그대로(0–3점, 2점 이상 관련, 조건별 판정 포함).
- 각 시스템 상위 10개 GEO Series.

## 3. 비교 대상 (arm)

| arm | 시스템 | 입력 | 수집 장소 |
|---|---|---|---|
| A | OmicsPlorer 하이브리드(고친 색인) | 질의 문장 그대로. RRF 후 재순위화, GEO 원천 필터, 영어 입력, 자동 번역 끔, 10개 | A100 |
| B | NCBI GEO DataSets 키워드 | `03-keyword-queries.csv`의 `ncbi_geo_term`. `(<term>) AND gse[Entry Type]`, relevance 정렬, retmax 10 | 이 서버 |
| C | OmicsDI 키워드 | `03-keyword-queries.csv`의 `omicsdi_query`. `(<query>) AND repository:"geo"`, size 10 | 이 서버 |
| D | POE(Public Omics Explorer) 의미 검색 | 질의 문장 그대로, 필터 없음. 반환 논문 순서대로 연결 GSE를 모아 중복 없이 처음 10개 | 이 서버 |

### 3.1 키워드 검색식 작성 규칙 (B, C)

검색식은 v1의 질의 문장과 고정 조건만 보고 만들었고, 어떤 서비스에서도 결과를 보지 않았다(AI 초안, Hojin Lee 확인). 문법 점검은 오류 목록만 기록하고 결과 수·ID는 읽지 않았다(`check_keyword_syntax.py`, `03-keyword-syntax-check.csv`).

1. 필수 개념마다 AND 묶음 하나: 질병·상태, 세포 유형 또는 조직(질병이나 세포 유형으로 이미 정해지는 조직은 뺀다), 분석법, 노출·처리·교란 인자, 질의가 이름을 댄 비교군(예: adjacent normal, epilepsy controls, responders).
2. 묶음 안은 표준 동의어·약어를 OR로 묶는다. 분석법 묶음은 공통 표(single-cell, single-nucleus, RNA-seq, spatial)를 쓴다.
3. "gene-expression profiling", "transcriptomics"처럼 GEO 전체에 해당하는 일반 분석법은 넣지 않는다.
4. 설계 형용사(paired, longitudinal, matched, time-series, dose-dependent, stratified, cross-species, integrated, atlas)와 제외 조건은 넣지 않는다. 사용자가 결과를 보고 거르는 조건으로 보고, 판정에서 확인한다.
5. 필수 생물종은 GEO에서 `"<종>"[Organism]`, OmicsDI에서 `TAXONOMY:"<taxid>"`로 건다. 둘 이상이면 모두 건다(C12).
6. 두 서비스에 같은 개념 묶음을 쓰고 문법만 다르게 한다.

### 3.2 POE 가용성

2026-10-08 확인 시 POE 웹(`https://nplab.gr/poe`)은 503, API 호스트는 응답이 없었다. arm B·C 수집일과 그다음 날까지 POE가 응답하지 않으면 arm D는 "수집 불가"로 기록하고 빼며, 다른 도구로 대체하지 않는다(대체 도구 선택이 결과를 본 뒤의 선택이 되지 않도록). Hojin Lee 승인(2026-10-08). 그 뒤에 POE가 살아나면 수집하되, 수집일이 다르다는 점을 편차로 적는다.

### 3.3 arm A 조건

- 제품 commit은 v1 수집과 같은 운영 배포본(`345abf7…`)을 쓴다. 바꾸는 것은 `source_db`를 keyword로 정의한 새 OpenSearch 색인뿐이다. 기존 운영 색인은 지우거나 덮어쓰지 않는다.
- 수집 전 확인: 60개 질의의 어휘 단독 요청이 모두 0건이 아닌가(0건이 있으면 그 질의를 기록하되 수집은 진행), 새 색인과 Qdrant·PostgreSQL 건수.
- 각 응답의 trace(실제 모드, 어휘·dense 후보 수, 재순위화 점수 유무)를 보존한다. 어휘 후보가 쓰이지 않은 응답이 있으면 그 사실을 보고한다.

## 4. 수집

- 원래 계획은 네 arm을 같은 날(KST) 수집하는 것이었다. 2026-10-08 A100 접속이 끊겨 arm A는 복구 또는 Drive 백업 복원 뒤에 수집한다(Hojin Lee 결정). arm B·C는 2026-10-08에 수집한다. arm A의 OmicsPlorer 코퍼스는 2026-08-29 고정 스냅샷이므로 수집일 차이가 OmicsPlorer 쪽 후보에 주는 영향은 작고, 비교 서비스 쪽은 그사이 새로 공개된 데이터셋이 더해질 수 있다. 이 차이를 편차로 보고한다.
- 판정 묶음은 arm A의 수집 여부가 정해진 뒤 만든다. A100을 영구히 쓸 수 없고 백업 복원도 하지 않기로 하면, arm B·C(·D)와 반복 74쌍으로 판정한다.
- 원 응답(제3자 제목 포함)은 `private/evaluation-private/complex-query-evaluation-v2/raw/`에, 순위 projection(qid, system, rank, GSE)은 공개 가능한 형태로 둔다.
- arm A의 projection은 A100에서 논문 저장소로, 원 응답은 Drive `gcrypt:` sync 폴더로 옮긴다(sha256 대조).

## 5. 판정

- 판정 대상 = (A∪B∪C∪D의 상위 10개 쌍) − (v1의 739쌍) + v1에서 봉인해 둔 반복 판정 표본 74쌍(`retest-selection.restricted.csv`, v1에서 열지 않음).
- 새 쌍과 반복 쌍을 섞어 무작위 순서로 제시하고, 시스템명·원래 순위·점수·반환 시스템 수·반복 여부를 숨긴다. 순서 seed는 `omicsplorer-v2-judgment`.
- 판정자: Hojin Lee 한 명. 판정 기준과 화면은 v1과 같다. 판정이 끝나면 workbook SHA-256을 기록하고 잠근 뒤에 시스템을 공개한다.
- 절차 편차로 기록할 것: 반복 판정은 v1 주 분석의 시스템 공개 뒤(약 4주 뒤)에 한다.

## 6. 분석 (사전 지정)

v2 판정을 v1 판정과 합친 확장 qrels로 계산한다.

1. 주 비교: arm A–D와 v1 세 시스템의 평균 nDCG@10(0건 질의 포함), 질의 단위 10,000회 bootstrap 95% 신뢰구간. OmicsPlorer(A)와 각 비교 대상(B, C, D)의 paired 차이, sign-flip p값 Holm 보정(3개 비교).
2. 보조: Success@10, 엄격한 Success@10, 결과 반환 질의 수, 질의당 관련 후보 수, 반환 후보 중 관련 비율, 난이도별 결과, 시스템 사이 관련 후보 겹침.
3. 확장 풀 민감도: v1 세 시스템의 지표를 확장 qrels로 다시 계산해 v1 보고값과 나란히 제시한다.
4. 반복 일치도: 74쌍의 exact agreement와 quadratic weighted Cohen's kappa.
5. arm A와 v1 OmicsPlorer(dense+재순위화) 비교: 같은 질의에서 nDCG@10과 관련 후보 수의 paired 차이(기술 통계).

결과가 OmicsPlorer에 불리해도 이 분석을 그대로 보고한다.

## 7. 사람 판정 없이 하는 v2 실험 (참고, 별도 문서)

- 구성요소 비교: 내부 hard set(49개 질의, 영어·한국어)에서 RRF+재순위화 / 재순위화 입력에서 구조화 필드 제거 / 설계 표현 boost 끔 / dense-only / BM25-only. facet present@10, conjunctive@10.
- 현행 Gemma 4 구조화 정확도: S9의 40건 재추출(사람 판정) + 무작위 200건 자동 대조(생물종, 표본 수, 분석법).
- 세부 실행은 `04-a100-handoff-ko.md`.
