import hashlib
import io
import json
import os
import sys
import tarfile
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest

from dovi_studio.dependencies import Tool, SPECS, discover, require
from dovi_studio.engine import Engine, discover_files, output_path, publish, pq_to_nits, read_archive
from dovi_studio.models import Analysis, Cancelled, OperationError, Options, Skipped
from dovi_studio.platform_tools import external_environment
from dovi_studio.process import Runner


def test_publish_does_not_replace_existing_file(tmp_path):
    staged, target = tmp_path / 'staged', tmp_path / 'movie.mkv'
    staged.write_bytes(b'new')
    target.write_bytes(b'original')
    with pytest.raises(OperationError, match='already exists'):
        publish(staged, target)
    assert target.read_bytes() == b'original'
    assert staged.read_bytes() == b'new'


def test_publish_complete_file(tmp_path):
    staged, target = tmp_path / 'staged', tmp_path / 'movie.mkv'
    staged.write_bytes(b'verified output')
    publish(staged, target)
    assert target.read_bytes() == b'verified output'
    assert not staged.exists()


def test_archive_rejects_links_without_extracting(tmp_path):
    path = tmp_path / 'hostile.dovi'
    with tarfile.open(path, 'w') as archive:
        member = tarfile.TarInfo('el.hevc')
        member.type = tarfile.SYMTYPE
        member.linkname = '../outside'
        archive.addfile(member)
    with pytest.raises(OperationError, match='regular'):
        read_archive(path, tmp_path, Runner(), allow_legacy=True)
    assert not (tmp_path / 'el.hevc').exists()


def write_archive(path, contents, manifest=None):
    with tarfile.open(path, 'w') as archive:
        for name, data in [('el.hevc', contents), *([('manifest.json', json.dumps(manifest).encode())] if manifest else [])]:
            member = tarfile.TarInfo(name)
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))


def test_archive_detects_corruption(tmp_path):
    path = tmp_path / 'damaged.dovi'
    manifest = {'format': 'dovi-studio-backup', 'version': 1, 'el_sha256': '0'*64}
    write_archive(path, b'not the original layer', manifest)
    with pytest.raises(OperationError, match='checksum'):
        read_archive(path, tmp_path, Runner())


def test_legacy_archive_requires_explicit_opt_in(tmp_path):
    archive = tmp_path / 'legacy.dovi'
    write_archive(archive, b'legacy layer')
    with pytest.raises(OperationError, match='Legacy'):
        read_archive(archive, tmp_path, Runner())
    output, manifest = read_archive(archive, tmp_path, Runner(), allow_legacy=True)
    assert output.read_bytes() == b'legacy layer'
    assert manifest is None


def test_queue_scan_depth_deduplication_and_generated_outputs(tmp_path):
    nested = tmp_path / 'one' / 'two'
    nested.mkdir(parents=True)
    for relative in ['main.MKV', 'main.p81.mkv', 'one/a.mkv', 'one/two/b.mkv']:
        (tmp_path / relative).touch()
    found = discover_files([tmp_path, tmp_path / 'main.MKV'], depth=1)
    assert {path.name for path, _ in found} == {'main.MKV', 'a.mkv'}
    # Explicitly selected conversions are allowed for inspection/restore workflows.
    assert len(discover_files([tmp_path / 'main.p81.mkv'])) == 1


def test_output_folder_structure_and_no_source_replacement(tmp_path):
    source = tmp_path / 'Library' / 'Show' / 'Episode.mkv'
    options = Options(output_dir=str(tmp_path / 'Output'))
    assert output_path(source, options, tmp_path / 'Library') == tmp_path / 'Output/Library/Show/Episode.p81.mkv'
    assert output_path(source, Options()) != source


@pytest.mark.parametrize('verdict,options,allowed', [
    ('mel', Options(), True),
    ('fel', Options(), False),
    ('fel', Options(include_fel=True), True),
    ('complex', Options(include_fel=True), False),
    ('unknown', Options(), False),
    ('complex', Options(allow_risky=True), True),
])
def test_conversion_policy(verdict, options, allowed):
    engine = Engine({}, options)
    analysis = Analysis(verdict=verdict, full=True)
    if allowed:
        engine.check_policy(analysis)
    else:
        with pytest.raises(Skipped):
            engine.check_policy(analysis)


