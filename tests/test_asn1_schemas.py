from __future__ import annotations

from pathlib import Path

from pcap2kml_player import asn1_schemas


def test_copy_schema_payloads_from_checkout_copies_only_relevant_files(tmp_path):
    checkout = tmp_path / "checkout"
    nested = checkout / "nested"
    nested.mkdir(parents=True)
    target = tmp_path / "target"
    target.mkdir()

    expected_files = {
        asn1_schemas.CDD_FILE,
        asn1_schemas.DSRC_FILE,
        asn1_schemas.ERI_FILE,
        *asn1_schemas.MSG_TYPE_MODULES.values(),
    }
    for file_name in expected_files:
        (nested / file_name).write_text(f"-- {file_name}\n", encoding="utf-8")
    (nested / "ignore-me.asn").write_text("-- ignore\n", encoding="utf-8")

    copied = asn1_schemas._copy_schema_payloads_from_checkout(checkout, target)

    assert copied == len(expected_files)
    assert {path.name for path in target.glob("*.asn")} == expected_files


def test_update_from_git_clones_to_temp_checkout_when_schema_dir_has_no_git(monkeypatch, tmp_path):
    schema_dir = tmp_path / "asn1"
    schema_dir.mkdir()
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    (schema_dir / "existing.asn").write_text("-- local\n", encoding="utf-8")
    (cache_dir / "old.pkl").write_bytes(b"cached")

    monkeypatch.setattr(asn1_schemas, "SCHEMAS_DIR", schema_dir)
    monkeypatch.setattr(asn1_schemas, "SCHEMA_CACHE_DIR", cache_dir)
    asn1_schemas._compiled_schemas["CAM"] = object()

    def fake_run(cmd, capture_output, text, timeout, check):
        assert cmd[:4] == ["git", "clone", "--depth", "1"]
        checkout_dir = Path(cmd[-1])
        nested = checkout_dir / "repo-content"
        nested.mkdir(parents=True, exist_ok=True)
        for file_name in {
            asn1_schemas.CDD_FILE,
            asn1_schemas.DSRC_FILE,
            asn1_schemas.ERI_FILE,
            *asn1_schemas.MSG_TYPE_MODULES.values(),
        }:
            (nested / file_name).write_text(f"-- refreshed {file_name}\n", encoding="utf-8")

    monkeypatch.setattr(asn1_schemas.subprocess, "run", fake_run)

    assert asn1_schemas.update_from_git() is True
    assert (schema_dir / asn1_schemas.CDD_FILE).exists()
    assert not (cache_dir / "old.pkl").exists()
    assert asn1_schemas._compiled_schemas == {}


def test_update_from_git_pulls_when_schema_dir_is_git_checkout(monkeypatch, tmp_path):
    schema_dir = tmp_path / "asn1"
    schema_dir.mkdir()
    (schema_dir / ".git").mkdir()
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    (cache_dir / "old.pkl").write_bytes(b"cached")

    monkeypatch.setattr(asn1_schemas, "SCHEMAS_DIR", schema_dir)
    monkeypatch.setattr(asn1_schemas, "SCHEMA_CACHE_DIR", cache_dir)
    asn1_schemas._compiled_schemas["CAM"] = object()

    calls: list[list[str]] = []

    def fake_run(cmd, capture_output, text, timeout, check):
        calls.append(cmd)

    monkeypatch.setattr(asn1_schemas.subprocess, "run", fake_run)

    assert asn1_schemas.update_from_git() is True
    assert calls == [["git", "-C", str(schema_dir), "pull"]]
    assert not (cache_dir / "old.pkl").exists()
    assert asn1_schemas._compiled_schemas == {}
