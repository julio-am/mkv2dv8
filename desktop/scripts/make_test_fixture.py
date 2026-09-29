"""Create small reproducible test MKVs with real Dolby Vision metadata.

This explicitly requested developer command downloads checksum-pinned test data
from dovi_tool. The desktop app itself never downloads or uploads media.
"""
import argparse
import hashlib
import shutil
import subprocess
import urllib.request
from pathlib import Path

COMMIT = "614c816b6446dcd1dbaf433403d499a6026fbb5a"
ASSETS = {
    "assets/hevc_tests/regular_start_code_4_muxed_el.hevc": "968a31f36ceb785f43e097fa421f3e8b7e686f0c3973cc45bbb5ba48616de56a",
    "assets/hevc_tests/regular_rpu_mel.bin": "5a51b81485b61fc4b91fae354c7ff2946a63beb7ca69358dc2cfff2605581ef8",
    "assets/tests/fel_orig.bin": "b2b27714b7279c4e24d1a795cb6f95d3ad06745db96d360698ee0932184117a0",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path(".testdata"))
    args = parser.parse_args()
    folder = args.directory.resolve()
    folder.mkdir(parents=True, exist_ok=True)
    for name in ("dovi_tool", "mkvmerge", "ffmpeg"):
        if not shutil.which(name):
            raise SystemExit(f"Install {name} and put it on PATH first.")
    for relative, digest in ASSETS.items():
        target = folder / Path(relative).name
        if not target.exists():
            url = f"https://raw.githubusercontent.com/quietvoid/dovi_tool/{COMMIT}/{relative}"
            with urllib.request.urlopen(url, timeout=45) as response:
                payload = response.read()
            if hashlib.sha256(payload).hexdigest() != digest:
                raise SystemExit(f"Checksum mismatch: {relative}")
            target.write_bytes(payload)
        elif hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise SystemExit(f"Existing test asset differs: {target}")

    def run(*values):
        subprocess.run(list(map(str, values)), check=True)

    audio = folder / "audio.flac"
    if not audio.exists():
        run("ffmpeg", "-n", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=11", "-c:a", "flac", audio)
    (folder / "captions.srt").write_text("1\n00:00:00,100 --> 00:00:02,000\nHello, Dolby Vision!\n\n2\n00:00:03,000 --> 00:00:05,000\nSubtitles retained.\n", encoding="utf-8")
    (folder / "chapters.txt").write_text("CHAPTER01=00:00:00.000\nCHAPTER01NAME=Opening\nCHAPTER02=00:00:05.000\nCHAPTER02NAME=Second part\n", encoding="utf-8")
    (folder / "attachment.txt").write_text("MKV Profile Converter synthetic integration-test attachment", encoding="utf-8")
    (folder / "fel259.bin").write_bytes((folder / "fel_orig.bin").read_bytes() * 259)
    for kind, rpu in [("MEL", "regular_rpu_mel.bin"), ("FEL", "fel259.bin")]:
        target = folder / f"Sample {kind}.mkv"
        if target.exists():
            print(f"Keeping existing fixture: {target}")
            continue
        raw = folder / f"{kind}.hevc"
        run("dovi_tool", "inject-rpu", folder / "regular_start_code_4_muxed_el.hevc", "--rpu-in", folder / rpu, "-o", raw)
        run("mkvmerge", "-o", target, "--title", "Synthetic preservation test", "--chapters", folder / "chapters.txt",
            "--attachment-mime-type", "text/plain", "--attach-file", folder / "attachment.txt",
            "--default-duration", "0:24000/1001fps", "--language", "0:eng", "--track-name", "0:Original video", "--sync", "0:125", raw,
            "--language", "0:eng", "--track-name", "0:English lossless", "--default-track-flag", "0:yes", audio,
            "--language", "0:spa", "--track-name", "0:Comentario", "--default-track-flag", "0:no", audio,
            "--language", "0:eng", "--track-name", "0:English subtitles", "--forced-display-flag", "0:yes", folder / "captions.srt")
        print(f"Created: {target}")
    print(f"Set DOVI_TEST_FIXTURE to: {folder / 'Sample MEL.mkv'}")
    print(f"Set DOVI_TEST_FEL_FIXTURE to: {folder / 'Sample FEL.mkv'}")


if __name__ == "__main__":
    main()
