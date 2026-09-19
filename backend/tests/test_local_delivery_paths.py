"""Regression tests for directory resolution from environment variables.

The bug: `.env.example` ships `LOCAL_CACHE_DIR=` and `LOCAL_MODELS_DIR=` with no
value. `os.getenv(name, default)` returns the default only when the variable is
*absent*, so a present-but-empty value became `""`, and `Path("").resolve()` is
the process working directory.

Consequences, both observed: the OpenVINO compiled-model cache was written to
whatever directory the server was started from, putting ~23 MB of `.blob` files
into the repository root, and if that directory was not writable the cache was
silently lost (`create_core` swallows the failure) so every request paid a full
model recompile - up to ~19 s for the GPU model set.
"""

import sys
import types
from pathlib import Path

_ov = types.ModuleType("openvino")
_ov.Core = object
sys.modules.setdefault("openvino", _ov)

import pytest

from app.local_delivery import _env_path, models_dir

EXPECTED_DEFAULT_ROOT = Path(__file__).resolve().parent.parent / "local_scoring"


@pytest.mark.parametrize("value", ["", "   ", "\t"])
def test_blank_value_falls_back_to_the_default(monkeypatch, tmp_path, value):
    monkeypatch.setenv("CLARIVO_TEST_DIR", value)
    monkeypatch.chdir(tmp_path)
    resolved = _env_path("CLARIVO_TEST_DIR", EXPECTED_DEFAULT_ROOT / "cache")
    assert resolved == (EXPECTED_DEFAULT_ROOT / "cache").resolve()
    # The specific failure: it must not become the working directory.
    assert resolved != tmp_path.resolve()


def test_absent_value_falls_back_to_the_default(monkeypatch, tmp_path):
    monkeypatch.delenv("CLARIVO_TEST_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    assert _env_path("CLARIVO_TEST_DIR", EXPECTED_DEFAULT_ROOT / "cache") == (
        EXPECTED_DEFAULT_ROOT / "cache"
    ).resolve()


def test_a_real_value_is_honoured(monkeypatch, tmp_path):
    target = tmp_path / "custom-cache"
    monkeypatch.setenv("CLARIVO_TEST_DIR", str(target))
    assert _env_path("CLARIVO_TEST_DIR", EXPECTED_DEFAULT_ROOT / "cache") == target.resolve()


def test_surrounding_whitespace_is_stripped(monkeypatch, tmp_path):
    target = tmp_path / "padded"
    monkeypatch.setenv("CLARIVO_TEST_DIR", f"  {target}  ")
    assert _env_path("CLARIVO_TEST_DIR", EXPECTED_DEFAULT_ROOT / "cache") == target.resolve()


def test_models_dir_is_independent_of_the_working_directory(monkeypatch, tmp_path):
    """models_dir already handled blanks, but must stay that way."""
    monkeypatch.setenv("LOCAL_MODELS_DIR", "")
    monkeypatch.chdir(tmp_path)
    assert models_dir() == (EXPECTED_DEFAULT_ROOT / "models").resolve()

    monkeypatch.delenv("LOCAL_MODELS_DIR", raising=False)
    assert models_dir() == (EXPECTED_DEFAULT_ROOT / "models").resolve()
