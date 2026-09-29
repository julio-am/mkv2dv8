from __future__ import annotations

import csv
import json
import threading
import traceback
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QItemSelectionModel, QSize, QThread, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QDialog, QDialogButtonBox, QFileDialog,
    QHeaderView, QLabel, QMainWindow, QMenu, QMessageBox, QPlainTextEdit,
    QProgressBar, QSplitter, QStyle, QTableWidget, QTableWidgetItem,
    QTabWidget, QToolBar, QVBoxLayout, QWidget,
)

from . import __version__, settings
from .dependencies import discover, require
from .dialogs import ArchiveDialog, ConversionWizard, OptionsDialog, SetupWizard
from .engine import Engine, discover_files
from .models import Cancelled, Job, OperationError, Options, Skipped
from .process import Runner

APP_NAME = 'MKV Profile Converter'
IDENTITY_ROLE = int(Qt.ItemDataRole.UserRole)
SORT_ROLE = IDENTITY_ROLE + 1


def icon(theme, fallback):
    return QIcon.fromTheme(theme, QApplication.style().standardIcon(fallback))


def app_icon():
    return icon('video-x-generic', QStyle.StandardPixmap.SP_FileIcon)


def file_size(size):
    value = float(size)
    for unit in ('B', 'KiB', 'MiB', 'GiB', 'TiB'):
        if value < 1024 or unit == 'TiB':
            return f'{value:.1f} {unit}' if unit != 'B' else f'{size} B'
        value /= 1024


class Worker(QThread):
    log = Signal(str)
    phase = Signal(str, int)
    job_changed = Signal(int, object)

    def __init__(self, function, parent=None):
        super().__init__(parent)
        self.function = function
        self.cancel = threading.Event()
        self.value = None
        self.error = ''
        self.cancelled = False

    def run(self):
        try:
            self.value = self.function(self)
        except Cancelled as error:
            self.cancelled = True
            self.error = str(error)
        except Exception as error:
            self.log.emit(traceback.format_exc())
            self.error = str(error)


class SortItem(QTableWidgetItem):
    def __lt__(self, other):
        left, right = self.data(SORT_ROLE), other.data(SORT_ROLE)
        if isinstance(left, (int, float)) and isinstance(right, (int, float)):
            return left < right
        return self.text().casefold() < other.text().casefold()


class FileTable(QTableWidget):
    files_dropped = Signal(list)

    def __init__(self):
        super().__init__(0, 7)
        self.setHorizontalHeaderLabels(['Name', 'Size', 'Video', 'Audio', 'Subtitles', 'Status', 'Folder'])
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setShowGrid(False)
        self.setAlternatingRowColors(True)
        self.setWordWrap(False)
        self.verticalHeader().hide()
        self.verticalHeader().setDefaultSectionSize(max(24, self.fontMetrics().height() + 8))
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self.horizontalHeader().setSectionsMovable(True)
        self.horizontalHeader().setStretchLastSection(True)
        for column, width in enumerate((285, 95, 90, 70, 80, 165, 220)):
            self.setColumnWidth(column, width)
        self.setSortingEnabled(True)
        self.sortItems(0, Qt.SortOrder.AscendingOrder)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        self.files_dropped.emit([url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()])
        event.acceptProposedAction()


