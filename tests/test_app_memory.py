from __future__ import annotations

from pathlib import Path

from pcap2kml_player.app_memory import AppMemory


def test_app_memory_roundtrip(tmp_path: Path, monkeypatch) -> None:
    storage_file = tmp_path / "memory.json"
    monkeypatch.setattr(AppMemory, "storage_path", classmethod(lambda cls: storage_file))

    first = tmp_path / "capture-1.pcap"
    second = tmp_path / "capture-2.pcap"
    first.write_text("x", encoding="utf-8")
    second.write_text("y", encoding="utf-8")

    memory = AppMemory()
    memory.remember_files([str(first), str(second)])
    memory.remember_export_directory(str(tmp_path / "export"))
    memory.remember_session_summary(
        message_count=15,
        station_count=2,
        duration_seconds=42.5,
        msg_type_counts={"CAM": 10, "SPATEM": 5},
    )
    memory.save()

    loaded = AppMemory.load()

    assert loaded.last_opened_files == [str(first.resolve()), str(second.resolve())]
    assert loaded.last_directory == str(first.resolve().parent)
    assert loaded.last_export_directory == str((tmp_path / "export").resolve())
    assert loaded.last_session_message_count == 15
    assert loaded.last_session_types == {"CAM": 10, "SPATEM": 5}


def test_existing_last_session_files_filters_missing_entries(tmp_path: Path, monkeypatch) -> None:
    storage_file = tmp_path / "memory.json"
    monkeypatch.setattr(AppMemory, "storage_path", classmethod(lambda cls: storage_file))

    existing = tmp_path / "existing.pcap"
    existing.write_text("ok", encoding="utf-8")
    missing = tmp_path / "missing.pcap"

    memory = AppMemory(last_opened_files=[str(existing), str(missing)])

    assert memory.existing_last_session_files() == [str(existing)]


def test_load_missing_file_returns_defaults(tmp_path: Path, monkeypatch) -> None:
    storage_file = tmp_path / "nonexistent.json"
    monkeypatch.setattr(AppMemory, "storage_path", classmethod(lambda cls: storage_file))
    mem = AppMemory.load()
    assert mem.last_session_message_count == 0
    assert mem.last_session_station_count == 0


def test_load_corrupt_json_returns_defaults(tmp_path: Path, monkeypatch) -> None:
    storage_file = tmp_path / "bad.json"
    storage_file.write_text("not json", encoding="utf-8")
    monkeypatch.setattr(AppMemory, "storage_path", classmethod(lambda cls: storage_file))
    mem = AppMemory.load()
    assert mem.last_session_message_count == 0


def test_remember_files_empty_paths_noop() -> None:
    memory = AppMemory(recent_files=["old"])
    memory.remember_files([])
    assert memory.recent_files == ["old"]
    assert memory.last_opened_files == []


def test_remember_files_deduplication_and_limit(tmp_path: Path, monkeypatch) -> None:
    storage_file = tmp_path / "memory.json"
    monkeypatch.setattr(AppMemory, "storage_path", classmethod(lambda cls: storage_file))

    files = []
    for i in range(12):
        p = tmp_path / f"f{i}.pcap"
        p.write_text("x", encoding="utf-8")
        files.append(str(p))

    memory = AppMemory()
    memory.remember_files(files)
    assert len(memory.recent_files) == 10
    assert memory.recent_files[0] == files[0]  # preserves first occurrence order


def test_remember_export_directory(tmp_path: Path, monkeypatch) -> None:
    storage_file = tmp_path / "memory.json"
    monkeypatch.setattr(AppMemory, "storage_path", classmethod(lambda cls: storage_file))

    memory = AppMemory()
    memory.remember_export_directory(str(tmp_path))
    assert memory.last_export_directory == str(tmp_path.resolve())


def test_remember_session_summary_sorts_types() -> None:
    memory = AppMemory()
    memory.remember_session_summary(
        message_count=5,
        station_count=1,
        duration_seconds=10.0,
        msg_type_counts={"SPATEM": 3, "CAM": 2},
    )
    assert memory.last_session_types == {"CAM": 2, "SPATEM": 3}


def test_storage_path_falls_back_when_app_data_empty(monkeypatch) -> None:
    from PyQt6.QtCore import QStandardPaths

    monkeypatch.setattr(QStandardPaths, "writableLocation", lambda *_: "")
    path = AppMemory.storage_path()
    assert path.name == "memory.json"
    assert ".pcap2kml_player" in str(path)
