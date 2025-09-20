#!/usr/bin/env bash
set -euo pipefail

# =========================
# Config: adjust as needed
# =========================
HDD="/Volumes/LaCie"               # external HDD mount point
OUTROOT="$HDD/dv_out"              # final MP4s go here
TMPROOT="$HDD/dv_tmp"              # temp workspace root on LaCie

# --- NICE / throttling profile (auto-detect; set SPEED_MODE=fast|balanced|gentle) ---
if command -v taskpolicy >/dev/null 2>&1; then
  case "${SPEED_MODE:-balanced}" in
    fast)     NICE="" ;;
    balanced) NICE="$(command -v taskpolicy) -c background" ;;
    gentle)   NICE="$(command -v taskpolicy) -c background -t throttle" ;;
  esac
else
  case "${SPEED_MODE:-balanced}" in
    fast)     NICE="" ;;
    balanced) NICE="nice -n 5" ;;
    gentle)   NICE="nice -n 10" ;;
  esac
fi

# =========================
# Usage & prerequisites
# =========================
if [[ $# -lt 1 ]]; then
  echo "Usage: $(basename "$0") /path/to/input.mkv [optional_output_basename]"
  exit 1
fi

need() { command -v "$1" >/dev/null 2>&1 || { echo "Missing dependency: $1"; exit 1; }; }
need ffmpeg
need ffprobe
need dovi_tool
need MP4Box
need mediainfo || echo "Warning: mediainfo not found (DV check at end will be skipped)."

INPUT="$1"
[[ -r "$INPUT" ]] || { echo "Cannot read input: $INPUT"; exit 1; }

BASENAME="${2:-$(basename "${INPUT%.*}")}"

# Make per-job temp dir on LaCie so multiple runs don't collide
mkdir -p "$OUTROOT" "$TMPROOT"
JOBTMP="$(mktemp -d "$TMPROOT/${BASENAME}.XXXX")"
trap '[[ "${KEEP_TEMP:-no}" == "yes" ]] || rm -rf "$JOBTMP"' EXIT

TMP="$JOBTMP"        # shorthand
OUTDIR="$OUTROOT"    # shorthand

# sanity write test
touch "$TMP/.write_test" "$OUTDIR/.write_test" || {
  echo "ERROR: Cannot write to $TMP or $OUTDIR. Is $HDD writable (not NTFS read-only)?"
  exit 1
}
rm -f "$TMP/.write_test" "$OUTDIR/.write_test"

echo "==> Converting:"
echo "    Input     : $INPUT"
echo "    Temp dir  : $TMP"
echo "    Output dir: $OUTDIR"
echo

# =========================
# Work filenames
# =========================
RPU="$TMP/${BASENAME}.RPU.bin"
FIFO="$TMP/${BASENAME}.bl_rpu.fifo"
OUT="$OUTDIR/${BASENAME}.DV8.1.mp4"

cleanup_fifo() { [[ -p "$FIFO" ]] && rm -f "$FIFO"; }
trap cleanup_fifo EXIT

# =========================
# Step 1: Extract RPU (P7 -> P8.1 mapping mode 2) via pipe
# =========================
echo "==> Extracting RPU from BL via pipe (mapping mode 2)..."
# Convert BL to Annex B and stream to dovi_tool to extract RPU without writing BL.hevc
$NICE ffmpeg -hide_banner -loglevel error \
  -i "$INPUT" -map 0:v:0 -c copy -vbsf hevc_mp4toannexb -f hevc - \
  | $NICE dovi_tool -m 2 extract-rpu -i - -o "$RPU"

# =========================
# Step 2: Create FIFO and start BL+RPU producer
# =========================
echo "==> Creating FIFO for BL+RPU → MP4Box..."
cleanup_fifo
mkfifo "$FIFO"

echo "==> Starting producer (BL → inject RPU → FIFO)..."
(
  set -euo pipefail
  $NICE ffmpeg -hide_banner -loglevel error \
    -i "$INPUT" -map 0:v:0 -c copy -vbsf hevc_mp4toannexb -f hevc - \
  | $NICE dovi_tool -m 2 inject-rpu -i - --rpu-in "$RPU" -o - \
  > "$FIFO"
) &  # background producer writes BL+RPU to FIFO

# =========================
# Step 3: Extract MP4-friendly audio tracks to small temp files
# =========================
echo "==> Extracting audio tracks (MP4-friendly) to temp..."
AUDIO_FILES=()
idx=0

# helper: add one audio stream by index with codec-aware handling
add_audio_stream () {
  local aindex="$1" acodec="$2" af ext
  case "$acodec" in
    eac3)
      ext="eac3"; af="$TMP/${BASENAME}.a${idx}.${ext}"
      echo "   - stream $aindex ($acodec) -> $af (copy)"
      $NICE ffmpeg -hide_banner -loglevel error -i "$INPUT" -map 0:"$aindex" -c copy "$af"
      ;;
    ac3)
      ext="ac3"; af="$TMP/${BASENAME}.a${idx}.${ext}"
      echo "   - stream $aindex ($acodec) -> $af (copy)"
      $NICE ffmpeg -hide_banner -loglevel error -i "$INPUT" -map 0:"$aindex" -c copy "$af"
      ;;
    truehd)
      # Extract embedded AC-3 core (no re-encode). If core missing, transcode to E-AC-3.
      ext="ac3"; af="$TMP/${BASENAME}.a${idx}.${ext}"
      echo "   - stream $aindex (truehd) -> $af (extract AC-3 core)"
      if ! $NICE ffmpeg -hide_banner -loglevel error -i "$INPUT" -map 0:"$aindex" -c copy -bsf:a truehd_core "$af"; then
        af="$TMP/${BASENAME}.a${idx}.eac3"
        echo "     ! core missing; transcoding to E-AC-3 640k -> $af"
        $NICE ffmpeg -hide_banner -loglevel error -i "$INPUT" -map 0:"$aindex" -c:a eac3 -b:a 640k "$af"
      fi
      ;;
    aac|aac_latm|mp4a|alac)
      ext="m4a"; af="$TMP/${BASENAME}.a${idx}.${ext}"
      echo "   - stream $aindex ($acodec) -> $af (copy)"
      $NICE ffmpeg -hide_banner -loglevel error -i "$INPUT" -map 0:"$aindex" -c copy "$af"
      ;;
    dts|dca|dts_hd|dts_ma|flac)
      af="$TMP/${BASENAME}.a${idx}.eac3"
      echo "   - stream $aindex ($acodec) -> $af (transcode to E-AC-3 640k)"
      $NICE ffmpeg -hide_banner -loglevel error -i "$INPUT" -map 0:"$aindex" -c:a eac3 -b:a 640k "$af"
      ;;
    *)
      echo "   - Skipping stream $aindex ($acodec) – not suitable for MP4"
      return
      ;;
  esac
  AUDIO_FILES+=("$af")
  ((idx++))
}

