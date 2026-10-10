"""Render the two-drive configuration table."""

from importlib.resources import files
from html import escape
from pathlib import Path

from disk_ha.constants.DDISKHA import DDISKHA
from disk_ha.interface.HealthResult import HealthResult
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
    page = page.replace("{{health}}", render_health())
    return page.encode("utf-8")


def render_health() -> str:
    try:
        result = HealthResult(Path(DDISKHA.HEALTH_RESULT)).read()
    except (OSError, ValueError):
        return "<p>Health results unavailable.</p>"
    if result is None:
        return "<p>No health check recorded.</p>"
    rows = []
    for number, disk in enumerate(result["disks"], 1):
        status = "FAIL" if disk["problems"] else "PASS"
        problems = "; ".join(disk["problems"]) or "No problems detected"
        rows.append(f'<tr><th scope="row">Disk {number}</th><td>{status}</td>'
                    f'<td>{escape(disk["disk"]["device_path"])}</td>'
                    f'<td>{escape(problems)}</td></tr>')
    notification = ("<p>Email alert delivery failed: " + escape(result["notification_error"]) + "</p>"
                    if result["notification_error"] is not None else "")
    return (f'<p>Last check: <time>{escape(result["checked_at"])}</time></p>'
            '<table><thead><tr><th scope="col">Device</th><th scope="col">Health</th>'
            '<th scope="col">Identity</th><th scope="col">Details</th></tr></thead>'
            '<tbody>' + "".join(rows) + '</tbody></table>' + notification)
