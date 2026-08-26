# OmicsPlorer 외부 서비스 비교 벤치마크 — 사전등록 프로토콜 v1

상태: **구현 기준선 / confirmatory run 전**
프로토콜 버전: `external-services-v1.0.0`
작성 기준일: 2026-07-20
비교 서비스: OmicsPlorer, NCBI GEO DataSets, OmicsDI

## 1. 연구 질문

1. 세 서비스가 모두 검색할 수 있는 GEO Series에서 OmicsPlorer의 ranking 품질은 NCBI와 OmicsDI보다 높은가?
2. 복합 연구 설계, 약어, 부정 조건처럼 일반 keyword 검색이 어려운 질의에서 차이가 커지는가?
3. OmicsPlorer의 통합 source 연결과 구조화 metadata는 dataset 발견·판단에 실질적인 이득을 주는가?
4. 품질 개선이 과도한 **실사용 end-to-end tail latency** 또는 실패율을 대가로 얻어진 것은 아닌가?
5. LLM 기반 구조화와 self-healing 보강이 metadata 품질·검색 가능성·업데이트 신선도를 실제로 개선하면서 기존 정보를 훼손하지 않는가?

성능 우월성은 하나의 평균값으로 주장하지 않는다. ranking, coverage, metadata, latency를 서로 다른 endpoint로 보고한다.

## 2. 공식 API 근거

### NCBI

- GEO는 programmatic metadata 검색에 Entrez E-utilities를 제공한다.
- GEO DataSets는 keyword, organism, dataset type, author와 field/Boolean query를 지원한다.
- `ESearch(db=gds)`로 ranked UID를 받고 `ESummary(db=gds)`로 GSE accession과 metadata를 얻는다.
- API key가 없으면 한 IP에서 초당 3회, key가 있으면 기본 초당 10회가 공식 제한이다.
- 모든 요청에 `tool`과 유효한 `email`을 포함한다.

공식 문서:

- https://www.ncbi.nlm.nih.gov/books/NBK25497/
- https://www.ncbi.nlm.nih.gov/books/NBK25499/
- https://www.ncbi.nlm.nih.gov/geo/info/qqtutorial.html
- https://www.ncbi.nlm.nih.gov/geo/info/download.html

### OmicsDI

- `/ws/dataset/search`는 JSON 검색 결과와 facet을 제공한다.
- `query`, `start`, `size`, `sort_field`를 사용한다.
- page size 기본 20, 최대 100이다.
- `repository`, `omics_type`, `TAXONOMY`, `tissue`, `disease` 등의 query filter를 지원한다.

공식 문서:

- https://www.omicsdi.org/help/api
- https://www.omicsdi.org/home

## 3. 비교 단위

### 3.1 Primary: GEO common-corpus ranking

세 시스템 모두에 존재하는 **GEO Series(GSE)**만 비교한다.

- OmicsPlorer: `source_db=["GEO"]`, `access_preference="any"`
- NCBI: `db=gds`, query에 `gse[Entry Type]` 추가
- OmicsDI: query에 `repository:"geo"` 추가
- top-k: 10을 primary, 50을 recall secondary로 사용
- accession은 대문자 `GSE[0-9]+`로 canonicalize한다.

이 트랙에서 ENA/SRA/GDC/MetaboLights/PRIDE 등 service별 독점 corpus는 제외한다. 동일한 query가 같은 종류의 record를 대상으로 하게 하기 위해서다.

### 3.2 Secondary: source coverage

서비스가 실제로 검색·표시하는 repository 종류와 accession 수를 별도로 측정한다. 이 트랙은 ranking 점수와 합치지 않는다.

### 3.3 Secondary: SRA/ENA crosswalk

SRA는 NCBI SRP/SRR와 ENA ERP/ERR, BioProject의 관계를 먼저 canonical table로 만든 뒤 비교한다. crosswalk가 없는 accession을 동일 document로 간주하지 않는다. v1의 primary claim에는 사용하지 않는다.

## 4. 두 종류의 ground truth

### 4.1 Human topical relevance

질의별 세 시스템 top-10의 union을 pooling한다.

