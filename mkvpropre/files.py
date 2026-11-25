"""Safe file operations: unpredictable temp files, moves that never overwrite."""
from __future__ import annotations

import errno
import os
import secrets
from pathlib import Path

# link() not supported by the file system (exFAT, some network shares, ...)
NO_HARD_LINKS = {errno.EPERM, errno.ENOTSUP, errno.EOPNOTSUPP, errno.EMLINK, errno.ENOSYS}


def exclusive_temp(near: Path, suffix: str) -> Path:
    """A new, empty, hidden file next to `near`, with an unpredictable name.

    Created with O_EXCL: it can't be a file or a symlink that someone placed
    there beforehand, so whatever writes to it can't be redirected elsewhere.
    """
    while True:
        tmp = near.with_name(f".{near.stem}.{secrets.token_hex(6)}{suffix}")
        try:
            with open(tmp, "xb"):
                return tmp
        except FileExistsError:
            continue


def rename_no_overwrite(src: Path, dest: Path) -> None:
    """Rename `src` to `dest` (same file system), failing if `dest` exists.

    A hard link is atomic and refuses to replace an existing file, unlike
    rename(). File systems without hard links fall back to check-then-rename.
    Raises FileExistsError if `dest` exists.
    """
    try:
        os.link(src, dest, follow_symlinks=False)
    except FileExistsError:
        raise
    except OSError as e:
        if e.errno not in NO_HARD_LINKS:
            raise
        if dest.exists() or dest.is_symlink():
            raise FileExistsError(errno.EEXIST, "File exists", str(dest)) from e
        os.rename(src, dest)
        return
    os.unlink(src)
