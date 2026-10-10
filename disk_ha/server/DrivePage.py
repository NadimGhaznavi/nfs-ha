"""Render the two-drive configuration table."""

from importlib.resources import files

from disk_ha.interface.DriveUsage import read_usage


def render_page() -> bytes:
    page = (files("disk_ha.server") / "static/index.html").read_text(encoding="utf-8")
    for number in (1, 2):
        try:
            usage = read_usage(f"/exports/disk{number}")
        except OSError:
            capacity = used = "Unavailable"
        else:
            if usage is None:
                capacity = used = "Not mounted"
            else:
                capacity = f"{usage.total / 10**12:,.2f}"
                used = f"{usage.used / 10**12:,.2f}"
        page = page.replace(f"{{{{disk{number}_capacity}}}}", capacity)
        page = page.replace(f"{{{{disk{number}_usage}}}}", used)
    return page.encode("utf-8")
