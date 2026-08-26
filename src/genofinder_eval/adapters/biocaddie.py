"""bioCADDIE 2016 Dataset Retrieval Challenge corpus / queries / qrels loader.

Reference:
    Cohen T, Roberts K, et al. "DataMed — an open source discovery index for
    finding biomedical datasets." Database (Oxford), 2017. doi:10.1093/database/bax061
    bax068 overview paper: best submission infNDCG ≈ 0.423-0.513.

Data scale (논문 보고치):
    corpus: 794,992 datasets (DataMed internal IDs, 2016-03-24 snapshot,
            GEO + ArrayExpress + BioProject + dbGaP 등 20 repository)
    queries: 15 (test set)
    qrels: 20,000+ manual relevance judgments

Notes:
    - bioCADDIE doc_id 는 DataMed internal ID 라 우리 GSE accession 과 *직접 join 불가*.
    - 본 평가는 *우리 retrieval stack 을 bioCADDIE corpus 위에 올려 실행* 하는 OOD
      generalization 평가. 별도 임시 인덱스 (`biocaddie_2016_eval`) 사용.
    - fetch 실패 시 abort, 사용자 보고. 합성 데이터 fabrication 금지.

본 모듈은 두 가지 역할:
    1. raw bioCADDIE 배포본 → BEIR-format jsonl 변환 (`to_beir_format`).
    2. 변환 결과의 count 검증 (`verify_counts`).

실제 raw schema 는 fetch 성공 후에야 확정. 따라서 `to_beir_format` 은 *generic dispatch*
패턴 (raw 가 JSON / XML / TSV 어느 쪽이든 entry point 에서 분기).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import structlog

from genofinder_eval.utils.logging import get_logger

logger: structlog.stdlib.BoundLogger = get_logger(__name__)


# PHI-likely 패턴 (간단 휴리스틱) — 발견 시 abort.
_PHI_PATTERNS = (
    re.compile(r"\bMRN[-:]?\s*\d{6,}\b", re.IGNORECASE),
    re.compile(r"\bSSN[-:]?\s*\d{3}-?\d{2}-?\d{4}\b", re.IGNORECASE),
    # 이름 검출은 false-positive 너무 많아 제외 (논문 abstract 의 author name 등).
)


def _check_phi(text: str, source: str = "") -> None:
    """PHI-likely 패턴 발견 시 raise. 합성 / 변형 금지 — 즉시 abort."""
    for pat in _PHI_PATTERNS:
        if pat.search(text):
            raise RuntimeError(
                f"PHI-likely pattern detected in bioCADDIE raw ({source}): "
                f"{pat.pattern!r}. fetch 무결성 / 라이선스 재검토 필요. abort."
            )


def to_beir_format(raw_dir: Path, out_dir: Path) -> dict[str, int]:
    """bioCADDIE raw 배포본 → BEIR-format 변환.

    raw_dir 의 가능한 구조 (실 fetch 후 확정):
        - corpus.json / corpus.jsonl / corpus/*.json (수십만 doc)
        - queries.txt / queries.json / topics.xml
        - qrels.txt / qrels.tsv

    본 함수는 *generic dispatch* — 디렉토리 내 파일 패턴을 감지하여 변환.
    실 raw 구조 확정 후 분기 보강 필요.

    Returns:
        {"corpus_n": N, "queries_n": M, "qrels_n": K}.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {"corpus_n": 0, "queries_n": 0, "qrels_n": 0}

    # 1) corpus
    corpus_out = out_dir / "corpus.jsonl"
    corpus_n = _convert_corpus(raw_dir, corpus_out)
    counts["corpus_n"] = corpus_n
    logger.info("biocaddie_corpus_converted", count=corpus_n)

    # 2) queries
    queries_out = out_dir / "queries.jsonl"
    queries_n = _convert_queries(raw_dir, queries_out)
    counts["queries_n"] = queries_n
    logger.info("biocaddie_queries_converted", count=queries_n)

    # 3) qrels
    qrels_dir = out_dir / "qrels"
    qrels_dir.mkdir(exist_ok=True)
    qrels_out = qrels_dir / "test.tsv"
    qrels_n = _convert_qrels(raw_dir, qrels_out)
    counts["qrels_n"] = qrels_n
    logger.info("biocaddie_qrels_converted", count=qrels_n)

    return counts


def _convert_corpus(raw_dir: Path, out: Path) -> int:
    """raw corpus → BEIR jsonl. JSON / JSONL 자동 감지."""
    candidates = list(raw_dir.glob("corpus*.json*"))
    if not candidates:
        raise FileNotFoundError(
            f"bioCADDIE raw corpus 파일 미발견. raw_dir={raw_dir}. "
            "scripts/01-fetch-biocaddie.sh fetch 결과 재확인."
        )
    src = candidates[0]
    n = 0
    with src.open("r", encoding="utf-8") as fin, out.open("w", encoding="utf-8") as fout:
        # JSONL 우선 시도 (한 줄 한 doc) — 첫 줄 parse 가능한지 검증.
        first = fin.readline()
        try:
            json.loads(first)
        except json.JSONDecodeError:
            raise RuntimeError(
                f"raw corpus {src} parse 실패. JSON / JSONL 아님. raw schema 확인 필요."
            ) from None
        # JSONL 패턴이면 첫 줄 외에도 줄이 더 있음
        fin.seek(0)
        for line in fin:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            doc = _normalize_corpus_doc(obj)
            _check_phi(doc["title"] + " " + doc["text"], source=f"corpus:{doc['_id']}")
            fout.write(json.dumps(doc, ensure_ascii=False) + "\n")
            n += 1
    return n


def _normalize_corpus_doc(obj: dict[str, Any]) -> dict[str, str]:
    """raw doc → BEIR {_id, title, text}. 필드명 후보 다수 시도."""
    # 알려진 후보 — 실 raw schema 확정 후 정확한 키만 남김.
    doc_id = (
        obj.get("_id") or obj.get("id") or obj.get("doc_id")
        or obj.get("datamed_id") or obj.get("docno")
    )
    title = obj.get("title") or obj.get("name") or obj.get("dataset_title") or ""
    text = (
        obj.get("text") or obj.get("description") or obj.get("abstract")
        or obj.get("summary") or ""
    )
    if doc_id is None:
        raise KeyError(f"raw doc 의 식별자 필드 미발견. keys={list(obj.keys())[:10]}")
    return {"_id": str(doc_id), "title": str(title), "text": str(text)}


def _convert_queries(raw_dir: Path, out: Path) -> int:
    """raw queries (topics) → BEIR jsonl."""
    candidates = list(raw_dir.glob("queries*.json*")) + list(raw_dir.glob("topics*.json*"))
    if not candidates:
        raise FileNotFoundError(
            f"bioCADDIE raw queries 파일 미발견 in {raw_dir}. "
            "topics.xml 같은 형식이면 별도 변환 필요."
        )
    src = candidates[0]
    n = 0
    with src.open("r", encoding="utf-8") as fin, out.open("w", encoding="utf-8") as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line) if line.startswith("{") else None
            if obj is None:
                # 전체가 단일 JSON object array
                fin.seek(0)
                root = json.load(fin)
                items = root.get("queries", root) if isinstance(root, dict) else root
                for q in items:
                    qid = str(q.get("_id") or q.get("id") or q.get("topic_id"))
                    text = q.get("text") or q.get("title") or q.get("query") or ""
                    fout.write(json.dumps({"_id": qid, "text": text}, ensure_ascii=False) + "\n")
                    n += 1
                break
            qid = str(obj.get("_id") or obj.get("id") or obj.get("topic_id"))
            text = obj.get("text") or obj.get("title") or obj.get("query") or ""
            fout.write(json.dumps({"_id": qid, "text": text}, ensure_ascii=False) + "\n")
            n += 1
    return n


def _convert_qrels(raw_dir: Path, out: Path) -> int:
    """raw qrels → TREC TSV format (qid Q0 docid relevance)."""
    candidates = list(raw_dir.glob("qrels*.txt")) + list(raw_dir.glob("qrels*.tsv"))
    if not candidates:
        raise FileNotFoundError(f"bioCADDIE raw qrels 파일 미발견 in {raw_dir}.")
    src = candidates[0]
    n = 0
    with src.open("r", encoding="utf-8") as fin, out.open("w", encoding="utf-8") as fout:
        for line in fin:
            parts = line.strip().split()
            if len(parts) < 4:
                continue
            qid, q0, docid, rel = parts[0], parts[1], parts[2], parts[3]
            fout.write(f"{qid}\t{q0}\t{docid}\t{rel}\n")
            n += 1
    return n


def verify_counts(corpus_n: int, queries_n: int, qrels_n: int) -> None:
    """논문 보고치와 일치 검증.

    bax068 Table 1: corpus 794,992 / queries 15 / qrels 20,000+ (정확한 qrel 수는
    submission 별로 변동하나 일반적으로 20,000-30,000 범위).
    """
    if corpus_n != 794992:
        raise ValueError(
            f"bioCADDIE corpus count mismatch: got {corpus_n}, expected 794992. "
            "다운로드 무결성 확인 필요."
        )
    if queries_n != 15:
        raise ValueError(f"bioCADDIE queries count mismatch: got {queries_n}, expected 15.")
    if qrels_n < 20000:
        raise ValueError(
            f"bioCADDIE qrels count suspicious: got {qrels_n}, expected 20,000+. "
            "qrel 파일이 잘렸을 가능성."
        )
