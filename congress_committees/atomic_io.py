"""Atomic file writes for the on-disk caches.

Write to a temp file in the same directory, then ``os.replace`` it onto the
destination. ``os.replace`` is atomic on POSIX, so a reader never sees a
half-written file and an interrupted or concurrent write can't leave a corrupt
file at the destination.
"""

import os
import tempfile
from pathlib import Path
from typing import Union


def atomic_write_bytes(path: Union[str, Path], data: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        dir=str(path.parent), prefix=f"{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def atomic_write_text(path: Union[str, Path], text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))
