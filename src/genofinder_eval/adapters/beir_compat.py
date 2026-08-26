"""BEIR-format corpus / queries / qrels 표준 IO.

corpus.jsonl  : {"_id": str, "title": str, "text": str, ...}
queries.jsonl : {"_id": str, "text": str}
qrels/*.tsv   : qid \\t Q0 \\t docid \\t relevance  (TREC qrel 표준)
"""
from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path


def load_corpus(path: Path) -> Iterator[dict[str, str]]:
    """Yield {`_id`, `title`, `text`} per line. 본 함수는 streaming — 794k docs 도 메모리 OK."""
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def load_queries(path: Path) -> dict[str, str]:
    """qid → query_text dict."""
    out: dict[str, str] = {}
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            out[d["_id"]] = d["text"]
    return out


def load_qrels(path: Path) -> dict[str, dict[str, int]]:
    """TREC qrel TSV → {qid: {docid: relevance}}."""
    out: dict[str, dict[str, int]] = {}
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) < 4:
                continue
            qid, _q0, docid, rel = parts[0], parts[1], parts[2], parts[3]
            out.setdefault(qid, {})[docid] = int(rel)
    return out


def write_run(path: Path, qid_runs: dict[str, list[tuple[str, float]]], tag: str) -> None:
    """TREC runfile 표준 형식 — qid Q0 docid rank score tag.

    atomic write: tempfile → rename 으로 corruption 방지.
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    with tmp.open("w", encoding="utf-8") as f:
        for qid, ranked in qid_runs.items():
            for rank, (docid, score) in enumerate(ranked, start=1):
                f.write(f"{qid}\tQ0\t{docid}\t{rank}\t{score:.6f}\t{tag}\n")
    tmp.replace(path)
