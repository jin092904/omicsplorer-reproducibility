# 복합 질의 01 시트 검토 기록

검토일: 2026-09-02
상태: 질의 작성자 확인 및 기대 조건 사람 최종 검토 완료

## 검토 범위

사용자가 제공한 60개 영어·한국어 질의를 CSV 형식, 양 언어의 의미, 난이도·category slot, 생물학적 현실성, 현재 논문의 GEO 중심 비교 적합성과 최소 API 반환 여부를 기준으로 점검했다.

## 형식 검사 결과

- 원본은 60개 의도를 포함했지만 C14와 C15가 줄바꿈 없이 붙어 있었다.
- 각 행은 `query_ko` 뒤의 작성자·역할·날짜·결과 미열람 확인 열이 빠져 있었다.
- C10의 쉼표와 따옴표, C14–C15 병합을 수정해 표준 CSV 60행으로 복원했다.
- 한국어 오탈자와 용어를 고쳤다. 예: `급성 급성림프구백혈병`, `베이타`, `흑질종`, `종양 침윤 침구`, `차적 유전자 발현`.
- 사용자는 2026-09-02에 60개 질의가 AI 생성 초안이 아니며 본인이 검토했고, 최초 작성 언어가 한국어였음을 확인했다. 이에 `original_language=ko`, `query_author=Hojin Lee`, `author_role=author`, `date_written=2026-09-02`, `results_not_seen_yes=yes`와 사람 작성·검토 기록을 60행에 동일하게 입력했다.

## 최소 가용성 검사

로컬 OmicsPlorer API에서 source를 GEO로 제한하고 RRF·reranking 제외·page size 1로 반환 여부만 확인했다. 결과 제목, accession과 순위 내용은 기록하지 않았다.

첫 실행에서 59개는 후보를 반환했다. S02는 첫 실행에서 0건이었으나 같은 문장과 간결하게 정리한 문장을 dense-only와 RRF로 즉시 재검사했을 때 모두 후보를 반환했다. 따라서 60개 중 API 반환 0건을 이유로 삭제한 질의는 없다.

이 검사는 관련성 평가가 아니다. 후보 한 건이 반환됐다는 사실은 그 후보가 질문을 만족한다는 뜻이 아니다. 또한 최종 질의 고정 전에 수행한 availability screen이므로 논문에는 confirmatory 성능 결과로 사용하지 않는다.

## 내용상 주요 수정

| ID | 원본 문제 | 수정 방향 |
|---|---|---|
| S11 | metagenomics와 metabolomics를 한 simple 질의에 동시에 요구 | 장내 미생물군집 metagenomics 한 가지로 단순화 |
| S20 | dataset modality 없이 분석 결과인 세포 구조·상호작용만 요청 | triple-negative breast cancer spatial transcriptomics로 명확화 |
| M02 | glioblastoma spatial transcriptomics와 intratumoral microbiome의 직접 결합 근거가 불명확 | 공개 자료가 확인되는 tumor core–infiltrative margin의 spatial transcriptomics와 snRNA-seq로 변경 |
| M05 | 감염 폐 조직의 `metatranscriptomics`가 숙주·병원체 중 무엇을 뜻하는지 모호 | host–pathogen dual RNA-seq로 명확화 |
| M06 | `HIV reservoir cells`를 single-cell spatial transcriptomics가 직접 확정하는 것처럼 표현 | reservoir-associated immune niche를 공간적으로 분석하는 질의로 조정 |
| M11 | spatial microbiome과 host expression의 직접 동시 측정을 과도하게 요구 | 점막 생검의 paired microbiome–host transcriptome으로 조정 |
| M12 | ALS 진행 CSF mass-spectrometry proteomics는 주로 ProteomeXchange 계열에 있고 공통 GEO 비교에 불리 | GEO GSE242736의 공개 설계와 일치하는 수술 후 섬망 환자-대조군 aptamer-based CSF proteomics 질의로 변경 |
| M14 | spatial transcriptomics와 MIBI를 같은 측정처럼 표현 | 공개 PDAC 연구 설계에 맞춰 snRNA-seq와 MIBI 조합으로 변경 |
| M16 | `aging brain models`의 생물종과 표본이 모호 | 인간 해마의 노화에 따른 snRNA-seq로 명확화 |
| M17 | 다핵성 syncytiotrophoblast를 scRNA-seq로 직접 포획하는 표현이 부정확 | 태반 trophoblast population의 snRNA-seq로 변경 |
| C01 | 교모세포종 환자의 matched healthy brain control은 표본 확보와 표현이 부자연스러움 | 같은 환자의 tumor core와 infiltrative margin 비교로 변경 |
| C03 | differential expression이라는 분석 행위를 dataset 검색어로 사용 | anti-PD-1 treatment 대 vehicle control RNA-seq dataset 질의로 변경 |
| C06 | 척수는 같은 마우스에서 반복 채취할 수 없어 `longitudinal` 표현과 충돌 | 반복 채혈 가능한 환자 말초혈액의 면역치료 전·중 longitudinal scRNA-seq로 변경 |
| C17 | `excluding carriers`보다 실제 metadata에 나타날 가능성이 높은 상태 표현이 적절 | EGFR-wild-type 및 ALK-negative로 변경 |
| C20 | 세포 이웃·상호작용은 후속 분석 결과이며 측정법이 빠져 있음 | spatial transcriptomics를 명시 |

