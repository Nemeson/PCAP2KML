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
