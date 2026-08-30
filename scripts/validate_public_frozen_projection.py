#!/usr/bin/env python3
"""Validate a public frozen projection and its optional external accession attachment."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from genofinder_eval.frozen_release_public import validate_public_projection_directory


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--projection-dir", type=Path, required=True)
    parser.add_argument("--accession-asset", type=Path)
    parser.add_argument(
        "--allow-missing-external-attachment",
        action="store_true",
        help="accept a checksum-bound release attachment that is intentionally absent from Git",
    )
    args = parser.parse_args()
    report = validate_public_projection_directory(
        args.projection_dir,
        accession_asset=args.accession_asset,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if report["status"] == "GO":
        return 0
    if (
        args.allow_missing_external_attachment
        and report["status"] == "GO_WITH_EXTERNAL_ATTACHMENT_REQUIRED"
    ):
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