- 동일 GSE는 한 후보로 합친다.
- system 이름, 원래 rank, score를 annotator에게 숨긴다.
- title, description, organism, assay, sample/design 정보와 원본 GEO link만 제공한다.
- 최소 2명의 domain annotator가 독립적으로 0–3 등급을 매긴다.
- 0: 무관
- 1: 주변적 관련
- 2: 관련; 주요 조건 대부분 충족
- 3: 매우 관련; 질의 조건과 연구 설계까지 충족
- 차이가 2 이상이거나 0 대 2/3인 항목은 adjudication한다.
- quadratic weighted Cohen’s kappa와 raw agreement를 보고한다.

불완전 pooling을 고려해 nDCG 외에 `bpref`를 보고한다. pooled top-10 밖의 unjudged document를 자동 0으로 취급해 Recall@50을 과장하지 않는다.

### 4.2 Known-item retrieval

GEO intersection에서 고정 seed로 dataset을 층화 표본추출한다.

- accession을 query에서 제거한 title query
- accession과 고유명사를 제거하고 organism/modality/disease/tissue/design으로 만든 facet query

target GSE의 reciprocal rank와 hit@1/5/10/50을 측정한다. 이는 객관적이고 자동화 가능하지만 “해당 dataset만이 유일하게 관련 있다”는 뜻은 아니므로 topical nDCG를 대체하지 않는다.

## 5. 질의 집합과 누수 방지

### 5.1 Pilot

기존 `balanced_queries`와 `hard_queries`에서 common-corpus 질의를 사용해 수집기와 annotation workflow를 검증한다. 이 질의들은 OmicsPlorer 개발 과정에서 사용되었으므로 pilot 결과를 confirmatory 성능 주장에 사용하지 않는다.

### 5.2 Confirmatory

- 최소 60개 질의
- 외부 비교 결과를 보지 않은 2명 이상의 연구자가 독립 작성
- simple 20, disease/tissue/modality 20, complex design/negation 20
- 질의 작성 후 Git commit과 SHA-256을 고정하고 서비스 호출 전에 protocol manifest를 저장
- 특정 서비스의 syntax에 맞게 query를 수동 최적화하지 않음
- API에는 동일한 영어 free-text를 전달하고 corpus 제한만 adapter가 추가
- 한국어는 별도 differentiation track이며 primary fair-comparison 평균에 합치지 않음

표본 크기 60은 작은 차이를 확정하기에 충분하다고 선험적으로 보장하지 않는다. run 후 observed effect에 맞춰 retrospective power를 주장하지 않고, query-level bootstrap CI 폭을 중심으로 해석한다.

## 6. Primary/secondary endpoint

### Primary endpoint

- human relevance `nDCG@10`
- query를 paired unit으로 사용한 system 간 평균 차이
- 10,000회 paired bootstrap, percentile 95% CI

### Secondary endpoints

- `P@10`
- `MRR@10`
- `Success@10` — relevance 2 이상이 하나 이상
- `bpref`
- judged-only `Recall@10`
- known-item `MRR`, Hit@1/5/10/50
- production browser의 검색 제출→첫 결과 렌더, 제출→페이지 안정화 latency p50/p95/p99/max
- AI Pick 클릭→추천 카드 완료 latency p50/p95/p99/max
- API 내부 search, Next server/BFF, ontology label, browser rendering의 단계별 시간
- timeout/HTTP/schema failure rate
- result accession 중복률
- title/description/organism/assay/date/sample count completeness

## 7. 통계 계획

1. 모든 품질 비교는 같은 query의 paired difference를 사용한다.
2. primary pairwise comparisons는 OmicsPlorer–NCBI, OmicsPlorer–OmicsDI 두 개다.
3. 두 primary p-value를 Holm 방식으로 보정한다.
4. 효과 크기와 95% CI를 먼저 보고하고 p-value만으로 결론 내리지 않는다.
5. query category별 결과는 사전 지정된 subgroup이며 exploratory로 표시한다.
6. latency는 heavy-tail이므로 평균보다 median, p95와 ECDF를 보고한다.
7. timeout은 latency 표본에서 제거하지 않고 별도 failure로 집계하며, timeout ceiling을 적용한 sensitivity analysis를 추가한다.

## 8. 실제 서비스 latency 측정

### 8.1 Primary 시간 지표

시간 성능의 primary 관측점은 API의 `latency_ms`가 아니라 **실제 production URL을 연 headless browser에서 사용자가 검색을 제출한 시각부터 결과가 화면에 렌더된 시각까지**다.

