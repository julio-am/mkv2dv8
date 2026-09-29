# Notices

MKV Profile Converter is distributed under GNU GPL version 3 or later. See LICENSE.

The workflow and FEL brightness heuristic were informed by
[cryptochrome/dovi_convert](https://github.com/cryptochrome/dovi_convert),
version 8.2.0, GPL-3.0. This application implements its own native GUI and
portable orchestration; it does not vendor or execute the upstream script.
It is not an official dovi_convert frontend.

External projects retain their respective licenses:

- [dovi_tool / quietvoid](https://github.com/quietvoid/dovi_tool): MIT.
- [MKVToolNix](https://mkvtoolnix.download/): GPL v2 or later.
- [FFmpeg](https://ffmpeg.org/): LGPL/GPL depending on build.
- [MediaInfo](https://mediaarea.net/): BSD-style license.
- [PySide6 / Qt for Python](https://doc.qt.io/qtforpython-6/): LGPLv3/GPLv3/commercial, depending on component.

Third-party media executables are not bundled. Native builds include the Qt
runtime installed from PySide6-Essentials; retain its license files when
redistributing. This source package includes everything needed to modify and
rebuild MKV Profile Converter.

Dolby and Dolby Vision are trademarks of Dolby Laboratories Licensing
Corporation. This independent project is not affiliated with, sponsored by,
or endorsed by Dolby. Dolby format names are used to identify the media the
application processes. The app does not use Dolby logos or claim Dolby
certification. Open-source copyright licenses do not themselves grant rights
to Dolby trademarks or establish clearance of third-party patents.

Optional integration-test data comes from the dovi_tool repository, under its
MIT license. The fixture-generation script fetches only explicitly named,
checksum-pinned test assets. No movie files are distributed in this package.
