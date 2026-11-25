"""Turn a plan into changes on disk."""
from __future__ import annotations

import logging
import os
import shlex
from dataclasses import replace
from pathlib import Path

from .config import Config
from .model import remap_content
from .plan import make_plan
from .probe import probe, read_media
from .tools import run_tool

log = logging.getLogger(__name__)


def remux(path: Path, order: list[int]) -> None:
    """Lossless track reorder; the original is only replaced once mkvmerge succeeded."""
    tmp = path.with_name(f".{path.stem}.reorder.tmp.mkv")
    try:
        run_tool(["mkvmerge", "-q", "-o", str(tmp),
                  "--track-order", ",".join(f"0:{i}" for i in order), str(path)])
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def process(path: Path, cfg: Config, title: str | None, dry: bool, source: str = "") -> bool:
    """Normalize one file. Returns True if it was (or would be) changed.

    `cfg` is this file's configuration (its VO included); `source` says where the
    title and VO come from, for the log.
    """
    log.info("\n== %s", path.name)
    log.info("   %s VO: %s, title: %s", f"[{source}]" if source else "", cfg.original,
             repr(title) if title else "left as is")
    media = probe(path, cfg)
    plan = make_plan(media, cfg, title)
    for note in plan.notes:
        log.info("   · %s", note)
    for warning in plan.warnings:
        log.warning("   ! %s", warning)

    changed = False
    if plan.needs_reorder:
        current = [t.id for t in media.tracks]
        log.info("   reordering tracks %s -> %s (lossless remux)", current, plan.order)
        if dry:
            media = media.reordered(plan.order)
        else:
            remux(path, plan.order)
            media = replace(read_media(path), content=remap_content(media.content, plan.order))
        plan = make_plan(media, cfg, title)   # same decisions, on the reordered layout
        changed = True

    args = plan.propedit_args()
    if not args:
        log.info("   already normalized" if not changed else "   nothing else to change")
        return changed
    if media.attachments:
        log.info("   removing %d attachment(s): %s", len(media.attachments),
                 ", ".join(a.file_name for a in media.attachments))
    cmd = ["mkvpropedit", "-q", str(path)] + args
    log.info("   $ %s", shlex.join(cmd))
    if not dry:
        run_tool(cmd)
    return True
