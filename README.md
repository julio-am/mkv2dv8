# mkv2dv
A tool to remux .mkv files into files that are compatible with TVs that accept Dolby Vision 8.1


## Usage

```
# fastest run (no throttling)
SPEED_MODE=fast mkdv8 "/path/to/YourMovie.mkv"

# be gentle with system load
SPEED_MODE=gentle mkdv8 "/path/to/YourMovie.mkv"

# auto-remove the MKV after success
REMOVE_SOURCE=yes SPEED_MODE=fast mkdv8 "/path/to/YourMovie.mkv"

# keep temp files for debugging
KEEP_TEMP=yes SPEED_MODE=fast mkdv8 "/path/to/YourMovie.mkv"
```
