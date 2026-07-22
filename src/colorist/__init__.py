# SPDX-License-Identifier: MIT
"""colorist: an ffmpeg-based measure-first color pipeline.

Importing colour-science emits a one-line warning when Matplotlib is absent,
which none of this project's paths need. The filter is installed here, before
any submodule imports colour, so the CLI and library stay quiet about an
optional feature they do not use. It is matched by message text to avoid
importing colour (and triggering the warning) just to name its category.
"""

import sys as _sys
import warnings as _warnings

if _sys.version_info[:2] < (3, 11):
    _version = ".".join(str(part) for part in _sys.version_info[:3])
    raise RuntimeError(
        f"colorist requires Python 3.11 or newer; running Python {_version}"
    )

_warnings.filterwarnings(
    "ignore",
    message=r'.*"Matplotlib" related API features are not available.*',
)