def test_sampled_scan_cannot_authorize_conversion():
    with pytest.raises(OperationError, match='full metadata'):
        Engine({}, Options(allow_risky=True)).check_policy(Analysis('mel', full=False))


def test_risk_override_not_persisted():
    assert not Options.from_dict(Options(allow_risky=True).to_dict()).allow_risky


def test_pq_reference_values():
    assert pq_to_nits(0) == 0
    assert pq_to_nits(4095) == pytest.approx(10000)
    assert pq_to_nits(3079) == pytest.approx(1000, abs=3)


def test_arguments_never_interpreted_by_a_shell(tmp_path):
    argument = 'Café, a; echo bad $(whoami) & !.mkv'
    result = Runner().run([sys.executable, '-c', 'import sys; print(sys.argv[1])', argument])
    assert result.strip() == argument


def test_cancellation_terminates_running_process():
    cancel = threading.Event()
    timer = threading.Timer(0.15, cancel.set)
    timer.start()
    start = time.monotonic()
    with pytest.raises(Cancelled):
        Runner(cancel).run([sys.executable, '-c', 'import time; time.sleep(30)'])
    timer.join()
    assert time.monotonic() - start < 5


def test_pipe_checks_producer_exit_even_if_consumer_succeeds():
    with pytest.raises(OperationError, match='Streaming failed'):
        Runner().pipe([sys.executable, '-c', 'import sys; sys.stdout.write("partial"); sys.exit(7)'],
                      [sys.executable, '-c', 'import sys; print(sys.stdin.read())'])


def test_pipe_drains_large_stderr_without_deadlock():
    result = Runner().pipe([sys.executable, '-c', 'import sys; sys.stderr.write("x"*300000); sys.stdout.buffer.write(b"a"*500000)'],
                           [sys.executable, '-c', 'import sys; print(len(sys.stdin.buffer.read()))'])
    assert result.strip() == '500000'


def test_explicit_missing_tool_is_not_silently_replaced(tmp_path):
    tools = discover({'dovi_tool': str(tmp_path / 'missing-tool')})
    assert not tools['dovi_tool'].ok
    assert 'missing-tool' in tools['dovi_tool'].path


def test_optional_tool_fallbacks():
    tools = {name: Tool(name=name, path=name, ok=name in {'dovi_tool', 'mkvmerge', 'mkvextract', 'mediainfo'}) for name in SPECS}
    require(tools, 'disk')
    with pytest.raises(OperationError, match='ffmpeg'):
        require(tools, 'stream')


@pytest.mark.skipif(os.name == 'nt', reason='POSIX executable fixture')
def test_bundled_tools_win_over_path_and_explicit_overrides_still_work(tmp_path, monkeypatch):
    from dovi_studio import dependencies
    bundle, external = tmp_path / 'bundle/media-tools', tmp_path / 'external'
    bundle.mkdir(parents=True)
    external.mkdir()
    for directory, version in ((bundle, '999.0'), (external, '998.0')):
        for name in SPECS:
            executable = directory / name
            executable.write_text(f'#!/bin/sh\necho "version {version}"\n')
            executable.chmod(0o755)
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, '_MEIPASS', str(bundle.parent), raising=False)
    monkeypatch.setenv('PATH', str(external))
    tools = discover()
    require(tools, 'stream')
    assert all(tool.ok and Path(tool.path).parent == bundle for tool in tools.values())
    override = discover({'dovi_tool': str(external / 'dovi_tool')})
    assert override['dovi_tool'].version == '998.0.0'
    assert Path(override['mkvmerge'].path).parent == bundle


def test_frozen_bundle_does_not_leak_its_library_paths(monkeypatch):
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, '_MEIPASS', '/app/bundle', raising=False)
    monkeypatch.setenv('LD_LIBRARY_PATH', '/app/bundle')
    monkeypatch.setenv('LD_LIBRARY_PATH_ORIG', '/system/tools')
    monkeypatch.setenv('QT_PLUGIN_PATH', '/app/bundle/Qt/plugins')
    env = external_environment()
    assert env['LD_LIBRARY_PATH'] == '/system/tools'
    assert 'QT_PLUGIN_PATH' not in env
