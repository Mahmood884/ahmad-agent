"""Append-only, prompt-free provider call cost accounting."""
from __future__ import annotations

import json
import math
import os
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from ahmad.providers.base import ProviderResult


def _nonnegative_number(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) and number >= 0 else None


def _usage(metadata: dict) -> tuple[int | None, int | None]:
    usage = metadata.get("usage")
    usage = usage if isinstance(usage, dict) else metadata
    input_tokens = usage.get("input_tokens", usage.get("prompt_tokens"))
    output_tokens = usage.get("output_tokens", usage.get("completion_tokens"))
    input_tokens = (
        input_tokens if isinstance(input_tokens, int) and not isinstance(input_tokens, bool)
        and input_tokens >= 0 else None
    )
    output_tokens = (
        output_tokens if isinstance(output_tokens, int) and not isinstance(output_tokens, bool)
        and output_tokens >= 0 else None
    )
    return input_tokens, output_tokens


def _rate_cost(
    rates: Mapping[str, float],
    input_tokens: int,
    output_tokens: int,
) -> float | None:
    if "input_per_million" in rates and "output_per_million" in rates:
        scale = 1_000_000
        input_rate = _nonnegative_number(rates["input_per_million"])
        output_rate = _nonnegative_number(rates["output_per_million"])
    elif "input_per_1k" in rates and "output_per_1k" in rates:
        scale = 1_000
        input_rate = _nonnegative_number(rates["input_per_1k"])
        output_rate = _nonnegative_number(rates["output_per_1k"])
    else:
        return None
    if input_rate is None or output_rate is None:
        return None
    return (input_tokens * input_rate + output_tokens * output_rate) / scale


class ProviderCostLedger:
    """Records token/cost facts without storing prompts or generated text."""

    def __init__(
        self,
        path: Path,
        rates: Mapping[str, Mapping[str, float]] | None = None,
    ) -> None:
        self.path = Path(path)
        self.rates = dict(rates or {})

    def record(
        self,
        provider: str,
        request_id: str,
        prompt: str,
        result: ProviderResult | None,
    ) -> None:
        metadata = result.metadata if result is not None else {}
        input_tokens, output_tokens = _usage(metadata)
        cost = _nonnegative_number(metadata.get("cost_usd"))
        if cost is None:
            cost = _nonnegative_number(metadata.get("total_cost_usd"))
        if cost is None:
            cost = _nonnegative_number(metadata.get("cost"))

        usage_basis = "provider_reported" if (
            input_tokens is not None or output_tokens is not None
        ) else "unknown"
        cost_basis = "provider_reported" if cost is not None else "unknown"

        rate = self.rates.get(provider)
        if cost is None and rate is not None:
            if input_tokens is None:
                input_tokens = math.ceil(len(prompt) / 4)
                usage_basis = "estimated_characters"
            if output_tokens is None and result is not None:
                output_tokens = math.ceil(len(result.text) / 4)
                usage_basis = "estimated_characters"
            if output_tokens is not None:
                cost = _rate_cost(rate, input_tokens, output_tokens)
                if cost is not None:
                    cost_basis = "estimated_configured_rates"

        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "request_id": request_id,
            "provider": provider,
            "success": bool(result and result.success),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "usage_basis": usage_basis,
            "cost": cost,
            "currency": "USD",
            "cost_basis": cost_basis,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(self.path, flags, 0o600)
        except OSError as exc:
            raise RuntimeError(f"cannot safely open provider cost ledger {self.path}") from exc
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise RuntimeError("provider cost ledger must be a regular file")
            if hasattr(os, "getuid") and metadata.st_uid != os.getuid():
                raise RuntimeError("provider cost ledger must be owned by the current user")
            os.fchmod(descriptor, 0o600)
            record = (json.dumps(entry, separators=(",", ":"), allow_nan=False) + "\n").encode()
            written = os.write(descriptor, record)
            if written != len(record):
                raise OSError("incomplete write to provider cost ledger")
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
