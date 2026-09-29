# Functionality relative to dovi_convert 8.2.0

| Upstream capability | MKV Profile Converter implementation |
|---|---|
| Profile 7 → 8.1 | Standard desktop file manager and conversion wizard; shell-free pipeline |
| File/folder batch processing | File picker, drag/drop, recursive depth, individual row selection |
| Scan | Quick first-240-frame scan; exact coverage displayed |
| Inspect | Full RPU inspection; all L1 values examined when FEL is present |
| Simple/complex FEL checks | MaxCLL-based heuristic; unknown data handled conservatively |
| Include simple FEL / force | Explicit GUI options; risky override resets on restart |
| Standard/streaming conversion | Native subprocess pipe, checked exit codes on both tools |
| Safe disk mode | MKVToolNix extraction, timestamps reapplied and verified |
| HDR10 extraction | Output mode removes DV and enhancement-layer data |
| Retain audio/subtitles | All tracks remuxed; optional compressed-payload hashes |
| Original backup | Original MKV kept at its existing path; separate output copy |
| Enhancement-layer archive | Compatible `.dovi` TAR plus fingerprint manifest |
| Restore | Exact base matching for new archives; explicit legacy support |
| Temporary/output directories | Configurable; subfolder layout preserved for folder imports |
| Progress/logging | Background worker, stage/tool progress, logs and CSV export |
| Dependency checks | Setup wizard with versions, explicit paths, platform-specific search and install guidance |
| Cancellation | Stops tools, including both ends of pipes; cleans private temporary files |
| Delete backups / cleanup | Deliberately omitted: originals are never deleted by this app |
| In-place source replacement | Deliberately omitted: converted files use a distinct suffix |
| Auto package installation | Install instructions and official links, rather than unattended system changes |
| Upstream self-updater | Not included; rebuild/install a new application version |
| Docker/web terminal | Not needed for this native desktop interface |

Additional checks include output Profile 8.1 compatibility, RPU/frame-count
matching, source-identity rechecks, archive fingerprint matching, and preservation
of the source's video timestamps. Dependencies remain replaceable and independent
of the Qt runtime. No external `dovi_convert` installation is required.
