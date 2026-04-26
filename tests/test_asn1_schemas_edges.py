"""Edge-case tests for asn1_schemas.py to push branch coverage above 80%."""

from __future__ import annotations

import pickle
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pcap2kml_player import asn1_schemas as schemas_mod


@pytest.fixture(autouse=True)
def _reset_module_state(monkeypatch):
    """Reset the module-level caches and counters before each test."""
    schemas_mod._compiled_schemas.clear()
    schemas_mod._decoding_errors.clear()
    monkeypatch.setattr(schemas_mod, "asn1tools", None)


class TestVerifySchemaIntegrity:
    def test_returns_empty_dict_when_dir_missing(self, monkeypatch):
        monkeypatch.setattr(schemas_mod, "SCHEMAS_DIR", Path("/nonexistent_schemas"))
        assert schemas_mod.verify_schema_integrity() == {}


class TestGetSchemaVersions:
    def test_returns_empty_dict_when_dir_missing(self, monkeypatch):
        monkeypatch.setattr(schemas_mod, "SCHEMAS_DIR", Path("/nonexistent_schemas"))
        assert schemas_mod.get_schema_versions() == {}

    def test_skips_unreadable_file(self, tmp_path: Path, monkeypatch):
        schema_dir = tmp_path / "schemas"
        schema_dir.mkdir()
        bad = schema_dir / "bad.asn"
        bad.write_text("V1.0.0", encoding="utf-8")

        def _raise(*args, **kwargs):
            raise OSError("boom")

        monkeypatch.setattr("pathlib.Path.open", _raise)
        monkeypatch.setattr(schemas_mod, "SCHEMAS_DIR", schema_dir)
        assert schemas_mod.get_schema_versions() == {}


class TestErrorStats:
    def test_get_and_reset(self):
        schemas_mod._decoding_errors["x"] = 3
        assert schemas_mod.get_decoding_error_stats() == {"x": 3}
        schemas_mod.reset_decoding_error_stats()
        assert schemas_mod.get_decoding_error_stats() == {}


class TestCacheHelpers:
    def test_load_compiled_missing_file_returns_none(self, tmp_path: Path):
        assert schemas_mod._load_compiled_from_disk(tmp_path / "missing.pkl") is None

    def test_load_compiled_bad_pickle_returns_none(self, tmp_path: Path):
        p = tmp_path / "bad.pkl"
        p.write_bytes(b"not a pickle")
        assert schemas_mod._load_compiled_from_disk(p) is None

    def test_save_compiled_uses_parent_mkdir(self, tmp_path: Path):
        cache_dir = tmp_path / "cache"
        p = cache_dir / "test.pkl"
        schemas_mod._save_compiled_to_disk(p, {"compiled": True})
        assert p.exists()

    def test_save_compiled_failure_is_silent(self, tmp_path: Path, monkeypatch):
        p = tmp_path / "test.pkl"
        monkeypatch.setattr(Path, "write_bytes", lambda *_: (_ for _ in ()).throw(OSError("fail")))
        schemas_mod._save_compiled_to_disk(p, {"compiled": True})


class TestSchemaFilesAvailable:
    def test_returns_false_when_empty(self, tmp_path: Path, monkeypatch):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        monkeypatch.setattr(schemas_mod, "SCHEMAS_DIR", empty_dir)
        assert schemas_mod._schema_files_available() is False

    def test_returns_true_when_asn_present(self, tmp_path: Path, monkeypatch):
        schema_dir = tmp_path / "schemas"
        schema_dir.mkdir()
        (schema_dir / "x.asn").write_text("x", encoding="utf-8")
        monkeypatch.setattr(schemas_mod, "SCHEMAS_DIR", schema_dir)
        assert schemas_mod._schema_files_available() is True


class TestGetSchemaFilesMissing:
    def test_warns_when_cdd_missing(self, tmp_path: Path, monkeypatch, caplog):
        schema_dir = tmp_path / "schemas"
        schema_dir.mkdir()
        monkeypatch.setattr(schemas_mod, "SCHEMAS_DIR", schema_dir)
        files = schemas_mod._get_schema_files("CAM")
        assert "CDD file not found" in caplog.text
        assert files == []

    def test_warns_when_dsrc_missing_for_is_type(self, tmp_path: Path, monkeypatch, caplog):
        schema_dir = tmp_path / "schemas"
        schema_dir.mkdir()
        (schema_dir / "ETSI-ITS-CDD.asn").write_text("x", encoding="utf-8")
        monkeypatch.setattr(schemas_mod, "SCHEMAS_DIR", schema_dir)
        files = schemas_mod._get_schema_files("MAPEM")
        assert "DSRC file not found" in caplog.text
        assert "ERI stub file not found" in caplog.text


class TestCopySchemaPayloadsNotFound:
    def test_logs_debug_for_missing_file(self, tmp_path: Path, caplog):
        source_dir = tmp_path / "checkout"
        source_dir.mkdir()
        target_dir = tmp_path / "target"
        target_dir.mkdir()
        with caplog.at_level("DEBUG"):
            schemas_mod._copy_schema_payloads_from_checkout(source_dir, target_dir)
        assert "not found in checkout" in caplog.text


class TestInvalidateCaches:
    def test_clears_compiled_schemas(self, tmp_path: Path, monkeypatch):
        schemas_mod._compiled_schemas["CAM"] = "dummy"
        monkeypatch.setattr(schemas_mod, "SCHEMA_CACHE_DIR", tmp_path / "cache_empty")
        schemas_mod._invalidate_schema_caches()
        assert schemas_mod._compiled_schemas == {}

    def test_removes_cache_files(self, tmp_path: Path, monkeypatch):
        cache_dir = tmp_path / "cache_full"
        cache_dir.mkdir()
        p = cache_dir / "x.pkl"
        p.write_bytes(b"y")
        monkeypatch.setattr(schemas_mod, "SCHEMA_CACHE_DIR", cache_dir)
        schemas_mod._invalidate_schema_caches()
        assert not p.exists()

    def test_remove_failure_is_silent(self, tmp_path: Path, monkeypatch):
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        p = cache_dir / "x.pkl"
        p.write_bytes(b"y")

        def _raise(*args, **kwargs):
            raise OSError("denied")

        monkeypatch.setattr("pathlib.Path.unlink", _raise)
        monkeypatch.setattr(schemas_mod, "SCHEMA_CACHE_DIR", cache_dir)
        schemas_mod._invalidate_schema_caches()


class TestGetCompiledSchemaEdgeCases:
    def test_returns_none_when_asn1tools_missing(self):
        assert schemas_mod.get_compiled_schema("CAM") is None

    def test_returns_none_for_unknown_msg_type(self):
        schemas_mod.asn1tools = MagicMock()
        assert schemas_mod.get_compiled_schema("UNKNOWN") is None


class TestDecodeItsMessageEdgeCases:
    def test_returns_none_when_asn1tools_missing(self):
        assert schemas_mod.decode_its_message("CAM", b"\x00") is None


class TestInitSchemas:
    def test_returns_false_for_all_when_asn1tools_missing(self):
        result = schemas_mod.init_schemas()
        assert not any(result.values())
