"""structlog 구성. SENSITIVE keys (bearer_token, query_text) 의 출력 직전 redact.

OmicsPlorer ADR 0002 의 redaction 원칙과 일치 — query 본문은 L3 (Restricted) 로 다뤄야
하므로 평가 로그에서도 그대로 노출하지 않는다. 디버그 시 마스킹 해제는 별도 flag.
"""
from __future__ import annotations

import logging
import os
from collections.abc import MutableMapping
from typing import Any, cast

import structlog

SENSITIVE_KEYS = frozenset({"bearer_token", "authorization", "query_text", "query", "abstract"})


def _redact_sensitive(
    _: Any, __: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    for k in list(event_dict.keys()):
        if k.lower() in SENSITIVE_KEYS and isinstance(event_dict[k], str):
            v = event_dict[k]
            event_dict[k] = (v[:8] + "…[REDACTED]") if v else v
    return event_dict


def configure_logging() -> None:
    level = os.environ.get("EVAL_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(level=getattr(logging, level, logging.INFO), format="%(message)s")
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            _redact_sensitive,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level, logging.INFO)),
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(name))
