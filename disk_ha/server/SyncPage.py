"""Stream the most recent rsync transcript as escaped text on its own page."""

from html import escape
from importlib.resources import files
from pathlib import Path
from typing import Iterator

from disk_ha.constants.DDiskHA import DDiskHA


def render_sync_output() -> Iterator[bytes]:
    page = (files("disk_ha.server") / "static/sync-output.html").read_text(encoding="utf-8")
    before, after = page.split("{{output}}", 1)
    yield before.encode("utf-8")
    try:
        with Path(DDiskHA.SYNC_RESULT).open(encoding="utf-8", errors="replace") as stream:
            while chunk := stream.read(65536):
                yield escape(chunk).encode("utf-8")
    except FileNotFoundError:
        yield b"No data sync has run yet."
    except OSError:
        yield b"Sync output unavailable."
    yield after.encode("utf-8")
