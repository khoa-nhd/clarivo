"""Where OpenVINO's compiled-model cache goes, and why it must never fail.

Voice analysis on the deployed backend answered:

    500 Local audio analysis failed:
        OSError: [Errno 30] Read-only file system: '/var/task/local_scoring/cache'

A serverless function's code directory is read-only. The cache was being
created there eagerly at the top of every audio request - for a cache that
request never uses, because on the web the transcript comes from Cloudflare
Whisper and no local model is ever compiled. An unused directory took the whole
feature down.
"""

import sys
import tempfile
import types
from pathlib import Path

_ov = types.ModuleType("openvino")
_ov.Core = object
sys.modules.setdefault("openvino", _ov)

import pytest

from app import local_delivery


def test_a_writable_location_is_used_as_is(tmp_path, monkeypatch):
    target = tmp_path / "cache"
    monkeypatch.setenv("LOCAL_CACHE_DIR", str(target))
    assert local_delivery._cache_dir() == target
    assert target.is_dir()


def _make_read_only(monkeypatch, denied: Path):
    """Make exactly `denied` behave like a read-only filesystem.

    Keyed on the path rather than on a literal "/var/task" so the test means the
    same thing on Windows, where that string resolves to a drive-relative path.
    """
    real_mkdir = Path.mkdir

    def mkdir(self, *args, **kwargs):
        if self == denied:
            raise OSError(30, "Read-only file system")
        return real_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", mkdir)


def test_a_read_only_location_falls_back_instead_of_raising(tmp_path, monkeypatch):
    """The serverless case. Previously this raised and returned a 500."""
    denied = tmp_path / "read-only-cache"
    monkeypatch.setenv("LOCAL_CACHE_DIR", str(denied))
    _make_read_only(monkeypatch, denied)

    resolved = local_delivery._cache_dir()
    assert resolved != denied
    assert resolved.is_dir()
    assert str(resolved).startswith(tempfile.gettempdir())


def test_the_fallback_is_writable(tmp_path, monkeypatch):
    """A fallback that is itself unusable would only move the failure."""
    denied = tmp_path / "read-only-cache"
    monkeypatch.setenv("LOCAL_CACHE_DIR", str(denied))
    _make_read_only(monkeypatch, denied)

    probe = local_delivery._cache_dir() / "write-probe.txt"
    probe.write_text("ok", encoding="utf-8")
    assert probe.read_text(encoding="utf-8") == "ok"
    probe.unlink()


def test_a_blank_environment_variable_does_not_mean_the_working_directory(monkeypatch):
    """`LOCAL_CACHE_DIR=` once resolved to '.', dropping cache blobs into the repo."""
    monkeypatch.setenv("LOCAL_CACHE_DIR", "")
    resolved = local_delivery._cache_dir()
    assert resolved.name == "cache"
    assert resolved.parent.name == "local_scoring"