다음 두 event를 별도로 기록한다.

- `search_first_result_ms`: submit/navigation 시작 → 결과 수 또는 첫 ResultCard가 visible
- `search_settled_ms`: submit 시작 → search route의 network/DOM이 안정되고 pending overlay가 사라짐

AI Pick은 검색을 막지 않는 사용자 opt-in 기능이므로 분리한다.

- `ai_pick_cached_ms`: Generate 클릭 → ready/empty/error
- `ai_pick_forced_refresh_ms`: Refresh(nocache) 클릭 → ready/empty/error

### 8.2 tail 중심 보고

- 대표 문구: “가장 빠르면 X초”가 아니라 “관측 요청의 95%가 X초, 99%가 Y초 안에 완료”
- p50, p90, p95, p99, max, timeout/error 비율을 모두 표시
- 표본이 100 미만이면 p99를 안정적인 SLA 추정치로 부르지 않고 observed quantile로 표시
- timeout은 누락하지 않고 timeout ceiling 값으로 우측 censoring된 sensitivity plot과 실패율에 포함
- min 값은 diagnostic appendix 외에는 홍보 지표로 사용하지 않음

### 8.3 환경과 표본

- 실제 공개 ingress(현재 Cloudflare tunnel 또는 확정 production domain)에서 실행
- production Next.js, FastAPI, DB, Qdrant, OpenSearch, Ollama와 실제 데이터 사용
- 최소 100회, 권장 300회; simple/medium/complex query를 균형 배치
- 24시간 이상에 걸쳐 시간대를 분산해 warm cache만 측정하는 문제를 줄임
- browser engine/version, 실행 host와 network 위치를 manifest에 기록
- client와 server clock을 혼합하지 않고 browser monotonic wall time을 end-to-end 기준으로 사용
- API `latency_ms`는 원인 분해용 secondary 값으로만 사용

### 8.4 cold/warm 정의

운영 cache나 model을 임의로 비우지 않은 측정은 `live-cache-state-unknown`으로 표기한다. cache clear/model unload는 실제 사용자 상태를 훼손할 수 있으므로 별도 maintenance window와 승인 아래서만 수행한다.

- query cache cold: 해당 protocol query/hash가 run 시작 전 cache에 없음을 확인
- model cold: Ollama에 대상 model이 load되어 있지 않음을 확인
- browser cold: 새 context, HTTP cache/storage 비움
- warm: 동일 query의 직전 성공 호출 후 반복

이 네 상태를 섞어 하나의 “평균 검색 시간”으로 만들지 않는다.

### 8.5 왜 API와 브라우저 시간을 모두 저장하는가

사용자가 10초 이상 기다리는데 API가 약 1초라고 기록되는 경우, 나머지 시간은 Next server rendering, ontology label fetch, ingress/network, connection queue, browser hydration/navigation 또는 재시도에서 생길 수 있다. 다음 waterfall을 같은 run ID로 연결한다.

```text
browser submit
  -> ingress/Next route TTFB
  -> Next server POST /api/v1/search
  -> FastAPI retrieval latency_ms
  -> ontology label fetch
  -> RSC/HTML transfer
  -> browser DOM commit
  -> first result visible / pending overlay hidden
```

## 9. LLM 자동 수집·구조화·보강 benchmark

이 트랙은 제품의 핵심 평가이며 외부 ranking 평균에 부가적으로 합산하지 않는다.

### 9.1 평가 대상

1. 신규 source metadata 수집과 idempotent UPSERT
2. Gemma 기반 modality/disease/tissue/cell/cohort 구조화
3. OLS4 exact label/synonym 정규화
4. Sol4 weak-row detection, shadow inference, validation gate, safe merge
5. PostgreSQL→Qdrant/OpenSearch 동기화와 실제 검색 가능 시각

### 9.2 고정 데이터셋

- source별 층화 표본 최소 300건: GEO 100, SRA 100, GDC 및 metadata-hard case 100
- 신규/짧은 abstract/다중 조직/복합 design/약어/부정/prompt-injection-like metadata를 포함
- annotator는 원본 source metadata만 보고 gold label 작성
- modality, organism, disease, tissue, cell type, cohort design, subject grouping을 field별 평가
- benchmark 시작 전 source payload와 SHA-256을 snapshot하여 외부 metadata 변경을 차단

