"""Portable media orchestration. Source MKVs are always opened read-only.

The FEL brightness heuristic follows the approach documented by dovi_convert
(GPL-3.0). It is advisory, not a proof of perceptual equivalence.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import shutil
import tarfile
import tempfile
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Callable

from . import __version__
from .dependencies import Tool, require
from .models import Analysis, Cancelled, Media, OperationError, Options, Skipped
from .process import Runner


def pq_to_nits(code: float) -> float:
    value = min(1.0, max(0.0, code / 4095.0)) ** (32.0 / 2523.0)
    return 10000.0 * (max(value - 3424.0 / 4096.0, 0.0) / (2413.0 / 128.0 - 2392.0 / 128.0 * value)) ** (16384.0 / 2610.0)


def fingerprint(path: Path) -> tuple[int, int, int, int]:
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns


def hash_file(path: Path, runner: Runner) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(4 * 1024 * 1024):
            runner.check()
            result.update(chunk)
    return result.hexdigest()


def publish(staged: Path, destination: Path) -> None:
    """Reserve with exclusive creation; atomically replace only our reservation.

    The staged file is on the destination filesystem, including for exFAT drives.
    This never replaces an existing user file, symlink, or another app instance's
    reservation. A crash may leave a zero-byte reservation, never corrupt a source.
    """
    try:
        with destination.open("xb") as target:
            identity = os.fstat(target.fileno())
    except FileExistsError as error:
        raise OperationError(f"Output already exists: {destination}") from error
    try:
        now = destination.stat()
        if (identity.st_dev, identity.st_ino) != (now.st_dev, now.st_ino):
            raise OperationError("Output reservation changed; refusing to replace it.")
        os.replace(staged, destination)
    except BaseException:
        try:
            now = destination.stat()
            if now.st_size == 0 and (identity.st_dev, identity.st_ino) == (now.st_dev, now.st_ino):
                destination.unlink()
        except OSError:
            pass
        raise


def discover_files(paths: list[Path], depth: int = 8) -> list[tuple[Path, Path | None]]:
    result, seen = [], set()
    for supplied in paths:
        supplied = supplied.expanduser().resolve()
        if supplied.is_file():
            candidates = [(supplied, None)]
        elif supplied.is_dir():
            candidates = []
            for folder, dirs, files in os.walk(supplied, followlinks=False):
                relative = Path(folder).relative_to(supplied)
                if len(relative.parts) >= depth:
                    dirs[:] = []
                dirs[:] = sorted(d for d in dirs if not d.startswith(".") and not (Path(folder) / d).is_symlink())
                for name in sorted(files):
                    # Do not pick up our own results on the next folder scan.
                    if not re.search(r"\.(?:p81|hdr10|restored)\.mkv$", name, re.I):
                        candidates.append((Path(folder) / name, supplied))
        else:
            continue
        for path, root in candidates:
            if path.suffix.lower() != ".mkv" or path.is_symlink():
                continue
            identity = path.resolve()
            if identity not in seen:
                seen.add(identity)
                result.append((identity, root))
    return result


def output_path(source: Path, options: Options, root: Path | None = None, suffix: str | None = None) -> Path:
    directory = Path(options.output_dir).expanduser().resolve() if options.output_dir else source.parent
    if root and options.output_dir:
        directory = directory / root.name / source.parent.relative_to(root)
    return directory / f"{source.stem}.{suffix or options.mode}.mkv"


def preserved_track_signature(track: dict) -> tuple:
    props = track.get("properties", {})
    keys = ("codec_id", "language", "language_ietf", "track_name", "default_track", "forced_track",
            "enabled_track", "hearing_impaired", "visual_impaired", "text_descriptions", "original", "commentary")
    return (track.get("type"), tuple((key, str(props[key])) for key in keys if key in props))


def verify_inventory(original: Media, converted: Media) -> None:
    original_tracks = Counter(preserved_track_signature(t) for t in original.tracks if t.get("type") != "video")
    new_tracks = Counter(preserved_track_signature(t) for t in converted.tracks if t.get("type") != "video")
    if original_tracks != new_tracks:
        raise OperationError("Audio/subtitle tracks or their language, names, or flags changed during remux.")
    if [t.get("type") for t in original.tracks] != [t.get("type") for t in converted.tracks]:
        raise OperationError("Track order changed during remux.")
    for old, new in zip(original.tracks, converted.tracks):
        old_time = old.get("properties", {}).get("minimum_timestamp")
        new_time = new.get("properties", {}).get("minimum_timestamp")
        if old_time is not None and new_time is not None and abs(old_time - new_time) > 1_010_000:
            raise OperationError("A track's starting timestamp changed during remux.")
    def attachments(media):
        return Counter((a.get("file_name"), a.get("content_type"), a.get("size")) for a in media.identification.get("attachments", []))
    if attachments(original) != attachments(converted):
        raise OperationError("Attachments were not retained.")
    def chapters(media):
        return sum(int(c.get("num_entries", 0)) for c in media.identification.get("chapters", []))
    if chapters(original) != chapters(converted):
        raise OperationError("Chapter counts changed during remux.")
    if original.duration and abs(original.duration - converted.duration) > max(0.25, original.duration * 0.0001):
        raise OperationError("Output duration differs from the source.")


class Engine:
    def __init__(self, tools: dict[str, Tool], options: Options, runner: Runner | None = None,
                 progress: Callable[[str, int], None] | None = None):
        self.tools, self.options = tools, options
        self.runner = runner or Runner()
        self.progress = progress or (lambda stage, value: None)
        self.stage_text = ""
        self.stage_min = self.stage_max = 0

    def tool(self, name: str) -> str:
        tool = self.tools[name]
        if not tool.ok:
            raise OperationError(f"{name}: {tool.message}. Open Dependencies to configure it.")
        return tool.path

    def stage(self, text: str, start: int, end: int | None = None):
        self.runner.check()
        self.stage_text, self.stage_min, self.stage_max = text, start, end if end is not None else start
        self.progress(text, start)
        self.runner.log(text)

    def on_line(self, text: str):
        matches = re.findall(r"(?:Progress:\s*|#GUI#progress\s+)(\d+)%?", text)
        if matches:
            value = min(int(matches[-1]), 100)
            self.progress(self.stage_text, round(self.stage_min + (self.stage_max - self.stage_min) * value / 100))

    def run(self, name: str, *args, cwd=None) -> str:
        return self.runner.run([self.tool(name), *map(str, args)], cwd=cwd,
                               accepted=(0, 1) if name.startswith("mkv") else (0,), on_line=self.on_line)

    def temp(self, directory: Path | None = None):
        directory = directory or (Path(self.options.temp_dir).expanduser() if self.options.temp_dir else None)
        if directory:
            directory.mkdir(parents=True, exist_ok=True)
        return tempfile.TemporaryDirectory(prefix="dovi-studio-", dir=directory)

    def probe(self, path: Path) -> Media:
        self.runner.check()
        if not path.is_file():
            raise OperationError(f"File does not exist: {path}")
        try:
            data = json.loads(self.run("mkvmerge", "-J", path))
        except ValueError as error:
            raise OperationError("MKVToolNix returned invalid identification data.") from error
        if data.get("errors"):
            raise OperationError("; ".join(data["errors"]))
        videos = [t for t in data.get("tracks", []) if t.get("type") == "video"]
        if len(videos) != 1:
            raise Skipped("Exactly one video track is supported. Separate-video-layer or multi-angle MKVs need preparation first.")
        media = Media(path, data, videos[0], size=path.stat().st_size)
        media.duration = data.get("container", {}).get("properties", {}).get("duration", 0) / 1e9
        if self.tools["ffprobe"].ok:
            try:
                raw = self.run("ffprobe", "-v", "error", "-select_streams", "v:0", "-show_streams", "-of", "json", path)
                stream = json.loads(raw).get("streams", [{}])[0]
                for side in stream.get("side_data_list", []):
                    if "dv_profile" in side:
                        media.profile = int(side["dv_profile"])
                        media.compatibility = int(side.get("dv_bl_signal_compatibility_id", -1))
                    if "max_content" in side and float(side["max_content"]) > 0:
                        media.max_cll = float(side["max_content"])
            except (OperationError, ValueError, IndexError) as error:
                if isinstance(error, Cancelled):
                    raise
                self.runner.log(f"ffprobe inspection unavailable; trying MediaInfo: {error}")
        if self.tools["mediainfo"].ok and (media.profile is None or media.max_cll is None):
            try:
                raw = json.loads(self.run("mediainfo", "--Output=JSON", path))
                video = next(t for t in raw.get("media", {}).get("track", []) if t.get("@type") == "Video")
                profile_text = " ".join(str(video.get(k, "")) for k in ("HDR_Format", "HDR_Format_Profile", "HDR_Format_Compatibility"))
                match = re.search(r"(?:dvhe|dvh1)\.(\d+)", profile_text, re.I) or re.search(r"Profile\s*(\d+)", profile_text, re.I)
                if match and media.profile is None:
                    media.profile = int(match.group(1))
                if media.profile == 8 and "HDR10" in profile_text and media.compatibility is None:
                    media.compatibility = 1
                match = re.search(r"\d+(?:\.\d+)?", str(video.get("MaxCLL", "")))
                if match and float(match.group()) > 0 and media.max_cll is None:
                    media.max_cll = float(match.group())
            except (OperationError, ValueError, StopIteration) as error:
                if isinstance(error, Cancelled):
                    raise
                self.runner.log(f"MediaInfo inspection unavailable: {error}")
        return media

    def inspect(self, media: Media, *, full: bool = True, directory: Path | None = None) -> Analysis:
        if media.profile != 7:
            return Analysis("not-p7", f"Dolby Vision Profile {media.profile}" if media.profile else "No Profile 7 metadata detected", full)
        if "HEVC" not in str(media.props.get("codec_id", media.video.get("codec", ""))).upper():
            raise Skipped("Only HEVC Profile 7 video is supported.")
        self.stage("Inspecting all Dolby Vision metadata" if full else "Inspecting first 240 metadata frames", 3, 12)
        with self.temp(directory) as temporary:
            work = Path(temporary)
            rpu = work / "source.rpu"
            args = ["extract-rpu", media.path, "-o", rpu]
            if not full:
                args += ["--limit", "240"]
            self.run("dovi_tool", *args)
            if not rpu.exists() or not rpu.stat().st_size:
                raise OperationError("No Dolby Vision metadata extracted; conversion was not started.")
            summary = self.run("dovi_tool", "info", "-i", rpu, "--summary")
            frame_match = re.search(r"Frames:\s*(\d+)", summary)
            count = int(frame_match.group(1)) if frame_match else 0
            if not re.search(r"(?m)^\s*Profile:\s*7\s*\([^\n]+\)\s*$", summary):
                raise OperationError("The metadata does not consistently identify Profile 7 throughout this inspection.")
            result = Analysis(full=full, rpu_count=count, base_peak_nits=media.max_cll, summary=summary)
            if count <= 0:
                result.reason = "Cannot establish metadata frame count."
                return result
            if "MEL" in summary and "FEL" not in summary:
                result.verdict, result.reason = "mel", "Minimal enhancement layer" + ("" if full else " (first 240 frames only)")
                return result
            if "FEL" not in summary:
                result.reason = "Could not establish enhancement-layer type from dovi_tool summary."
                return result
            # Export just L1 CSV, not enormous per-frame JSON documents. Relative
            # filenames avoid dovi_tool's comma-delimited export argument grammar.
            self.run("dovi_tool", "export", "-i", rpu, "-l", "level1=level1.csv", cwd=work)
            peak, rows = 0.0, 0
            with (work / "level1.csv").open(encoding="utf-8-sig", newline="") as stream:
                for row in csv.DictReader(stream):
                    self.runner.check()
                    if row.get("max_pq", "").strip():
                        peak = max(peak, pq_to_nits(float(row["max_pq"])))
                        rows += 1
            result.peak_nits = peak if rows else None
            if not rows or rows != count:
                result.reason = f"Incomplete L1 metadata ({rows}/{count} frames)."
            elif media.max_cll is None or media.max_cll < 100:
                result.reason = "FEL present, but reliable base-layer MaxCLL is unavailable."
            elif peak > media.max_cll + 50:
                result.verdict = "complex"
                result.reason = f"Possible brightness expansion: L1 peak {peak:.0f} nits exceeds base MaxCLL {media.max_cll:.0f} nits."
            else:
                result.verdict = "fel"
                result.reason = "FEL: no brightness expansion detected" + (" in the full metadata pass." if full else " in the first 240 frames; full inspection required.")
            return result

    def check_policy(self, analysis: Analysis):
        if not analysis.full:
            raise OperationError("Conversion requires a full metadata pass.")
        if analysis.verdict == "not-p7":
            raise Skipped(analysis.reason)
        if analysis.verdict == "fel" and not self.options.include_fel:
            raise Skipped("FEL is excluded. Enable 'Include FEL without detected expansion' to accept loss of enhancement-layer picture data.")
        if analysis.verdict in {"complex", "unknown"} and not self.options.allow_risky:
            raise Skipped(analysis.reason + " Enable the advanced override only if you accept the picture changes.")

    def extract_raw(self, media: Media, destination: Path):
        self.run("mkvextract", media.path, "tracks", f"{media.track_id}:{destination}")
        if not destination.is_file() or destination.stat().st_size == 0:
            raise OperationError("Extracted video is empty.")

    def ffmpeg_command(self, media: Media) -> list[str]:
        return [self.tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-i", str(media.path),
                "-map", "0:v:0", "-c:v", "copy", "-an", "-sn", "-dn", "-bsf:v", "hevc_mp4toannexb", "-f", "hevc", "-"]

    def timestamps(self, media: Media, path: Path) -> int:
        self.run("mkvextract", media.path, "timestamps_v2", f"{media.track_id}:{path}")
        count = 0
        previous = float("-inf")
        with path.open(encoding="utf-8-sig") as stream:
            for line in stream:
                if not line.strip() or line.startswith("#"):
                    continue
                value = float(line.strip())
                if value < previous:
                    raise OperationError("Non-monotonic presentation timestamps. Refusing to guess video timing.")
                previous = value
                count += 1
        if count < 2:
            raise OperationError("No video timestamps found.")
        # mkvextract writes one end timestamp after the per-frame timestamps.
        # Preserve it in the timing file, but do not count it as a video frame.
        return count - 1

    def remux(self, media: Media, raw: Path, timestamps: Path, output: Path):
        props = media.props
        args = ["--ui-language", "en_US", "-o", output]
        title = media.identification.get("container", {}).get("properties", {}).get("title")
        if title:
            args += ["--title", title]
        order = [f"0:0" if t.get("type") == "video" else f"1:{t['id']}" for t in media.tracks]
        args += ["--track-order", ",".join(order), "--timestamps", f"0:{timestamps}",
                 "--language", "0:" + props.get("language_ietf", props.get("language", "und")),
                 "--track-name", "0:" + props.get("track_name", "")]
        if props.get("default_duration"):
            args += ["--default-duration", f"0:{props['default_duration']}ns"]
        for key, switch in {"default_track": "--default-track-flag", "forced_track": "--forced-display-flag",
                            "enabled_track": "--track-enabled-flag"}.items():
            if key in props:
                args += [switch, f"0:{1 if props[key] else 0}"]
        display = props.get("display_dimensions")
        if display and re.fullmatch(r"\d+x\d+", display) and props.get("display_unit", 0) == 0:
            args += ["--display-dimensions", "0:" + display]
        if media.identification.get("track_tags"):
            all_tags = raw.parent / "source-tags.xml"
            self.run("mkvextract", media.path, "tags", all_tags)
            if all_tags.exists():
                source_tags = ET.parse(all_tags).getroot()
                video_tags = ET.Element("Tags")
                for tag in source_tags.findall("Tag"):
                    if str(props.get("uid")) in [node.text for node in tag.findall("Targets/TrackUID")]:
                        for target in tag.findall("Targets/TrackUID"):
                            tag.find("Targets").remove(target)
                        for item in list(tag.findall("Simple")):
                            name = item.findtext("Name", "")
                            if name in {"BPS", "DURATION", "NUMBER_OF_FRAMES", "NUMBER_OF_BYTES"} or name.startswith("_STATISTICS_"):
                                tag.remove(item)
                        if tag.findall("Simple"):
                            video_tags.append(tag)
                if len(video_tags):
                    tag_path = raw.parent / "video-tags.xml"
                    ET.ElementTree(video_tags).write(tag_path, encoding="utf-8", xml_declaration=True)
                    args += ["--tags", f"0:{tag_path}"]
        args += [raw, "--no-video", media.path]
        self.run("mkvmerge", *args)

    def verify(self, source: Media, target: Path, timestamps: Path, expected_profile: int | None, expected_rpus: int | None):
        output = self.probe(target)
        verify_inventory(source, output)
        if expected_profile is None:
            if output.profile is not None:
                raise OperationError("HDR10 output still advertises Dolby Vision.")
        elif output.profile != expected_profile:
            raise OperationError(f"Expected Profile {expected_profile}, detected {output.profile}. Update MediaInfo/FFmpeg/MKVToolNix if necessary.")
        if expected_profile == 8 and output.compatibility != 1:
            raise OperationError("Output is not verified as HDR10-compatible Dolby Vision Profile 8.1.")
        output_times = timestamps.with_name("output-timestamps.txt")
        frame_count = self.timestamps(output, output_times)
        # Stream the comparison so long videos do not grow Python memory usage.
        def values(path):
            with path.open(encoding="utf-8-sig") as stream:
                for line in stream:
                    if line.strip() and not line.startswith("#"):
                        yield float(line)
        from itertools import zip_longest
        for old, new in zip_longest(values(timestamps), values(output_times)):
            self.runner.check()
            if old is None or new is None or abs(old - new) > 1.01:
                raise OperationError("Video frame counts or timestamps changed during conversion.")
        if expected_rpus is not None and frame_count != expected_rpus:
            raise OperationError(f"Metadata/frame mismatch: {expected_rpus} Dolby Vision frames vs {frame_count} video frames.")
        if expected_profile in {7, 8}:
            output_rpu = timestamps.with_name("verified-output.rpu")
            self.run("dovi_tool", "extract-rpu", target, "-o", output_rpu)
            summary = self.run("dovi_tool", "info", "-i", output_rpu, "-s")
            match = re.search(r"Frames:\s*(\d+)", summary)
            if not match or int(match.group(1)) != frame_count:
                raise OperationError("Output is missing Dolby Vision metadata on one or more frames.")
            if not re.search(rf"(?m)^\s*Profile:\s*{expected_profile}(?:\s*\([^\n]+\))?\s*$", summary):
                raise OperationError("Output contains inconsistent Dolby Vision metadata profiles.")
        if self.options.strict_verify and self.tools["ffmpeg"].ok:
            # Hash compressed packets, not decoded PCM/video. No video re-encode.
            for track_type in ("a", "s"):
                if not any(t.get("type") == {"a": "audio", "s": "subtitles"}[track_type] for t in source.tracks):
                    continue
                digests = []
                for path in (source.path, target):
                    output_hash = self.run("ffmpeg", "-hide_banner", "-v", "error", "-nostdin", "-i", path,
                                           "-map", f"0:{track_type}", "-c", "copy", "-f", "streamhash", "-hash", "sha256", "-")
                    hashes = re.findall(r"SHA256=([0-9a-fA-F]{64})", output_hash)
                    if not hashes:
                        raise OperationError("Could not verify compressed audio/subtitle hashes.")
                    digests.append(hashes)
                if digests[0] != digests[1]:
                    raise OperationError("Audio/subtitle payload verification failed.")
        elif self.options.strict_verify:
            self.runner.log("FFmpeg unavailable: verified track inventory and video timestamps; payload hashing was not available.")

    def ensure_space(self, media: Media, work: Path, output: Path, factor: float):
        margin = 64 * 1024 * 1024
        for folder, needed in ((work, int(media.size * factor) + margin), (output, media.size + margin)):
            if shutil.disk_usage(folder).free < needed:
                raise OperationError(f"Insufficient free space in {folder}. Need approximately {needed / 1024**3:.1f} GiB for this stage.")
        if os.stat(work).st_dev == os.stat(output).st_dev:
            needed = int(media.size * (factor + 1)) + margin
            if shutil.disk_usage(work).free < needed:
                raise OperationError(f"Need approximately {needed / 1024**3:.1f} GiB free on the work/output drive.")

    def convert(self, source: Path, root: Path | None = None) -> tuple[Path, Analysis]:
        require(self.tools, self.options.method)
        if self.options.mode not in {"p81", "hdr10"} or self.options.method not in {"disk", "stream"}:
            raise OperationError("Invalid conversion settings.")
        before = fingerprint(source)
        media = self.probe(source)
        if media.profile != 7:
            raise Skipped("Only Dolby Vision Profile 7 MKVs are conversion candidates.")
        target = output_path(source, self.options, root)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise Skipped(f"Output already exists: {target}")
        with self.temp() as temp_dir, tempfile.TemporaryDirectory(prefix=".dovi-studio-", dir=target.parent) as final_dir:
            work, final = Path(temp_dir), Path(final_dir)
            self.ensure_space(media, work, target.parent, 3.2 if self.options.backup_el else 2.1 if self.options.method == "disk" else 1.1)
            analysis = self.inspect(media, full=True, directory=work)
            self.check_policy(analysis)
            timecodes = work / "timestamps.txt"
            self.stage("Preserving video timestamps", 13, 18)
            frames = self.timestamps(media, timecodes)
            if analysis.rpu_count != frames:
                raise OperationError(f"Source has {frames} video frames but {analysis.rpu_count} metadata frames. Refusing a partial conversion.")
            raw, converted = work / "source.hevc", work / "converted.hevc"
            if self.options.method == "disk" or self.options.backup_el:
                self.stage("Extracting original video", 18, 38)
                self.extract_raw(media, raw)
            staged_backup = None
            archive = target.with_suffix(".dovi")
            if self.options.backup_el:
                if archive.exists():
                    raise OperationError(f"Enhancement-layer backup already exists: {archive}")
                self.stage("Archiving enhancement layer", 38, 47)
                staged_backup = final / "layer.dovi"
                self.archive(media, raw, work, staged_backup, frames)
            self.stage("Converting Dolby Vision metadata" if self.options.mode == "p81" else "Extracting HDR10 base layer", 48, 68)
            args = ["-m", "2", "convert", "--discard"] if self.options.mode == "p81" else ["remove"]
            if raw.exists():
                self.run("dovi_tool", *args, raw, "-o", converted)
                raw.unlink()
            else:
                self.runner.pipe(self.ffmpeg_command(media), [self.tool("dovi_tool"), *args, "-", "-o", str(converted)], on_line=self.on_line)
            self.stage("Remuxing all audio, subtitles, chapters and attachments", 69, 84)
            staged = final / "output.mkv"
            self.remux(media, converted, timecodes, staged)
            self.stage("Verifying profile, tracks and timestamps", 85, 97)
            self.verify(media, staged, timecodes, 8 if self.options.mode == "p81" else None, frames if self.options.mode == "p81" else None)
            if fingerprint(source) != before:
                raise OperationError("Source changed during conversion; output was not published.")
            self.runner.check()
            if staged_backup:
                publish(staged_backup, archive)
            publish(staged, target)
        self.progress("Complete", 100)
        return target, analysis

    def archive(self, media: Media, raw: Path, work: Path, output: Path, frames: int):
        base, el = work / "base.hevc", work / "el.hevc"
        self.run("dovi_tool", "demux", raw, "-b", base, "-e", el)
        if not el.exists() or not el.stat().st_size:
            raise OperationError("No enhancement layer found to archive.")
        manifest = {"format": "dovi-studio-backup", "version": 1, "app_version": __version__,
                    "source": media.path.name, "frames": frames,
                    "base_sha256": hash_file(base, self.runner), "el_sha256": hash_file(el, self.runner)}
        encoded = json.dumps(manifest, indent=2).encode("utf-8")
        class CheckedReader:
            def __init__(self, stream, runner):
                self.stream, self.runner = stream, runner
            def read(self, size):
                self.runner.check()
                return self.stream.read(size)
        with tarfile.open(output, "w") as archive, el.open("rb") as stream:
            archive.copybufsize = 4 * 1024 * 1024
            layer = tarfile.TarInfo("el.hevc")
            layer.size = el.stat().st_size
            archive.addfile(layer, CheckedReader(stream, self.runner))
            member = tarfile.TarInfo("manifest.json")
            member.size = len(encoded)
            archive.addfile(member, io.BytesIO(encoded))
        base.unlink()
        el.unlink()

    def backup(self, source: Path, root: Path | None = None) -> Path:
        require(self.tools)
        before = fingerprint(source)
        media = self.probe(source)
        if media.profile != 7:
            raise Skipped("Enhancement-layer backup requires Profile 7.")
        destination = output_path(source, self.options, root, "backup").with_suffix(".dovi")
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise Skipped(f"Backup exists: {destination}")
        with self.temp() as tmp, tempfile.TemporaryDirectory(prefix=".dovi-studio-", dir=destination.parent) as final:
            work = Path(tmp)
            self.ensure_space(media, work, destination.parent, 3.2)
            self.stage("Extracting video for backup", 5, 40)
            raw = work / "source.hevc"
            self.extract_raw(media, raw)
            frames = self.timestamps(media, work / "timestamps.txt")
            self.stage("Creating verified enhancement-layer archive", 42, 90)
            staged = Path(final) / "backup.dovi"
            self.archive(media, raw, work, staged, frames)
            self.runner.check()
            if fingerprint(source) != before:
                raise OperationError("Source changed during backup.")
            publish(staged, destination)
        self.progress("Backup complete", 100)
        return destination

    def restore(self, source: Path, archive_path: Path, *, allow_legacy: bool = False) -> Path:
        require(self.tools)
        before = fingerprint(source)
        media = self.probe(source)
        if media.profile not in (None, 8) or (media.profile == 8 and media.compatibility != 1):
            raise Skipped("Restore requires the matching Profile 8.1 or HDR10 base-layer MKV.")
        target = output_path(source, self.options, suffix="restored")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise Skipped(f"Restored file exists: {target}")
        with self.temp() as tmp, tempfile.TemporaryDirectory(prefix=".dovi-studio-", dir=target.parent) as final:
            work = Path(tmp)
            self.ensure_space(media, work, target.parent, 4.2)
            self.stage("Checking enhancement-layer archive", 3, 10)
            el, manifest = read_archive(archive_path, work, self.runner, allow_legacy)
            self.stage("Extracting matching base layer", 11, 30)
            raw, base = work / "source.hevc", work / "base.hevc"
            self.extract_raw(media, raw)
            self.run("dovi_tool", "remove", raw, "-o", base)
            raw.unlink()
            timestamps = work / "timestamps.txt"
            frames = self.timestamps(media, timestamps)
            if manifest and (manifest.get("frames") != frames or manifest.get("base_sha256") != hash_file(base, self.runner)):
                raise OperationError("Backup does not match this exact base video. Use the corresponding unedited conversion.")
            self.stage("Rebuilding Profile 7", 35, 64)
            restored = work / "restored.hevc"
            self.run("dovi_tool", "mux", "--bl", base, "--el", el, "-o", restored)
            self.stage("Remuxing restored video with all tracks", 65, 84)
            staged = Path(final) / "restored.mkv"
            self.remux(media, restored, timestamps, staged)
            self.stage("Verifying restored Profile 7", 85, 97)
            self.verify(media, staged, timestamps, 7, frames)
            if fingerprint(source) != before:
                raise OperationError("Source changed during restore.")
            self.runner.check()
            publish(staged, target)
        self.progress("Restore complete", 100)
        return target


def read_archive(path: Path, destination: Path, runner: Runner, allow_legacy=False) -> tuple[Path, dict | None]:
    """Extract only a regular el.hevc; never use tar.extract/all or follow links."""
    with tarfile.open(path, "r:*") as archive:
        entries = []
        for member in archive:
            entries.append(member)
            if len(entries) > 16:
                raise OperationError("Unexpected archive contents.")
        layers = [entry for entry in entries if entry.name == "el.hevc"]
        manifests = [entry for entry in entries if entry.name == "manifest.json"]
        if len(layers) != 1 or not layers[0].isfile() or layers[0].size <= 0:
            raise OperationError("Backup must contain one regular, nonempty el.hevc file.")
        if layers[0].size + 64 * 1024**2 > shutil.disk_usage(destination).free:
            raise OperationError("Not enough space to extract the enhancement layer.")
        manifest = None
        if manifests:
            if len(manifests) != 1 or not manifests[0].isfile() or manifests[0].size > 65536:
                raise OperationError("Invalid backup manifest.")
            with archive.extractfile(manifests[0]) as stream:
                manifest = json.load(stream)
            if manifest.get("format") != "dovi-studio-backup" or manifest.get("version") != 1:
                raise OperationError("Unsupported backup manifest.")
        elif not allow_legacy:
            raise OperationError("Legacy .dovi archive has no base-video fingerprint. Enable legacy restore only for a known matching pair.")
        output = destination / "el.hevc"
        with archive.extractfile(layers[0]) as stream, output.open("xb") as out:
            while chunk := stream.read(4 * 1024 * 1024):
                runner.check()
                out.write(chunk)
        if manifest and manifest.get("el_sha256") != hash_file(output, runner):
            raise OperationError("Enhancement-layer checksum mismatch; archive is damaged.")
        return output, manifest
