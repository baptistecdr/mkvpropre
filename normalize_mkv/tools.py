"""Running MKVToolNix."""
from __future__ import annotations

import logging
import shutil
import subprocess

log = logging.getLogger(__name__)

REQUIRED_TOOLS = ("mkvmerge", "mkvextract", "mkvpropedit")


class ToolError(Exception):
    pass


def missing_tools() -> list[str]:
    return [tool for tool in REQUIRED_TOOLS if not shutil.which(tool)]


def run_tool(cmd: list[str]) -> str:
    """Run an MKVToolNix tool. Exit 1 = warnings only (the job is done); 2 = error."""
    cmd = [cmd[0], "--output-charset", "UTF-8"] + cmd[1:]
    res = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace")
    output = "\n".join(s.strip() for s in (res.stdout, res.stderr) if s.strip())
    if res.returncode == 1:
        warnings = [line for line in output.splitlines() if line.startswith("Warning:")]
        for line in warnings or [f"{cmd[0]} reported warnings"]:
            log.warning("   ! %s", line)
    elif res.returncode != 0:
        tail = "\n".join(output.splitlines()[-5:])
        raise ToolError(f"{cmd[0]} failed (exit {res.returncode}): {tail}")
    return res.stdout
