#!/usr/bin/env bash
set -euo pipefail

# =========================
# Config: adjust as needed
# =========================
HDD="/Volumes/LaCie"               # external HDD mount point
OUTROOT="$HDD/dv_out"              # final MP4s go here
TMPROOT="$HDD/dv_tmp"              # temp workspace root on LaCie
LOGROOT="$HDD/dv_logs"             # optional logs

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
command -v mediainfo >/dev/null 2>&1 || echo "Warning: mediainfo not found (DV check at end will be skipped)."

INPUT="$1"
[[ -r "$INPUT" ]] || { echo "Cannot read input: $INPUT"; exit 1; }
BASENAME="${2:-$(basename "${INPUT%.*}")}"

# =========================
# Prepare dirs & logging
# =========================
mkdir -p "$OUTROOT" "$TMPROOT" "$LOGROOT"
JOBTMP="$(mktemp -d "$TMPROOT/${BASENAME}.XXXX")"
trap '[[ "${KEEP_TEMP:-no}" == "yes" ]] || rm -rf "$JOBTMP"' EXIT

LOGFILE="$LOGROOT/${BASENAME}_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$LOGFILE") 2>&1

TMP="$JOBTMP"
OUTDIR="$OUTROOT"
OUT="$OUTDIR/${BASENAME}.DV8.1.mp4"

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
echo "    Log file  : $LOGFILE"
echo

# =========================
# Work filenames (NO FIFOs)
# =========================
BL="$TMP/${BASENAME}.BL.hevc"            # Annex B BL only
RPU="$TMP/${BASENAME}.RPU.bin"           # extracted/converted RPU
BL_RPU="$TMP/${BASENAME}.BL_RPU.hevc"    # Annex B BL with injected RPUs

# =========================
# Step 1: Extract BL (Annex B) to disk
# =========================
echo "==> Extracting BL (base layer) to Annex B..."
$NICE ffmpeg -nostdin -hide_banner -analyzeduration 200M -probesize 1G \
  -i "$INPUT" -map 0:v:0 -c copy -vbsf hevc_mp4toannexb -f hevc "$BL"

# =========================
# Step 2: Extract RPU (mapping mode 2) to disk
# =========================
echo "==> Extracting RPU (mapping mode 2)..."
# If BL already had RPUs, this still works; we’ll reinject clean P8.1 RPUs.
$NICE dovi_tool -m 2 extract-rpu -i "$BL" -o "$RPU"

# =========================
# Step 3: Inject RPU into BL to produce P8.1-compatible stream
# =========================
echo "==> Injecting RPU -> BL_RPU (P8.1)..."
$NICE dovi_tool -m 2 inject-rpu -i "$BL" --rpu-in "$RPU" -o "$BL_RPU"

# =========================
# Step 4: Extract/prepare audio tracks to disk (absolute indexes)
# =========================
echo "==> Extracting audio tracks (MP4-friendly) to temp..."
AUDIO_FILES=()
idx=0

add_audio_stream () {
  local aindex="$1" acodec="$2" af ext
  case "$acodec" in
    eac3)
      ext="eac3"; af="$TMP/${BASENAME}.a${idx}.${ext}"
      echo "   - stream $aindex ($acodec) -> $af (copy)"
      $NICE ffmpeg -nostdin -hide_banner -loglevel error \
        -i "$INPUT" -map 0:"$aindex" -c copy "$af"
      ;;
    ac3)
      ext="ac3"; af="$TMP/${BASENAME}.a${idx}.${ext}"
      echo "   - stream $aindex ($acodec) -> $af (copy)"
      $NICE ffmpeg -nostdin -hide_banner -loglevel error \
        -i "$INPUT" -map 0:"$aindex" -c copy "$af"
      ;;
    truehd)
      # Try AC-3 core first; if none embedded, transcode to E-AC-3 768k
      ext="ac3"; af="$TMP/${BASENAME}.a${idx}.${ext}"
      echo "   - stream $aindex (truehd) -> $af (extract AC-3 core)"
      if ! $NICE ffmpeg -nostdin -hide_banner -loglevel error \
           -i "$INPUT" -map 0:"$aindex" -c copy -bsf:a truehd_core "$af"; then
        af="$TMP/${BASENAME}.a${idx}.eac3"
        echo "     ! core missing; transcoding to E-AC-3 768k -> $af"
        $NICE ffmpeg -nostdin -hide_banner -loglevel error \
          -i "$INPUT" -map 0:"$aindex" -c:a eac3 -b:a 768k "$af"
      fi
      ;;
    aac|aac_latm|mp4a|alac)
      ext="m4a"; af="$TMP/${BASENAME}.a${idx}.${ext}"
      echo "   - stream $aindex ($acodec) -> $af (copy)"
      $NICE ffmpeg -nostdin -hide_banner -loglevel error \
        -i "$INPUT" -map 0:"$aindex" -c copy "$af"
      ;;
    dts|dca|dts_hd|dts_ma|flac)
      af="$TMP/${BASENAME}.a${idx}.eac3"
      echo "   - stream $aindex ($acodec) -> $af (transcode to E-AC-3 640k)"
      $NICE ffmpeg -nostdin -hide_banner -loglevel error \
        -i "$INPUT" -map 0:"$aindex" -c:a eac3 -b:a 640k "$af"
      ;;
    *)
      echo "   - Skipping stream $aindex ($acodec) – not suitable for MP4"
      return
      ;;
  esac
  AUDIO_FILES+=("$af")
  ((idx++))
}

while IFS=, read -r aindex acodec; do
  add_audio_stream "$aindex" "$acodec"
done < <(ffprobe -v error -select_streams a -show_entries stream=index,codec_name -of csv=p=0 "$INPUT")

[[ ${#AUDIO_FILES[@]} -eq 0 ]] && echo "   (No MP4-friendly audio found; video-only MP4 will be created.)"

# =========================
# Step 5: Mux to MP4 (video from BL_RPU, dv-profile=8), then force hvc1
# =========================
echo "==> Muxing to MP4 with MP4Box (dv-profile=8, hevc payload)..."
MP4_ARGS=( -quiet -tmp "$TMP" )
MP4_ARGS+=( -add "$BL_RPU:dv-profile=8:fmt=hevc:name=Video" )
for f in "${AUDIO_FILES[@]}"; do MP4_ARGS+=( -add "$f" ); done
MP4_ARGS+=( -brand mp42isom -ab dby1 -new "$OUT" )
MP4Box "${MP4_ARGS[@]}" </dev/null

echo "==> Ensuring video tag is hvc1..."
$NICE ffmpeg -nostdin -hide_banner -loglevel error \
  -i "$OUT" -map 0 -c copy -tag:v hvc1 "$OUT.tmp.mp4"
mv -f "$OUT.tmp.mp4" "$OUT"

# =========================
# Step 6: Optional source removal
# =========================
if [[ "${REMOVE_SOURCE:-no}" == "yes" ]]; then
  echo "==> REMOVE_SOURCE=yes set; deleting original MKV:"
  echo "    $INPUT"
  rm -f -- "$INPUT"
fi

# =========================
# Step 7: Done + quick verification
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
