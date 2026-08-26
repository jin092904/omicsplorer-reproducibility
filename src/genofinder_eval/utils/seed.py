"""결정론적 seed 고정. 모든 random 사용처는 본 모듈의 `set_global_seed()` 를 호출.

`EVAL_SEED` 환경변수가 있으면 그 값 사용, 없으면 42.
"""
from __future__ import annotations

import os
import random

import numpy as np


def set_global_seed(seed: int | None = None) -> int:
    """Random / numpy / hash 시드 통합 고정. 반환값은 실제로 사용된 seed."""
    if seed is None:
        seed = int(os.environ.get("EVAL_SEED", "42"))
    random.seed(seed)
    np.random.seed(seed)
    os.environ["PYTHONHASHSEED"] = str(seed)
    return seed
