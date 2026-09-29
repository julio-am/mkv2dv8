# Validation record

Validation was performed in a Linux x86_64 environment. The complete suite
passed: **45 tests**, including **12 real-tool integration tests**. The machine-
readable result is in `test-results.xml`.

## Tools actually used

| Component | Version |
|---|---|
| Python | 3.12.14 |
| PySide6 / Qt | 6.11.2 |
| dovi_tool | 2.3.4 |
| MKVToolNix | 82.0 |
| FFmpeg / FFprobe | 6.1.1 |
| MediaInfo | 24.01 |
| PyInstaller | 6.22.3 |

## Executed checks

- Profile 7 MEL → Profile 8.1 using disk extraction and native streaming pipes.
- Profile 7 → HDR10 base-layer output.
- Enhancement-layer archive creation during conversion and independently.
- Restoration of Profile 7 from P8.1 plus its archive.
- MediaInfo fallback with both FFmpeg and FFprobe disabled.
- FFprobe-based operation with MediaInfo disabled.
- Full FEL inspection, brightness-expansion and missing-MaxCLL classifications,
  default FEL exclusion, and explicitly enabled FEL conversion.
- Exact source preservation and refusal to overwrite an existing output.
- Variable presentation timestamps, original video offset, track order,
  language/default/forced flags, and custom video-tag preservation.
- Two FLAC audio tracks and SRT subtitles retained; compressed stream hashes
  compared; chapters and attachment inventories preserved.
- Wrong base-video fingerprint and damaged archive rejection; legacy archive
  opt-in; rejection of archive symlinks.
- Cancellation cleanup and process termination; large stderr drain without
  pipe deadlock; failure detection on both sides of a streaming pipe.
- Unicode/spaces/comma/metacharacter filename handling without shell expansion.
- A real conversion completed through all pages of the conversion wizard.
- Ten GUI tests cover sortable file selection, removal without deleting source
  media, worker completion, settings cancellation, Back/Next state, destination
  validation, cancellation before and during processing, missing-tool errors,
  and setup verification invalidation without changing saved defaults.
- Main window, conversion wizard and media-tools setup screenshots were rendered
  from the working Qt application and inspected.
- A Linux PyInstaller distribution was built. Its offscreen startup remained
  running through first-run setup with no application errors. The headless Qt
  plugin may emit its standard propagateSizeHints notice. No display server
  was available for an interactive packaged-binary playback test.

## Scope of the evidence

Fixtures are small 259-frame test clips constructed from checksum-pinned
dovi_tool test assets, with generated audio, subtitles, chapters and an
attachment. They exercise real binaries, metadata parsing, remuxing and hashes.
This does not establish picture quality on a Dolby Vision display, behavior on
every codec or unusual Matroska layout, or reliability on a full-length UHD
remux. No user's movie files were available for those checks.

macOS and Windows were **not executed** in this environment. Their native
launchers, platform-specific tool discovery and library isolation, packaging
scripts, and GitHub Actions build matrix are included. Signed installers and
cross-platform CI results are not being claimed. The supplied Linux binary
was built against this environment's glibc; build from source on an older Linux
distribution if its system libraries cannot run the bundle.

## Native desktop interface (0.2.0)

The custom stylesheet and forced Fusion style were removed. Menus, toolbar,
file list, selection, dialogs, palette and wizards use the platform defaults.
The supplied screenshots show Qt's Linux/offscreen rendering; they are not
screenshots of macOS or Windows.

Windows Inno Setup and macOS pkgbuild installer recipes are included and wired
into CI. They were not compiled or run on those operating systems here. The
Linux app remains a portable TAR.GZ. Media Tools Setup discovers existing
programs and opens official download pages; it does not silently install them.

## Apple Silicon macOS test build (0.2.0)

[Build 36641162951](https://github.com/julio-am/mkv2dv8/actions/runs/36641162951)
ran on a native arm64 macOS 15.7.9 runner, using Python 3.12.10, Qt/PySide6
6.11.2, and PyInstaller 6.22.3. It built the app ZIP and Installer PKG from
commit `0ff7a6667f7fa04562b6844e36a5afcf72571ea9`.

- 33 unit and GUI tests passed; 12 media integration tests were deselected.
- Apple's Installer successfully installed the PKG into `/Applications`.
- The installed executable passed its arm64 architecture check and the app's
  ad-hoc code signature verified, including nested code.
- The installed app stayed running for eight seconds using native Cocoa,
  with no Python traceback. This is a startup smoke check, not a complete
  interactive conversion or playback test on macOS.
- Downloaded archive and installer SHA-256 hashes matched the runner outputs.

The app uses ad-hoc signing only. The Installer PKG is unsigned, and neither
artifact has been notarized. Media tools are external dependencies. The app ZIP
is also available under a `macOS-arm64.zip` filename; renaming it from the
runner's `Darwin-arm64.zip` did not alter its bytes. The machine-readable test
result is in `macos-test-results.xml`. Earlier references to unavailable macOS
execution describe the original Linux-only validation phase.

## Complete Apple Silicon installer (0.3.0)

[Build 36644951012](https://github.com/julio-am/mkv2dv8/actions/runs/36644951012)
passed on native Apple Silicon macOS 15, from commit
`62be4273e7d667cf68dcd4cf40c25bafc4a0d052`.

- All **46 tests passed**: 34 unit/GUI tests and 12 real-media integration tests.
- The package installs Python, Qt and all six media tools inside the app.
- Homebrew was moved out of its normal location before installation and
  runtime checks. The installed app automatically launched as the console
  user, not root, and opened without the dependency setup wizard.
- An additional check drove the installed native Cocoa GUI through a real
  Profile 7 MEL to Profile 8.1 streaming conversion with strict verification.
  Every discovered media tool resolved inside the installed app bundle.
- The 12 integration tests ran using only the bundled media executables.
  They cover conversion, audio/subtitle preservation, backup/restore,
  metadata fallbacks, FEL policy, cancellation and failure handling.
- The installed bundle passed arm64 architecture and deep code-signature
  verification. Its Mach-O dependencies were checked for unresolved
  references to build-machine libraries.
- Downloaded installer and app ZIP checksums matched the build output.

Bundled media versions: dovi_tool 2.3.4, MKVToolNix 101.0, FFmpeg/FFprobe
9.0.1, and MediaInfo 26.05. Media tools and GUI libraries are relocated in
separate directories to avoid loading incompatible QtCore versions.

Evidence: `macos-complete-unit-results.xml`,
`macos-complete-integration-results.xml`, and `macos-installed-app-check.json`.
The package requires Apple Silicon and macOS 15 or newer. It remains an
unsigned, unnotarized test installer with an ad-hoc-signed application.
Tests use small synthetic fixtures; a representative full-length title and
playback on the user's device still need user acceptance testing.
