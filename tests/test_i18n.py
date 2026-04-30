from __future__ import annotations

from pcap2kml_player.i18n import tr


def test_tr_returns_german_translation_for_known_key():
    assert tr("Play") == "Abspielen"
    assert tr("File loaded successfully") == "Datei erfolgreich geladen"


def test_tr_falls_back_to_message_id_for_unknown_key():
    assert tr("This key does not exist") == "This key does not exist"


def test_tr_with_format_args():
    assert tr("{} messages processed", 42) == "{} messages processed".format(42)


def test_tr_without_format_args_returns_verbatim():
    assert tr("No messages to display") == "Keine Nachrichten zum Anzeigen"


def test_tr_handles_multiple_format_args():
    result = tr("{} of {} files loaded", 3, 10)
    assert "3" in result
    assert "10" in result
