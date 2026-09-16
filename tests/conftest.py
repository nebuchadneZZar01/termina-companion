"""Keep test runs hermetic: never hit a real LLM unless a test opts in."""

from __future__ import annotations

import os

import pytest

_ENV = ("LLM_PROVIDER", "LLM_API_KEY", "LLM_MODEL", "LLM_BASE_URL")


@pytest.fixture(autouse=True)
def _force_rule_based_provider():
    saved = {k: os.environ.get(k) for k in _ENV}
    for key in _ENV:
        os.environ.pop(key, None)
    os.environ["LLM_PROVIDER"] = "rule-based"
    yield
    for key, value in saved.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