### 9.3 비교 조건

- `raw`: 원본 metadata, 구조화 없음
- `rules`: deterministic parser와 mapping만 사용
- `llm_structurer`: LLM + schema validation
- `llm_ols`: LLM + OLS4 normalization
- `sol4_shadow`: 현재값에 Sol4 제안 적용 전 diff
- `sol4_commit_simulation`: 복제 DB에서 gate와 safe merge까지 적용

동일 입력 snapshot에 paired 실행한다. model, quantization, prompt/version, temperature, seed 가능 여부, GPU, Ollama version을 고정한다.

### 9.4 품질 endpoint

- field별 micro/macro precision, recall, F1
- exact-set match와 Jaccard
- ontology CURIE validity와 label evidence rate
- unsupported/hallucinated CURIE rate
- JSON/schema pass rate, first-pass/retry pass rate
- cohort subject regex compile/match rate
- **information gain**: 빈/약한 field가 gold와 일치하게 추가된 비율
- **regression rate**: 기존 gold-correct 값을 잃거나 틀린 값으로 바꾼 비율
- safe-merge 핵심 gate: ontology list shrink 0건
- human review 필요율과 평균 review 시간

### 9.5 자동화·신선도 endpoint

- source publication/last-update → harvest 완료
- harvest 완료 → 구조화 완료
- 구조화 완료 → DB commit
- DB commit → Qdrant/OpenSearch searchable
- 각 단계 p50/p95/p99/max와 timeout/failure/backlog
- scheduled run 성공률, retry 횟수, watermark drift
- 동일 batch 재실행 전후 row/index 변화로 idempotency 확인
- worker/model 장애 후 자동 재개와 checkpoint 복구 시간

현재 Sol4 Celery beat 항목은 주석 처리되어 있으므로 기준 시점의 `scheduled unattended completion rate`는 측정 가능한 운영 자동화로 인정하지 않는다. 먼저 shadow schedule, alert, durable checkpoint, rollback을 활성화·검증한 뒤 “자동 보강 운영”이라고 표현한다.

### 9.6 비용·처리량

- dataset/sec 및 samples/sec
- GPU-seconds/dataset, peak VRAM, CPU/RAM
- 입력/출력 token 또는 Ollama eval count가 제공되면 함께 기록
- first-pass와 retry 분리
- 1만 건/전체 corpus 보강 예상 wall time은 p95 처리량 기반 range로 제시
- 최고 속도가 아니라 장애/retry를 포함한 production batch의 p95 completion time을 대표값으로 사용

### 9.7 downstream 유용성

동일 query와 동일 candidate pool에서 구조화 전/후를 비교한다.

- facet coverage와 conjunctive satisfaction
- nDCG@10/Recall@10 변화
- 신규로 발견된 relevant dataset
- 잘못된 facet 때문에 사라진 relevant dataset
- payload-only sync와 re-embedding 조건을 분리

## 10. 실행 통제

- 실행 시각: UTC와 Asia/Seoul 모두 기록
- 각 서비스 endpoint와 response hash 기록
- query 순서는 seed로 섞되 모든 system에 같은 순서 block을 사용
- relevance 수집은 query당 1회; browser latency는 100회 이상을 시간대별로 분산
- latency마다 browser/cache/model 상태를 명시하고 확인 불가능하면 unknown으로 기록
- NCBI rate limit 준수; key는 manifest에 기록하지 않고 `api_key_used: true/false`만 기록
- 요청 간 backoff와 `Retry-After` 준수
- 외부 API의 raw JSON을 그대로 저장하고 SHA-256 생성
- OmicsPlorer code commit, dirty patch hash, model digest, DB/index counts를 manifest에 저장
- client에서 service score를 공통 score로 재해석하지 않고 원래 rank만 사용

## 11. 식별자 정규화

```text
GEO Series: GSE\d+
SRA Study:  SRP\d+
ENA Study:  ERP\d+ / DRP\d+
BioProject: PRJNA\d+ / PRJEB\d+ / PRJDB\d+
GDC:        UUID 또는 project ID, 별도 namespace 유지
```

GSM sample, GPL platform, GDS curated dataset을 GSE Series와 합치지 않는다. NCBI `gds` 결과에서 `entrytype=GSE`만 유지한다.