# enumerate audio streams and add them
while IFS=, read -r aindex acodec; do
  add_audio_stream "$aindex" "$acodec"
done < <(ffprobe -v error -select_streams a -show_entries stream=index,codec_name -of csv=p=0 "$INPUT")

[[ ${#AUDIO_FILES[@]} -eq 0 ]] && echo "   (No MP4-friendly audio found; video-only MP4 will be created.)"

# ---------- FIXED MP4Box mux (properly quoted args) ----------
echo "==> Muxing to MP4 (dv-profile=8) from FIFO..."
MP4_ARGS=( -quiet -tmp "$TMP" )
# video from FIFO
MP4_ARGS+=( -add "$FIFO:dv-profile=8:fmt=hevc:name=Video" )
# each audio file
for f in "${AUDIO_FILES[@]}"; do
  MP4_ARGS+=( -add "$f" )
done
MP4_ARGS+=( -brand mp42isom -ab dby1 -new "$OUT" )

MP4Box "${MP4_ARGS[@]}"

echo "==> Ensuring video tag is hvc1..."
$NICE ffmpeg -hide_banner -loglevel error -i "$OUT" -map 0 -c copy -tag:v hvc1 "$OUT.tmp.mp4"
mv -f "$OUT.tmp.mp4" "$OUT"
# =========================
# Step 5: Optional source removal
# =========================
if [[ "${REMOVE_SOURCE:-no}" == "yes" ]]; then
  echo "==> REMOVE_SOURCE=yes set; deleting original MKV:"
  echo "    $INPUT"
  rm -f -- "$INPUT"
fi

# =========================
# Step 6: Done + quick verification
# =========================
echo
echo "==> Done:"
echo "    $OUT"
echo

if command -v mediainfo >/dev/null 2>&1; then
  echo "==> Quick DV check:"
  mediainfo "$OUT" | grep -i -E "dolby vision|dvhe|BL\+RPU|hvc1" || true
fi

echo "Tip: For fastest run, use SPEED_MODE=fast. Example:"
echo "     SPEED_MODE=fast $(basename "$0") \"$INPUT\""