## 공개 자료로 확인한 현실성 예시

- 교모세포종 중심부와 침윤 경계부 spatial multi-omics: GEO GSE286413
- 사람 척수 spatial transcriptomics: GEO GSE222322
- ALS 척수 spatial transcriptomics: GEO GSE120374 및 관련 공개 자료
- HIV 저장소 연관 림프절 spatial transcriptomics 연구가 공개되어 있음
- 췌장관선암종 snRNA-seq·MIBI·GeoMx 연구: GEO GSE202051 및 GSE199102
- 태반 syncytiotrophoblast에서 snRNA-seq의 중요성을 보여주는 GEO GSE288650
- 점막 host transcriptome–microbiome 연계 연구: GEO GSE65270
- aptamer 기반 CSF proteomics의 GEO 사례: GSE242736

이 accession은 질의별 정답을 확정한 것이 아니다. 질의가 현실의 연구·데이터 유형과 연결되는지 확인한 예시일 뿐이다. Known-relevant answer로 사용하려면 `02-expected-criteria-sheet.csv`에 근거와 함께 별도로 사전 고정해야 한다.

## 다음 확인이 필요한 항목

1. 결과 목록을 보기 전 작성된 `02-expected-criteria-sheet.csv`의 AI 보조 초안을 이호진이 직접 검토·확정한다.
2. 두 시트를 함께 최종 검증한 뒤 commit과 SHA-256을 고정한다.

## 2차 주제·설계 일치 검수 반영

사용자는 2026-09-02에 다음 A안을 선택했다.

- S10: ALS의 `spinal-cord lesions`를 더 정확하고 포괄적인 `spinal-cord tissue`로 변경
- C01: `case_control` slot에 맞도록 교모세포종 조직과 뇌전증 수술 유래 비종양성 대뇌피질 대조 조직 비교로 변경
- C13: dual-disease 질의의 표본과 측정법을 명확히 하도록 간 조직 및 single-nucleus RNA-seq를 명시

이 변경은 실제 검색 결과의 관련성이나 순위를 본 뒤 선택한 것이 아니라, 질의 내용과 사전 지정 topic·design slot의 일치성을 높이기 위한 사전 수정이다.

변경 직후 세 질의를 GEO 제한 RRF·reranking 제외·page size 1로 다시 실행했으며 S10, C01과 C13 모두 HTTP 200과 후보 1건 이상을 반환했다. 후보의 제목·accession·순위는 이 확인 기록에 사용하지 않았다. 이는 관련성 판정이 아니라 변경된 문장이 검색 경로에서 0건으로 끝나지 않는지 확인한 최소 가용성 검사다.

## 02 시트 필수 조건 초안 작성

2026-09-02에 `01-query-authoring-sheet.csv`의 사람 작성 질의 문장만 바탕으로 `02-expected-criteria-sheet.csv` 60행의 필수 조건과 현실성 근거를 AI 보조 방식으로 작성했다. 실제 검색 결과의 제목, accession과 순위는 보지 않았으며, 알려진 정답 GSE와 근거 URL은 임의로 만들지 않고 모두 비워 두었다.

질문에 명시되지 않은 생물종, 연구 설계와 비교군을 과도하게 추론하지 않도록 다시 점검해 삭제했다. 사람 검토 전에는 `criteria_author=OpenAI Codex (AI-assisted draft)`와 `Hojin Lee review required before freeze`로 표시했으며, 이호진의 행별 검토 전에는 최종 고정 검사가 실패하도록 검증기에 보호 규칙을 추가했다.

## 사람 최종 검토

이호진은 2026-09-02에 `05-query-and-criteria-review-ko.md`에서 한국어 질의와 필수·제외 조건 60개를 함께 확인하고 모두 맞게 입력되었다고 승인했다. 이에 02 시트의 작성자 기록을 `Hojin Lee (reviewed AI-assisted draft)`로 변경하고 60개 검토란을 완료 처리했다. 검색 결과의 제목, accession 또는 순위는 이 검토에 사용하지 않았다.