class MainWindow(QMainWindow):
    def __init__(self, *, check_tools=True):
        super().__init__()
        self.options = settings.load()
        self.jobs: list[Job] = []
        self.tools = {}
        self.worker: Worker | None = None
        self.close_when_done = False
        self.conversion_wizard = None
        self.setup_wizard = None
        self._worker_callback = None
        self._failure_callback = None
        self._offer_setup = check_tools
        self._dialogs = []
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.resize(1080, 680)
        self.setMinimumSize(760, 450)
        self._build()
        self._menus_and_toolbar()
        self.update_actions()
        if check_tools:
            QTimer.singleShot(100, self.check_dependencies)

    def _build(self):
        self.table = FileTable()
        self.table.files_dropped.connect(self.import_paths)
        self.table.itemSelectionChanged.connect(self.selection_changed)
        self.table.itemDoubleClicked.connect(lambda item: self.show_properties())
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.context_menu)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(3000)
        self.detail_view = QPlainTextEdit()
        self.detail_view.setReadOnly(True)
        self.detail_view.setPlainText('Select a file to view its properties. Use Inspect to read media tracks and Dolby Vision metadata.')
        self.tabs = QTabWidget()
        self.tabs.addTab(self.detail_view, 'File properties')
        self.tabs.addTab(self.log_view, 'Log')
        self.tabs.setMinimumHeight(100)
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.addWidget(self.table)
        self.splitter.addWidget(self.tabs)
        self.splitter.setStretchFactor(0, 4)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([420, 130])
        self.setCentralWidget(self.splitter)
        self.queue_label = QLabel('No files')
        self.dependency_banner = QLabel('Checking media tools…')
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(180)
        self.progress.setVisible(False)
        self.statusBar().addWidget(self.queue_label, 1)
        self.statusBar().addPermanentWidget(self.progress)
        self.statusBar().addPermanentWidget(self.dependency_banner)

    def _action(self, text, callback, shortcut=None, theme=None, fallback=None):
        action = QAction(text, self)
        if theme:
            action.setIcon(icon(theme, fallback))
        if shortcut:
            action.setShortcut(shortcut)
        action.triggered.connect(callback)
        return action

    def _menus_and_toolbar(self):
        sp = QStyle.StandardPixmap
        self.add_action = self._action('Add &Files…', self.add_files, QKeySequence.StandardKey.Open, 'document-new', sp.SP_FileDialogNewFolder)
        self.add_folder_action = self._action('Add F&older…', self.add_folder, 'Ctrl+Shift+O', 'folder-open', sp.SP_DirOpenIcon)
        self.remove_action = self._action('&Remove', self.remove_selected, QKeySequence.StandardKey.Delete, 'edit-delete', sp.SP_TrashIcon)
        self.remove_action.setToolTip('Remove selected files from the list. Files on disk are kept.')
        self.scan_action = self._action('&Inspect', lambda: self.run_jobs('scan'), 'F6', 'document-properties', sp.SP_FileDialogInfoView)
        self.scan_action.setToolTip('Read file information and inspect the first 240 metadata frames')
        self.full_scan_action = self._action('&Full Inspection', lambda: self.run_jobs('inspect'), 'F7')
        self.convert_action = self._action('&Convert…', self.open_conversion, 'F9', 'media-playback-start', sp.SP_MediaPlay)
        self.backup_action = self._action('Create Layer &Archive…', lambda: self.open_archive(False), 'Ctrl+B', 'document-save', sp.SP_DialogSaveButton)
        self.restore_action = self._action('&Restore Profile 7…', lambda: self.open_archive(True), 'Ctrl+R', 'document-revert', sp.SP_ArrowBack)
        self.options_action = self._action('&Options…', self.open_options, None, 'preferences-system', sp.SP_FileDialogDetailedView)
        self.setup_action = self._action('Media Tools &Setup…', self.open_setup)
        self.cancel_action = self._action('&Cancel Operation', self.cancel_work, None, 'process-stop', sp.SP_BrowserStop)
        self.properties_action = self._action('&Properties…', self.show_properties, 'Alt+Return', 'dialog-information', sp.SP_MessageBoxInformation)
        self.open_output_action = self._action('Open Output &Folder', self.open_output)
        self.save_queue_action = self._action('&Save File List…', self.save_queue, QKeySequence.StandardKey.Save)
        self.load_queue_action = self._action('&Load File List…', self.load_queue, 'Ctrl+L')
        self.export_action = self._action('Export &Results…', self.export_report)
        self.log_action = self._action('Save &Log…', self.save_log)
        self.quit_action = self._action('&Quit', self.close, QKeySequence.StandardKey.Quit)
        self.quit_action.setMenuRole(QAction.MenuRole.QuitRole)
        file_menu = self.menuBar().addMenu('&File')
        file_menu.addActions([self.add_action, self.add_folder_action])
        file_menu.addSeparator()
        file_menu.addActions([self.load_queue_action, self.save_queue_action, self.export_action, self.log_action])
        file_menu.addSeparator()
        file_menu.addActions([self.open_output_action, self.properties_action])
        file_menu.addSeparator()
        file_menu.addAction(self.quit_action)
        edit = self.menuBar().addMenu('&Edit')
        self.select_all_action = self._action('Select &All', self.table.selectAll, QKeySequence.StandardKey.SelectAll)
        self.clear_selection_action = self._action('Select &None', self.table.clearSelection, 'Ctrl+Shift+A')
        self.invert_action = self._action('&Invert Selection', self.invert_selection, 'Ctrl+I')
        edit.addActions([self.select_all_action, self.clear_selection_action, self.invert_action])
        edit.addSeparator()
        edit.addAction(self.remove_action)
        view = self.menuBar().addMenu('&View')
        details = self._action('&Details Pane', lambda checked: self.tabs.setVisible(checked))
        details.setCheckable(True)
        details.setChecked(True)
        view.addAction(details)
        actions = self.menuBar().addMenu('&Actions')
        actions.addActions([self.scan_action, self.full_scan_action, self.convert_action, self.cancel_action])
        actions.addSeparator()
        actions.addActions([self.backup_action, self.restore_action])
        tools = self.menuBar().addMenu('&Tools')
        tools.addActions([self.options_action, self.setup_action])
        help_menu = self.menuBar().addMenu('&Help')
        help_menu.addAction(self._action('&Getting Started', self.show_help))
        about = self._action('&About MKV Profile Converter', self.show_about)
        about.setMenuRole(QAction.MenuRole.AboutRole)
        help_menu.addAction(about)
        self.toolbar = QToolBar('Main toolbar', self)
        self.toolbar.setObjectName('main-toolbar')
        self.toolbar.setMovable(False)
        self.toolbar.setIconSize(QSize(32, 32))
        self.toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self.addToolBar(self.toolbar)
        for action, caption in [(self.add_action, 'Add Files'), (self.add_folder_action, 'Add Folder'), (self.remove_action, 'Remove'),
                                (self.scan_action, 'Inspect'), (self.convert_action, 'Convert'), (self.backup_action, 'Backup'),
                                (self.restore_action, 'Restore'), (self.options_action, 'Options')]:
            if action in (self.scan_action, self.backup_action, self.options_action):
                self.toolbar.addSeparator()
            action.setIconText(caption)
            self.toolbar.addAction(action)
        self.toolbar.addSeparator()
        self.toolbar.addAction(self.cancel_action)
        self.cancel_action.setIconText('Cancel')
        view.addAction(self.toolbar.toggleViewAction())
        self.mutating_actions = [self.add_action, self.add_folder_action, self.remove_action, self.scan_action, self.full_scan_action,
                                 self.convert_action, self.backup_action, self.restore_action, self.options_action, self.setup_action,
                                 self.load_queue_action, self.select_all_action, self.clear_selection_action, self.invert_action]

    def update_actions(self):
        working = self.worker is not None
        selected = any(job.checked for job in self.jobs)
        for action in self.mutating_actions:
            action.setEnabled(not working)
        for action in (self.remove_action, self.scan_action, self.full_scan_action, self.convert_action):
            action.setEnabled(selected and not working)
        self.cancel_action.setEnabled(working)
        self.table.setAcceptDrops(not working)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection if working else QAbstractItemView.SelectionMode.ExtendedSelection)
        self.progress.setVisible(working)
        self.update_count()

    def update_count(self):
        self.queue_label.setText(f'{len(self.jobs)} file(s), {sum(job.checked for job in self.jobs)} selected')

    def snapshot_options(self):
        return replace(self.options, tool_paths=dict(self.options.tool_paths))

    def start_worker(self, function, result=None, failure=None):
        if self.worker:
            return False
        worker = Worker(function, self)
        self.worker = worker
        self._worker_callback, self._failure_callback = result, failure
        worker.log.connect(self.append_log)
        worker.phase.connect(self.set_phase)
        worker.job_changed.connect(self.update_job)
        worker.finished.connect(self.worker_finished)
        self.update_actions()
        self.progress.setRange(0, 0)
        worker.start()
        return True

    def worker_finished(self):
        worker = self.worker
        callback, failure = self._worker_callback, self._failure_callback
        self.worker = None
        self._worker_callback = self._failure_callback = None
        self.update_actions()
        # Consume results only after the subprocess-owning thread has stopped.
        try:
            if worker.error:
                self.append_log(worker.error)
                if failure:
                    failure(worker.error)
                elif not worker.cancelled:
                    QMessageBox.warning(self, 'Operation could not finish', worker.error)
            elif callback:
                callback(worker.value)
        finally:
            worker.deleteLater()
            if self.close_when_done:
                self.close()

    def append_log(self, text):
        self.log_view.appendPlainText(text)
        if self.conversion_wizard and self.conversion_wizard.running:
            self.conversion_wizard.append_log(text)

    def set_phase(self, text, percent):
        self.statusBar().showMessage(text)
        self.progress.setRange(0, 0 if percent < 0 else 100)
        if percent >= 0:
            self.progress.setValue(percent)
        if self.conversion_wizard and self.conversion_wizard.running:
            self.conversion_wizard.set_phase(text, percent)

    def cancel_work(self):
        if self.worker:
            self.worker.cancel.set()
            self.statusBar().showMessage('Cancelling… Waiting for media tools and temporary-file cleanup.')
            self.cancel_action.setEnabled(False)

    def check_dependencies(self, overrides=None):
        overrides = self.options.tool_paths if overrides is None or isinstance(overrides, bool) else overrides
        if self.worker:
            return
        if self.setup_wizard:
            self.setup_wizard.tools_page.checking()
        self.start_worker(lambda worker: discover(overrides), lambda tools: self.dependencies_ready(tools, overrides), self.dependencies_failed)

    def dependencies_failed(self, message):
        self.dependency_banner.setText('Media tools need setup')
        if self.setup_wizard:
            self.setup_wizard.tools_page.set_tools({})
            self.setup_wizard.tools_page.message.setText(message)

    def dependencies_ready(self, tools, overrides=None):
        if self.setup_wizard:
            self.setup_wizard.tools_page.set_tools(tools)
        if overrides is not None and overrides != self.options.tool_paths:
            return
        self.tools = tools
        try:
            require(tools)
            self.dependency_banner.setText('Media tools ready')
        except OperationError:
            self.dependency_banner.setText('Media tools need setup')
            if self._offer_setup and not self.close_when_done:
                QTimer.singleShot(0, self.open_setup)
        self._offer_setup = False
        self.statusBar().clearMessage()

    def open_setup(self):
        if self.worker:
            return
        if self.setup_wizard and self.setup_wizard.isVisible():
            self.setup_wizard.raise_()
            return
        wizard = SetupWizard(self.options, self.tools, self)
        self.setup_wizard = wizard
        wizard.tools_page.check_requested.connect(self.check_dependencies)
        def accept():
            self.options.tool_paths = wizard.tools_page.overrides()
            self.dependencies_ready(wizard.tools_page.checked_tools)
            self.save_settings()
        wizard.accepted.connect(accept)
        wizard.open()

    def open_options(self):
        dialog = OptionsDialog(self.options, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.options = dialog.value()
            self.save_settings()

    def open_conversion(self):
        paths = [job.path for job in self.jobs if job.checked]
        if self.worker or not paths:
            return
        wizard = ConversionWizard(self.snapshot_options(), paths, self)
        self.conversion_wizard = wizard
        wizard.conversion_requested.connect(self.begin_conversion)
        wizard.cancel_requested.connect(self.cancel_work)
        wizard.open()

    def begin_conversion(self, options):
        self.options = options
        self.save_settings()
        self.run_jobs('convert')

    def open_archive(self, restore):
        if self.worker:
            return
        current = self.current_job()
        dialog = ArchiveDialog(restore, str(current.path) if current else '', self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        options = self.snapshot_options()
        source = Path(dialog.source.text()).resolve()
        archive = Path(dialog.archive.text()).resolve() if restore else None
        legacy = dialog.legacy.isChecked()
        def operation(worker):
            engine = Engine(discover(options.tool_paths), options, Runner(worker.cancel, worker.log.emit), worker.phase.emit)
            return engine.restore(source, archive, allow_legacy=legacy) if restore else engine.backup(source)
        self.tabs.setCurrentWidget(self.log_view)
        self.tabs.show()
        self.start_worker(operation, lambda path: self.archive_done(path))

    def archive_done(self, path):
        self.append_log(f'Saved: {path}')
        self.statusBar().showMessage(f'Saved: {path}')
        QMessageBox.information(self, 'Operation complete', f'Saved:\n{path}')

    def add_files(self):
        if not self.worker:
            paths, _ = QFileDialog.getOpenFileNames(self, 'Add MKV Files', '', 'Matroska video (*.mkv *.MKV)')
            self.import_paths(paths)

    def add_folder(self):
        if not self.worker:
            path = QFileDialog.getExistingDirectory(self, 'Add Folder')
            if path:
                self.import_paths([path])

    def import_paths(self, paths):
        if paths and not self.worker:
            self.start_worker(lambda worker: discover_files([Path(path) for path in paths], self.options.recursive_depth), self.add_discovered)

    def add_discovered(self, items):
        seen = {job.path for job in self.jobs}
        for path, root in items:
            if path not in seen:
                self.jobs.append(Job(path, root))
                seen.add(path)
        self.render_queue()
        self.statusBar().clearMessage()

    def render_queue(self):
        current = self.current_job()
        current_path = current.path if current else None
        self.table.blockSignals(True)
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self.jobs))
        self.table.clearSelection()
        for row, job in enumerate(self.jobs):
            media = job.media
            try:
                size = media.size if media else job.path.stat().st_size
            except OSError:
                size = 0
            profile = f'Profile {media.profile}' if media and media.profile else '—'
            if media and media.profile == 8 and media.compatibility == 1:
                profile = 'Profile 8.1'
            audio = sum(track.get('type') == 'audio' for track in media.tracks) if media else 0
            subs = sum(track.get('type') == 'subtitles' for track in media.tracks) if media else 0
            values = (job.path.name, file_size(size), profile, str(audio) if media else '—', str(subs) if media else '—', job.status, str(job.path.parent))
            for column, value in enumerate(values):
                item = SortItem(value)
                item.setData(IDENTITY_ROLE, row)
                item.setData(SORT_ROLE, {1: size, 3: audio, 4: subs}.get(column))
                item.setToolTip(job.result if column == 5 else str(job.path) if column == 0 else value)
                if column == 0:
                    item.setIcon(app_icon())
                if column in (1, 3, 4):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(row, column, item)
            if job.checked:
                self.table.selectionModel().select(self.table.model().index(row, 0), QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
            if job.path == current_path:
                self.table.setCurrentCell(row, 0, QItemSelectionModel.SelectionFlag.NoUpdate)
        self.table.setSortingEnabled(True)
        self.table.blockSignals(False)
        self.update_actions()
        self.show_details()

    def selection_changed(self):
        if not self.worker:
            selected = {self.table.item(index.row(), 0).data(IDENTITY_ROLE) for index in self.table.selectionModel().selectedRows()}
            for index, job in enumerate(self.jobs):
                job.checked = index in selected
            self.update_actions()
        self.show_details()

    def current_job(self):
        item = self.table.item(self.table.currentRow(), 0)
        index = item.data(IDENTITY_ROLE) if item else None
        return self.jobs[index] if isinstance(index, int) and 0 <= index < len(self.jobs) else None

    def invert_selection(self):
        for job in self.jobs:
            job.checked = not job.checked
        self.render_queue()

    def remove_selected(self):
        if not self.worker:
            self.jobs = [job for job in self.jobs if not job.checked]
            self.render_queue()

    def update_job(self, row, job):
        self.jobs[row] = job
        self.render_queue()

    def detail_text(self, job):
        lines = [f'Name: {job.path.name}', f'Folder: {job.path.parent}', f'Status: {job.status}']
        if job.result:
            lines += ['', job.result]
        if job.analysis:
            lines += ['', f'Inspection: {"full file" if job.analysis.full else "first 240 frames"}', job.analysis.reason, job.analysis.summary]
        if job.media:
            lines += ['', 'Tracks:']
            for track in job.media.tracks:
                props = track.get('properties', {})
                lines.append(f'{track["id"]}  {track["type"]}  {track.get("codec", "")}  {props.get("language_ietf", props.get("language", "und"))}  {props.get("track_name", "")}')
        return '\n'.join(lines)

    def show_details(self):
        job = self.current_job()
        if not job:
            job = next((job for job in self.jobs if job.checked), None)
        self.detail_view.setPlainText(self.detail_text(job) if job else 'Select a file to view its properties.')

    def show_properties(self):
        job = self.current_job() or next((job for job in self.jobs if job.checked), None)
        if not job:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(job.path.name + ' — Properties')
        dialog.resize(620, 460)
        layout = QVBoxLayout(dialog)
        text = QPlainTextEdit(self.detail_text(job))
        text.setReadOnly(True)
        layout.addWidget(text)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    def context_menu(self, point):
        menu = QMenu(self)
        menu.addActions([self.convert_action, self.scan_action, self.full_scan_action])
        menu.addSeparator()
        menu.addActions([self.open_output_action, self.properties_action, self.remove_action])
        menu.exec(self.table.viewport().mapToGlobal(point))

    def run_jobs(self, action):
        if self.worker:
            return
        selected = [(index, replace(job)) for index, job in enumerate(self.jobs) if job.checked]
        if not selected:
            QMessageBox.information(self, 'No files selected', 'Select files in the list. Use Ctrl+A (Command+A on macOS) to select all.')
            return
        options = self.snapshot_options()
        self.save_settings()
        def operation(worker):
            tools = discover(options.tool_paths)
            require(tools, options.method if action == 'convert' else 'disk')
            runner = Runner(worker.cancel, worker.log.emit)
            totals = {'completed': 0, 'skipped': 0, 'failed': 0, 'cancelled': 0, 'not processed': 0}
            for sequence, (row, job) in enumerate(selected):
                if worker.cancel.is_set():
                    break
                def progress(stage, value):
                    worker.phase.emit(f'{sequence + 1}/{len(selected)} · {job.path.name} · {stage}', value)
                worker.phase.emit(f'File {sequence + 1} of {len(selected)}: {job.path.name}', 0)
                engine = Engine(tools, options, runner, progress)
                job.status, job.result = 'Working', ''
                worker.job_changed.emit(row, replace(job))
                try:
                    job.media = engine.probe(job.path)
                    if action == 'convert':
                        result, job.analysis = engine.convert(job.path, job.root)
                        job.status, job.result = 'Done', str(result)
                    else:
                        job.analysis = engine.inspect(job.media, full=action == 'inspect')
                        job.status = {'mel': 'MEL', 'fel': 'FEL', 'complex': 'Complex', 'unknown': 'Unknown', 'not-p7': 'Skipped'}[job.analysis.verdict]
                        job.result = job.analysis.reason
                    totals['skipped' if job.status == 'Skipped' else 'completed'] += 1
                except Cancelled as error:
                    job.status, job.result = 'Cancelled', str(error)
                    totals['cancelled'] += 1
                except Skipped as error:
                    job.status, job.result = 'Skipped', str(error)
                    totals['skipped'] += 1
                except Exception as error:
                    job.status, job.result = 'Failed', str(error)
                    totals['failed'] += 1
                    worker.log.emit(traceback.format_exc())
                worker.job_changed.emit(row, replace(job))
                worker.log.emit(f'{job.path.name}: {job.status}\n{job.result}')
                if worker.cancel.is_set():
                    break
            totals['not processed'] = len(selected) - sum(totals.values())
            return totals
        def complete(totals):
            summary = ', '.join(f'{value} {key}' for key, value in totals.items() if value)
            self.statusBar().showMessage('Finished: ' + summary)
            if action == 'convert' and self.conversion_wizard:
                self.conversion_wizard.finish_operation(totals)
        def failed(message):
            if action == 'convert' and self.conversion_wizard:
                self.conversion_wizard.finish_operation(error=message)
            else:
                QMessageBox.warning(self, 'Operation could not finish', message)
        self.start_worker(operation, complete, failed)

    def save_settings(self):
        try:
            settings.save(self.snapshot_options())
        except OSError as error:
            self.append_log(f'Could not save preferences: {error}')

    def save_queue(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Save File List', 'mkv-files.json', 'JSON (*.json)')
        if path:
            data = {'version': 1, 'files': [{'path': str(job.path), 'root': str(job.root) if job.root else None, 'checked': job.checked} for job in self.jobs]}
            try:
                Path(path).write_text(json.dumps(data, indent=2), encoding='utf-8')
            except OSError as error:
                QMessageBox.warning(self, 'Could not save file list', str(error))

    def load_queue(self):
        if self.worker:
            return
        path, _ = QFileDialog.getOpenFileName(self, 'Load File List', '', 'JSON (*.json)')
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text('utf-8'))
            if data.get('version') != 1 or len(data['files']) > 100000:
                raise ValueError('Unsupported file list')
            jobs = []
            for entry in data['files']:
                source = Path(entry['path']).expanduser().resolve()
                root = Path(entry['root']).resolve() if entry.get('root') else None
                if root and not source.is_relative_to(root):
                    root = None
                if source.suffix.lower() == '.mkv':
                    jobs.append(Job(source, root, checked=bool(entry.get('checked', True))))
            self.jobs = jobs
            self.render_queue()
        except (OSError, ValueError, KeyError, TypeError) as error:
            QMessageBox.warning(self, 'Could not load file list', str(error))

    def export_report(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Export Results', 'mkv-results.csv', 'CSV (*.csv)')
        if path:
            try:
                with Path(path).open('w', encoding='utf-8-sig', newline='') as stream:
                    writer = csv.writer(stream)
                    writer.writerow(['Source', 'Profile', 'Status', 'Inspection', 'Full pass', 'Result'])
                    for job in self.jobs:
                        values = [str(job.path), job.media.profile if job.media else '', job.status,
                                  job.analysis.verdict if job.analysis else '', job.analysis.full if job.analysis else '', job.result]
                        writer.writerow(["'" + str(value) if str(value).startswith(('=', '+', '-', '@')) else value for value in values])
            except OSError as error:
                QMessageBox.warning(self, 'Could not export results', str(error))

    def save_log(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Save Log', 'mkv-profile-converter.log', 'Log (*.log)')
        if path:
            try:
                Path(path).write_text(self.log_view.toPlainText(), encoding='utf-8')
            except OSError as error:
                QMessageBox.warning(self, 'Could not save log', str(error))

    def open_output(self):
        job = self.current_job() or next((job for job in self.jobs if job.checked), None)
        if job:
            folder = Path(job.result).parent if job.status == 'Done' else job.path.parent
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def show_help(self):
        QMessageBox.information(self, 'Getting Started', '1. Use Tools → Media Tools Setup to locate the required programs.\n\n2. Add MKV files or folders. Select files using click, Shift-click or Ctrl-click (Command-click on macOS).\n\n3. Click Inspect to read their media properties, or Convert to open the conversion wizard. Every conversion performs a full inspection.\n\n4. Follow the wizard to choose output, options, review, and convert.\n\nTools → Options changes the defaults. Backup and Restore manage enhancement-layer archives.')

    def show_about(self):
        QMessageBox.about(self, 'About ' + APP_NAME, f'{APP_NAME} {__version__}\n\nDolby Vision Profile 7 to Profile 8.1 MKV conversion.\nAudio and subtitles are retained.\n\nInspired by dovi_convert; uses dovi_tool, MKVToolNix, FFmpeg and MediaInfo. GPL-3.0-or-later.\n\nDolby and Dolby Vision are trademarks of Dolby Laboratories Licensing Corporation. This independent project is not affiliated with, sponsored by, or endorsed by Dolby.')

    def closeEvent(self, event):
        if self.worker:
            self.close_when_done = True
            self.cancel_work()
            event.ignore()
        else:
            self.save_settings()
            event.accept()
