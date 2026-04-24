from __future__ import annotations

import logging

from pcap2kml_player import main as main_module


class _FakeApplication:
    attributes: list[tuple[object, bool]] = []

    def __init__(self, _argv):
        self.application_name = ""
        self.application_version = ""
        self.organization_name = ""
        self.style = ""
        self.stylesheet = ""

    @classmethod
    def setAttribute(cls, attr, enabled=True):
        cls.attributes.append((attr, enabled))

    def setApplicationName(self, value: str) -> None:
        self.application_name = value

    def setApplicationVersion(self, value: str) -> None:
        self.application_version = value

    def setOrganizationName(self, value: str) -> None:
        self.organization_name = value

    def setStyle(self, value: str) -> None:
        self.style = value

    def setStyleSheet(self, value: str) -> None:
        self.stylesheet = value

    def exec(self) -> int:
        return 0


class _FakeMessageBox:
    warnings: list[tuple[str, str]] = []

    @classmethod
    def warning(cls, _parent, title: str, message: str) -> None:
        cls.warnings.append((title, message))


class _FakeWindow:
    instances = 0
    shown = 0

    def __init__(self):
        type(self).instances += 1

    def show(self) -> None:
        type(self).shown += 1


def test_main_logs_qt_runtime_and_uses_software_opengl_when_preferred(monkeypatch, caplog):
    _FakeApplication.attributes = []
    _FakeMessageBox.warnings = []
    _FakeWindow.instances = 0
    _FakeWindow.shown = 0

    monkeypatch.setattr(main_module, "QApplication", _FakeApplication)
    monkeypatch.setattr(main_module, "QMessageBox", _FakeMessageBox)
    monkeypatch.setattr(main_module, "MainWindow", _FakeWindow)
    monkeypatch.setattr(main_module, "install_global_exception_handler", lambda _app: None)
    monkeypatch.setattr(main_module, "check_runtime_dependencies", lambda: [])
    monkeypatch.setattr(main_module, "prefer_software_rendering", lambda: True)
    monkeypatch.setenv("QT_OPENGL", "software")
    monkeypatch.setenv("QT_OPENGL_DLL", r"C:\PyQt6\Qt6\bin\opengl32sw.dll")
    monkeypatch.setenv("QSG_RHI_PREFER_SOFTWARE_RENDERER", "1")
    monkeypatch.setenv("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")

    with caplog.at_level(logging.INFO, logger="pcap2kml"):
        exit_code = main_module.main()

    assert exit_code == 0
    assert any("Qt runtime: software=True" in message for message in caplog.messages)
    assert any("QT_OPENGL_DLL=C:\\PyQt6\\Qt6\\bin\\opengl32sw.dll" in message for message in caplog.messages)
    assert any(
        attr == main_module.Qt.ApplicationAttribute.AA_UseSoftwareOpenGL and enabled is True
        for attr, enabled in _FakeApplication.attributes
    )
    assert _FakeWindow.instances == 1
    assert _FakeWindow.shown == 1


def test_main_skips_software_attribute_when_gpu_is_opted_in(monkeypatch, caplog):
    _FakeApplication.attributes = []
    _FakeMessageBox.warnings = []
    _FakeWindow.instances = 0
    _FakeWindow.shown = 0

    monkeypatch.setattr(main_module, "QApplication", _FakeApplication)
    monkeypatch.setattr(main_module, "QMessageBox", _FakeMessageBox)
    monkeypatch.setattr(main_module, "MainWindow", _FakeWindow)
    monkeypatch.setattr(main_module, "install_global_exception_handler", lambda _app: None)
    monkeypatch.setattr(main_module, "check_runtime_dependencies", lambda: [])
    monkeypatch.setattr(main_module, "prefer_software_rendering", lambda: False)
    monkeypatch.delenv("QT_OPENGL", raising=False)
    monkeypatch.delenv("QSG_RHI_PREFER_SOFTWARE_RENDERER", raising=False)
    monkeypatch.setenv("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-direct-composition")

    with caplog.at_level(logging.INFO, logger="pcap2kml"):
        exit_code = main_module.main()

    assert exit_code == 0
    assert any("Qt runtime: software=False" in message for message in caplog.messages)
    assert not any(
        attr == main_module.Qt.ApplicationAttribute.AA_UseSoftwareOpenGL
        for attr, _enabled in _FakeApplication.attributes
    )
