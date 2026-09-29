import os
import time
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QWizard
from dovi_studio.dependencies import Tool, SPECS
from dovi_studio.dialogs import ConversionWizard, OptionsDialog, SetupWizard
from dovi_studio.models import Options
from dovi_studio.ui import MainWindow, IDENTITY_ROLE


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    from dovi_studio import settings
    monkeypatch.setattr(settings, 'settings_dir', lambda: tmp_path / 'settings')
    result = MainWindow(check_tools=False)
    result.show()
    yield result
    if result.worker:
        result.worker.cancel.set()
        pump(app, lambda: result.worker is None)
    for dialog in result.findChildren(QDialog):
        dialog.reject()
    result.close()
    app.processEvents()


def pump(app, condition, timeout=5):
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.005)
    assert condition()


def test_native_controls_and_sorted_selection_stays_attached_to_file(app, window, tmp_path):
    first, second = tmp_path / 'Zebra.mkv', tmp_path / 'Alpha.mkv'
    first.write_bytes(b'123')
    second.write_bytes(b'123456789')
    window.add_discovered([(first, None), (second, None)])
    app.processEvents()
    assert not window.styleSheet()
    assert window.table.item(0, 0).text() == 'Alpha.mkv'
    window.table.selectRow(0)
    assert [job.path for job in window.jobs if job.checked] == [second]
    window.table.sortItems(1, Qt.SortOrder.AscendingOrder)
    app.processEvents()
    assert window.table.item(0, 0).text() == 'Zebra.mkv'
    assert [job.path for job in window.jobs if job.checked] == [second]
    window.remove_selected()
    assert [job.path for job in window.jobs] == [first]
    assert second.exists()  # Remove means remove from list, never delete media.


def test_worker_results_are_delivered_after_thread_stops(app, window, tmp_path):
    window.add_discovered([(tmp_path / 'Movie.mkv', None)])
    results = []
    window.start_worker(lambda worker: 42, lambda value: results.append((value, window.worker)))
    pump(app, lambda: window.worker is None)
    assert results == [(42, None)]
    assert window.convert_action.isEnabled()


def test_cancel_options_does_not_mutate_defaults(app):
    original = Options(output_dir='/original', include_fel=False)
    dialog = OptionsDialog(original)
    dialog.output.path.edit.setText('/edited')
    dialog.conversion.fel.setChecked(True)
    dialog.reject()
    assert original.output_dir == '/original'
    assert original.include_fel is False


def test_conversion_wizard_requires_destination_and_retains_back_navigation(app, tmp_path):
    wizard = ConversionWizard(Options(), [tmp_path / 'Movie.mkv'])
    wizard.show()
    app.processEvents()
    wizard.output_page.fields.custom.setChecked(True)
    assert not wizard.output_page.isComplete()
    wizard.output_page.fields.path.edit.setText(str(tmp_path))
    assert wizard.output_page.isComplete()
    wizard.next()
    wizard.conversion.backup.setChecked(True)
    wizard.next()
    assert 'Layer backup: Yes' in wizard.summary.toPlainText()
    wizard.back()
    assert wizard.conversion.backup.isChecked()
    wizard.back()
    assert wizard.output_page.fields.path.text() == str(tmp_path)
    wizard.reject()


def test_wizard_cancel_waits_for_worker_cleanup(app, window, tmp_path, monkeypatch):
    window.add_discovered([(tmp_path / 'Movie.mkv', None)])
    def start(options):
        def operation(worker):
            worker.cancel.wait(3)
            return {'cancelled': 1}
        window.start_worker(operation, lambda totals: window.conversion_wizard.finish_operation(totals))
    monkeypatch.setattr(window, 'begin_conversion', start)
    window.open_conversion()
    wizard = window.conversion_wizard
    wizard.next()
    wizard.next()
    wizard.next()
    pump(app, lambda: window.worker is not None)
    assert not wizard.progress_page.isComplete()
    wizard.reject()
    assert wizard.isVisible()
    assert wizard.cancelling
    pump(app, lambda: window.worker is None)
    assert wizard.progress_page.isComplete()
    assert 'stopped' in wizard.progress_page.title()
    wizard.accept()


def test_missing_tools_failure_finishes_wizard(app, window, tmp_path, monkeypatch):
    from dovi_studio import ui
    monkeypatch.setattr(ui, 'discover', lambda paths: {name: Tool(name=name) for name in SPECS})
    window.add_discovered([(tmp_path / 'Movie.mkv', None)])
    window.open_conversion()
    wizard = window.conversion_wizard
    wizard.next()
    wizard.next()
    wizard.next()
    pump(app, lambda: wizard.progress_page.done)
    assert window.worker is None
    assert 'errors' in wizard.progress_page.title()
    assert 'dovi_tool' in wizard.progress_page.phase.text()
    wizard.accept()


def test_setup_invalidates_checked_paths(app):
    tools = {name: Tool(name=name, path='/tools/' + name, version='999.0', ok=True) for name in SPECS}
    wizard = SetupWizard(Options(), tools)
    wizard.show()
    wizard.next()
    assert wizard.tools_page.isComplete()
    wizard.tools_page.fields['dovi_tool'].edit.setText('/other/dovi_tool')
    assert not wizard.tools_page.isComplete()
    wizard.tools_page.set_tools(tools)
    assert wizard.tools_page.isComplete()
    wizard.reject()


def test_cancelling_setup_keeps_saved_tool_paths(app, window):
    window.options.tool_paths = {'dovi_tool': '/original/dovi_tool'}
    window.open_setup()
    window.setup_wizard.tools_page.fields['dovi_tool'].edit.setText('/other/dovi_tool')
    window.setup_wizard.reject()
    assert window.options.tool_paths['dovi_tool'] == '/original/dovi_tool'


def test_cancel_before_queued_conversion_start_does_not_launch(app, tmp_path):
    wizard = ConversionWizard(Options(), [tmp_path / 'Movie.mkv'])
    launched = []
    wizard.conversion_requested.connect(launched.append)
    wizard.show()
    wizard.next()
    wizard.next()
    wizard.next()
    wizard.reject()
    pump(app, lambda: wizard.progress_page.done)
    assert not launched
    wizard.accept()


def test_uncommitted_setup_probe_does_not_replace_active_tool_cache(app, window):
    original = {name: Tool(name=name, path='/old/' + name, version='999.0', ok=True) for name in SPECS}
    other = {name: Tool(name=name, path='/new/' + name, version='999.0', ok=True) for name in SPECS}
    window.tools = original
    window.open_setup()
    window.dependencies_ready(other, {'dovi_tool': '/new/dovi_tool'})
    window.setup_wizard.reject()
    assert window.tools == original
