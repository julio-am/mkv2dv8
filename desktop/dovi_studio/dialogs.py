"""Standard desktop dialogs. All controls use the operating system's Qt style."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QRadioButton, QSpinBox, QTabWidget, QVBoxLayout,
    QWidget, QWizard, QWizardPage,
)
from .dependencies import SPECS, install_guide, require
from .models import OperationError, Options


def text_label(text):
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    return label


class PathField(QWidget):
    changed = Signal()

    def __init__(self, value='', *, folder=True, pattern='', parent=None):
        super().__init__(parent)
        self.folder, self.pattern = folder, pattern
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.edit = QLineEdit(value)
        self.browse = QPushButton('Browse…')
        row.addWidget(self.edit, 1)
        row.addWidget(self.browse)
        self.edit.textChanged.connect(self.changed)
        self.browse.clicked.connect(self.choose)

    def choose(self):
        if self.folder:
            path = QFileDialog.getExistingDirectory(self, 'Select folder', self.text())
        else:
            path, _ = QFileDialog.getOpenFileName(self, 'Select file', self.text(), self.pattern)
        if path:
            self.edit.setText(path)

    def text(self):
        return self.edit.text().strip()


class OutputOptions(QWidget):
    changed = Signal()

    def __init__(self, options, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        group = QGroupBox('Output format')
        form = QFormLayout(group)
        self.mode = QComboBox()
        self.mode.addItem('Dolby Vision Profile 8.1 (.p81.mkv)', 'p81')
        self.mode.addItem('HDR10 base layer (.hdr10.mkv)', 'hdr10')
        self.mode.setCurrentIndex(max(0, self.mode.findData(options.mode)))
        form.addRow('&Format:', self.mode)
        layout.addWidget(group)
        destination = QGroupBox('Destination')
        box = QVBoxLayout(destination)
        self.beside = QRadioButton('Save in the same folder as each source file')
        self.custom = QRadioButton('Save in this folder:')
        self.path = PathField(options.output_dir)
        self.path.edit.setAccessibleName('Output folder')
        box.addWidget(self.beside)
        box.addWidget(self.custom)
        box.addWidget(self.path)
        self.custom.setChecked(bool(options.output_dir))
        self.beside.setChecked(not options.output_dir)
        self.path.setEnabled(self.custom.isChecked())
        self.custom.toggled.connect(self.path.setEnabled)
        self.custom.toggled.connect(self.changed)
        self.path.changed.connect(self.changed)
        self.mode.currentIndexChanged.connect(self.changed)
        layout.addWidget(destination)
        layout.addWidget(text_label('Original files are kept. Existing output files are skipped. Audio, subtitles, chapters and attachments are copied.'))
        layout.addStretch()

    def valid(self):
        return self.beside.isChecked() or bool(self.path.text())

    def apply(self, options):
        return replace(options, mode=self.mode.currentData(), output_dir='' if self.beside.isChecked() else self.path.text())


class ConversionOptions(QWidget):
    def __init__(self, options, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        group = QGroupBox('Enhancement layer')
        box = QVBoxLayout(group)
        self.backup = QCheckBox('Create an enhancement-layer backup (.dovi)')
        self.backup.setChecked(options.backup_el)
        self.fel = QCheckBox('Include FEL files without detected brightness expansion')
        self.fel.setChecked(options.include_fel)
        box.addWidget(self.backup)
        box.addWidget(self.fel)
        box.addWidget(text_label('Profile 8.1 discards the enhancement-layer picture data. Brightness checks cannot guarantee the same appearance for FEL sources. Creating a backup uses disk extraction.'))
        layout.addWidget(group)
        verify = QGroupBox('Verification')
        box = QVBoxLayout(verify)
        self.strict = QCheckBox('Compare audio and subtitle payload hashes (requires FFmpeg)')
        self.strict.setChecked(options.strict_verify)
        box.addWidget(self.strict)
        box.addWidget(text_label('All conversions check metadata, track inventory and video timing before saving. Hash verification adds full-file reads.'))
        layout.addWidget(verify)
        layout.addStretch()

    def apply(self, options):
        return replace(options, backup_el=self.backup.isChecked(), include_fel=self.fel.isChecked(), strict_verify=self.strict.isChecked())


class AdvancedOptions(QWidget):
    def __init__(self, options, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.method = QComboBox()
        self.method.addItem('Disk extraction', 'disk')
        self.method.addItem('Streaming (requires FFmpeg)', 'stream')
        self.method.setCurrentIndex(max(0, self.method.findData(options.method)))
        self.temp = PathField(options.temp_dir)
        self.temp.edit.setPlaceholderText('System temporary folder')
        self.depth = QSpinBox()
        self.depth.setRange(0, 99)
        self.depth.setValue(options.recursive_depth)
        form.addRow('&Method:', self.method)
        form.addRow('&Temporary folder:', self.temp)
        form.addRow('Folder scan &depth:', self.depth)
        layout.addLayout(form)
        group = QGroupBox('FEL override')
        box = QVBoxLayout(group)
        self.risky = QCheckBox('Allow complex or uncertain FEL files')
        self.risky.setChecked(options.allow_risky)
        box.addWidget(self.risky)
        box.addWidget(text_label('Accepts possible brightness, clipping or color changes. This override is cleared when the app restarts.'))
        layout.addWidget(group)
        layout.addStretch()

    def apply(self, options):
        return replace(options, method=self.method.currentData(), temp_dir=self.temp.text(), recursive_depth=self.depth.value(), allow_risky=self.risky.isChecked())


class OptionsDialog(QDialog):
    def __init__(self, options, parent=None):
        super().__init__(parent)
        self.original = options
        self.setWindowTitle('Options')
        self.resize(600, 450)
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        self.output = OutputOptions(options)
        self.conversion = ConversionOptions(options)
        self.advanced = AdvancedOptions(options)
        tabs.addTab(self.output, 'Output')
        tabs.addTab(self.conversion, 'Conversion')
        tabs.addTab(self.advanced, 'Advanced')
        layout.addWidget(tabs)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def value(self):
        return self.advanced.apply(self.conversion.apply(self.output.apply(self.original)))

    def accept(self):
        if not self.output.valid():
            QMessageBox.information(self, 'Output folder', 'Choose an output folder or save alongside each source file.')
            return
        super().accept()


class OutputPage(QWizardPage):
    def __init__(self, options):
        super().__init__()
        self.setTitle('Choose the output')
        self.setSubTitle('Select a format and destination for the selected MKV files.')
        layout = QVBoxLayout(self)
        self.fields = OutputOptions(options)
        layout.addWidget(self.fields)
        self.fields.changed.connect(self.completeChanged)

    def isComplete(self):
        return self.fields.valid()


class ProgressPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.done = False
        self.setTitle('Converting files')
        self.setSubTitle('Please wait while the selected files are converted and verified.')
        self.setFinalPage(True)
        layout = QVBoxLayout(self)
        self.phase = text_label('Starting…')
        self.progress = QProgressBar()
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(1500)
        layout.addWidget(self.phase)
        layout.addWidget(self.progress)
        layout.addWidget(QLabel('Details:'))
        layout.addWidget(self.log, 1)

    def isComplete(self):
        return self.done


class ConversionWizard(QWizard):
    conversion_requested = Signal(object)
    cancel_requested = Signal()

    def __init__(self, options: Options, paths: list[Path], parent=None):
        super().__init__(parent)
        self.original, self.paths = options, paths
        self.started = False
        self.running = False
        self.cancelling = False
        self.setWindowTitle('Convert MKV Files')
        self.resize(690, 530)
        self.setMinimumSize(580, 480)
        self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage)
        self.setOption(QWizard.WizardOption.NoBackButtonOnLastPage)
        self.setButtonText(QWizard.WizardButton.CommitButton, '&Convert')
        self.output_page = OutputPage(options)
        self.addPage(self.output_page)
        page = QWizardPage()
        page.setTitle('Choose conversion options')
        page.setSubTitle('Configure layer backups, verification and advanced settings.')
        layout = QVBoxLayout(page)
        tabs = QTabWidget()
        self.conversion = ConversionOptions(options)
        self.advanced = AdvancedOptions(options)
        tabs.addTab(self.conversion, 'General')
        tabs.addTab(self.advanced, 'Advanced')
        layout.addWidget(tabs)
        self.addPage(page)
        review = QWizardPage()
        review.setTitle('Ready to convert')
        review.setSubTitle('Review the settings below, then click Convert to begin.')
        review.setCommitPage(True)
        layout = QVBoxLayout(review)
        self.summary = QPlainTextEdit()
        self.summary.setReadOnly(True)
        layout.addWidget(self.summary)
        self.addPage(review)
        self.progress_page = ProgressPage()
        self.addPage(self.progress_page)
        self.currentIdChanged.connect(self.page_changed)

    def value(self):
        options = self.advanced.apply(self.conversion.apply(self.output_page.fields.apply(self.original)))
        return replace(options, method='disk') if options.backup_el else options

    def page_changed(self, page_id):
        if page_id == 2:
            opt = self.value()
            values = [f'Files: {len(self.paths)}', f'Output: {"Dolby Vision Profile 8.1" if opt.mode == "p81" else "HDR10"}',
                      f'Destination: {opt.output_dir or "Same folder as each source"}',
                      f'Method: {"Disk extraction" if opt.method == "disk" or opt.backup_el else "Streaming"}',
                      f'Layer backup: {"Yes" if opt.backup_el else "No"}',
                      f'Payload verification: {"Yes, when FFmpeg is available" if opt.strict_verify else "No"}',
                      f'Include FEL without expansion: {"Yes" if opt.include_fel else "No"}',
                      f'Complex / uncertain FEL override: {"Enabled" if opt.allow_risky else "Disabled"}', '', 'Source files:']
            self.summary.setPlainText('\n'.join(values + [str(path) for path in self.paths]))
        elif page_id == 3 and not self.started:
            self.started = self.running = True
            QTimer.singleShot(0, self.request_conversion)

    def request_conversion(self):
        if self.cancelling:
            self.finish_operation({'cancelled': len(self.paths)})
        else:
            self.conversion_requested.emit(self.value())

    def set_phase(self, text, percent):
        self.progress_page.phase.setText(text)
        self.progress_page.progress.setRange(0, 0 if percent < 0 else 100)
        if percent >= 0:
            self.progress_page.progress.setValue(percent)

    def append_log(self, message):
        self.progress_page.log.appendPlainText(message)

    def finish_operation(self, totals=None, error=''):
        self.running = False
        totals = totals or {}
        unsuccessful = bool(error or totals.get('failed') or totals.get('cancelled') or self.cancelling)
        title = 'Conversion stopped' if self.cancelling or totals.get('cancelled') else 'Conversion finished with errors' if error or totals.get('failed') else 'Conversion complete'
        self.progress_page.setTitle(title)
        self.progress_page.setSubTitle('Review the results below. Click Finish to return to the file list.')
        self.progress_page.progress.setRange(0, 100)
        if not unsuccessful:
            self.progress_page.progress.setValue(100)
        summary = error or ', '.join(f'{value} {key}' for key, value in totals.items() if value) or 'No files converted.'
        self.progress_page.phase.setText(summary)
        self.progress_page.log.appendPlainText(summary)
        self.progress_page.done = True
        self.progress_page.completeChanged.emit()
        self.button(QWizard.WizardButton.CancelButton).setEnabled(False)

    def reject(self):
        if self.running:
            if not self.cancelling:
                self.cancelling = True
                self.cancel_requested.emit()
                self.progress_page.phase.setText('Cancelling… Waiting for media tools and temporary-file cleanup.')
                self.button(QWizard.WizardButton.CancelButton).setEnabled(False)
            return
        super().reject()

    def closeEvent(self, event):
        if self.running:
            self.reject()
            event.ignore()
        else:
            super().closeEvent(event)


class ToolPage(QWizardPage):
    check_requested = Signal(dict)

    def __init__(self, overrides, tools):
        super().__init__()
        self.setTitle('Locate the media tools')
        self.setSubTitle('Existing installations are detected automatically. Browse to any portable executables.')
        self.ready = False
        layout = QVBoxLayout(self)
        self.fields, self.labels = {}, {}
        self.controls = QWidget()
        form = QFormLayout(self.controls)
        for name in SPECS:
            row = QWidget()
            box = QVBoxLayout(row)
            box.setContentsMargins(0, 0, 0, 3)
            field = PathField(overrides.get(name, ''), folder=False)
            field.edit.setPlaceholderText(tools[name].path if name in tools else 'Auto-detect')
            field.edit.setAccessibleName(name + ' executable')
            status_row = QHBoxLayout()
            status = QLabel('Not checked')
            download = QPushButton('Download…')
            download.clicked.connect(lambda checked=False, key=name: QDesktopServices.openUrl(QUrl(SPECS[key][1])))
            status_row.addWidget(status, 1)
            status_row.addWidget(download)
            box.addWidget(field)
            box.addLayout(status_row)
            form.addRow(name + ':', row)
            self.fields[name], self.labels[name] = field, status
            field.changed.connect(self.invalidate)
        layout.addWidget(self.controls)
        self.check = QPushButton('Detect and &check versions')
        self.check.clicked.connect(lambda: self.check_requested.emit(self.overrides()))
        layout.addWidget(self.check, 0, Qt.AlignmentFlag.AlignLeft)
        self.message = text_label('Required: dovi_tool, mkvmerge, mkvextract, and either FFprobe or MediaInfo. FFmpeg is optional.')
        layout.addWidget(self.message)
        self.set_tools(tools)

    def overrides(self):
        return {name: field.text() for name, field in self.fields.items()}

    def invalidate(self):
        self.ready = False
        self.message.setText('Paths changed. Click Detect and check versions to validate them.')
        self.completeChanged.emit()

    def isComplete(self):
        return self.ready

    def checking(self):
        self.ready = False
        self.controls.setEnabled(False)
        self.check.setEnabled(False)
        self.message.setText('Checking executable versions…')
        self.completeChanged.emit()

    def set_tools(self, tools):
        self.checked_tools = tools
        self.controls.setEnabled(True)
        self.check.setEnabled(True)
        for name, field in self.fields.items():
            tool = tools.get(name)
            if tool:
                self.labels[name].setText(f'Found: {tool.version}' if tool.ok else tool.message or 'Not found')
                self.labels[name].setWordWrap(True)
                field.edit.setPlaceholderText(tool.path or 'Not found — browse to executable')
        try:
            require(tools)
            self.ready = True
            self.message.setText('Required tools are ready. Click Next to finish setup.')
        except (OperationError, KeyError):
            self.ready = False
            self.message.setText('Install the missing required tools, then click Detect and check versions. FFmpeg is optional; FFprobe or MediaInfo is required.')
        self.completeChanged.emit()


class SetupWizard(QWizard):
    def __init__(self, options, tools, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Media Tools Setup')
        self.resize(760, 660)
        self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage)
        welcome = QWizardPage()
        welcome.setTitle('Set up MKV Profile Converter')
        welcome.setSubTitle('This wizard helps you find the media tools needed for conversion.')
        layout = QVBoxLayout(welcome)
        layout.addWidget(text_label('Install the tools using the instructions below, then click Next to check their locations. Downloads open the official project websites.'))
        guide = QPlainTextEdit(install_guide())
        guide.setReadOnly(True)
        layout.addWidget(guide, 1)
        layout.addWidget(text_label('Tools are installed separately. You can cancel setup and return later from Tools → Media Tools Setup.'))
        self.addPage(welcome)
        self.tools_page = ToolPage(options.tool_paths, tools)
        self.addPage(self.tools_page)
        done = QWizardPage()
        done.setTitle('Setup complete')
        done.setSubTitle('The required media tools are ready to use.')
        layout = QVBoxLayout(done)
        layout.addWidget(text_label('Click Finish to save these locations.\n\nAdd MKV files to the main window, select the files you want to process, and click Convert.'))
        layout.addStretch()
        self.addPage(done)


class ArchiveDialog(QDialog):
    def __init__(self, restore=False, source='', parent=None):
        super().__init__(parent)
        self.restore = restore
        self.setWindowTitle('Restore Profile 7' if restore else 'Create Layer Archive')
        self.resize(630, 280)
        layout = QVBoxLayout(self)
        layout.addWidget(text_label('Choose the converted MKV and its matching layer archive.' if restore else 'Save the enhancement layer and base-video fingerprint from an original Profile 7 MKV.'))
        form = QFormLayout()
        self.source = PathField(source, folder=False, pattern='Matroska video (*.mkv *.MKV)')
        self.archive = PathField(folder=False, pattern='Enhancement-layer archive (*.dovi)')
        form.addRow('Converted &MKV:' if restore else 'Source &MKV:', self.source)
        if restore:
            form.addRow('Layer &archive:', self.archive)
        layout.addLayout(form)
        self.legacy = QCheckBox('Allow a legacy dovi_convert archive without a fingerprint')
        self.legacy.setToolTip('Use only a known matching pair. Legacy archives cannot verify the base-video fingerprint.')
        if restore:
            layout.addWidget(self.legacy)
        layout.addWidget(text_label('Output and temporary folders follow Tools → Options. Existing files are not overwritten.'))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Restore' if restore else 'Create')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self):
        if not self.source.text() or not Path(self.source.text()).is_file() or (self.restore and (not self.archive.text() or not Path(self.archive.text()).is_file())):
            QMessageBox.information(self, 'Select files', 'Choose the required existing files before continuing.')
            return
        super().accept()
