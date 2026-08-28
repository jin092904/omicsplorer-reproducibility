#!/usr/bin/env python3
"""Validate the frozen Sol4 feasibility-pilot contract without live services."""

from __future__ import annotations

import argparse
from pathlib import Path

from genofinder_eval.metadata_contract import validate_contract

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = ROOT / "protocols/metadata-enrichment-pilot-v1/frozen-contract"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract-dir", type=Path, default=DEFAULT_CONTRACT)
    args = parser.parse_args()
    manifest = validate_contract(args.contract_dir.resolve())
    print(f"CONTRACT OK: {manifest['product_git_commit']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
