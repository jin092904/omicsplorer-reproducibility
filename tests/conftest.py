"""Pytest fixtures — respx 기반 OmicsPlorer API mock + seed 고정."""
from __future__ import annotations

import pytest

from genofinder_eval.utils.seed import set_global_seed


@pytest.fixture(autouse=True)
def _fixed_seed() -> None:
    set_global_seed(42)