## 12. Blind pooling 산출물

```text
run/
├── run_manifest.json
├── raw/{system}/{qid}.json
├── normalized/{system}.jsonl
├── pool_key.csv                 # 접근 제한; system/rank provenance
├── annotation_round1.csv        # blind
├── annotation_round2.csv        # blind
├── adjudicated_qrels.tsv
├── metrics_per_query.csv
├── metrics_summary.csv
├── pairwise_bootstrap.csv
├── browser_timings.jsonl
├── enrichment/
│   ├── input_snapshot_manifest.json
│   ├── field_judgments.tsv
│   ├── outputs_by_condition.jsonl
│   ├── quality_metrics.csv
│   └── pipeline_stage_timings.jsonl
└── figures/
```

`pool_key.csv`는 annotator에게 제공하지 않는다. annotation 파일의 후보 순서는 query 내부 deterministic random seed로 섞는다.

## 13. 피겨 계획

1. `quality_primary`: system별 nDCG@10 query bootstrap CI
2. `quality_by_category`: category × system heatmap
3. `paired_difference`: OmicsPlorer−comparator query-level difference
4. `tail_latency`: 검색/AI Pick의 p50/p95/p99/max와 timeout; p95/p99 강조
5. `latency_waterfall`: browser end-to-end와 API/Next/ontology/render 분해
6. `latency_quality`: nDCG@10 대 p95 end-to-end latency
7. `known_item`: Hit@k curve
8. `metadata_completeness`: field별 완전성 dot plot
9. `coverage_overlap`: GSE accession overlap; 3-set이면 exact Venn보다 UpSet 스타일 사용
10. `enrichment_quality`: raw/rules/LLM/OLS/Sol4 field별 F1와 regression rate
11. `automation_freshness`: publication→searchable 단계별 p95/p99 waterfall

모든 결과 피겨는 `metrics_*.csv`와 `run_manifest.json`만 읽는다. Python 파일 안에 결과 숫자를 하드코딩하지 않는다. qrels가 없는 상태에서는 결과 막대그래프를 생성하지 않는다.

## 14. 성공/해석 규칙

OmicsPlorer의 차별성은 다음 조건을 동시에 만족할 때 주장한다.

- primary nDCG@10 차이의 95% CI가 0을 넘거나, 최소한 clinically/practically meaningful한 양의 효과를 보임
- 단순 query뿐 아니라 complex subgroup에서도 일관된 방향
- known-item/coverage 결과가 primary 결과와 모순되지 않음
- failure rate가 comparator보다 현저히 높지 않음
- latency trade-off가 명시됨
- production browser p95/p99와 timeout이 명시되고 API 내부 시간만으로 대체되지 않음
- LLM 보강이 information gain을 보이면서 regression/list-shrink 안전 gate를 통과함
- scheduler가 꺼진 기능을 unattended automation으로 주장하지 않음
- annotator agreement가 해석 가능한 수준; 낮으면 adjudication/기준 개선 후 재실행

유의하지 않은 결과도 그대로 보고한다. 특정 query 예시만 골라 일반 우월성을 주장하지 않는다.

## 15. 변경 금지와 protocol deviation

confirmatory run이 시작되면 query, endpoint, top-k, metric, exclusion rule을 수정하지 않는다. 불가피한 변경은 `protocol_deviations.jsonl`에 시각, 이유, 영향, 승인자를 기록하고 기존 raw data를 보존한다.

## 16. 현재 한계

- pilot query는 기존 개발 질의라 누수가 있다.
- 외부 서비스 index는 계속 변경되므로 동일 날짜 snapshot이 아니다.
- 외부 service의 내부 ranking과 corpus version은 완전히 고정할 수 없다.
- human qrels가 완성되기 전에는 실제 ranking 우월성 피겨를 만들 수 없다.
- OmicsDI의 광범위한 omics corpus는 coverage 장점이지만 GEO common-corpus ranking에서는 의도적으로 제한된다.
- browser 실행 위치의 network가 실제 사용자의 모든 지역을 대표하지 않는다. 위치별 측정은 별도 stratification이 필요하다.
- 현재 Sol4 schedule 비활성 상태에서는 코드의 자동화 가능성과 운영 자동화 성과를 분리해야 한다.

이 한계를 raw response, timestamp, hash, protocol version으로 최대한 통제한다.
