"""Tests for the background parsing worker."""

from pcap2kml_player.data_model import SessionData
from pcap2kml_player.parsing_worker import ParsingWorker


def test_parsing_worker_emits_finished_with_error_for_missing_file():
    worker = ParsingWorker(["C:\\does-not-exist\\missing.pcap"])
    captured = []

    worker.finished.connect(lambda session, paths, errors: captured.append((session, paths, errors)))
    worker.run()

    assert len(captured) == 1
    session, paths, errors = captured[0]
    assert isinstance(session, SessionData)
    assert session.messages == []
    assert paths == ["C:\\does-not-exist\\missing.pcap"]
    assert len(errors) == 1
    assert "missing.pcap" in errors[0]


def test_double_cancel_is_safe():
    worker = ParsingWorker(["C:\\does-not-exist\\missing.pcap"])
    worker.cancel()
    worker.cancel()

    captured: list[str] = []
    worker.cancelled.connect(lambda: captured.append("cancelled"))
    worker.run()

    assert len(captured) == 1


def test_cancel_during_run_triggers_cancelled_signal():
    import threading
    from pathlib import Path

    testfile = Path(__file__).resolve().parent.parent / "testfiles" / "txa 3.pcap"
    worker = ParsingWorker([str(testfile)])
    captured: list[str] = []
    worker.cancelled.connect(lambda: captured.append("cancelled"))

    def cancel_soon():
        worker.cancel()

    cancel_thread = threading.Thread(target=cancel_soon, daemon=True)
    cancel_thread.start()
    worker.run()
    cancel_thread.join(timeout=10)

    assert len(captured) == 1


def test_parsing_worker_empty_paths_emits_finished():
    worker = ParsingWorker([])
    captured = []

    worker.finished.connect(lambda session, paths, errors: captured.append((session, paths, errors)))
    worker.run()

    assert len(captured) == 1
    session, paths, errors = captured[0]
    assert session.messages == []
    assert paths == []
    assert errors == []
