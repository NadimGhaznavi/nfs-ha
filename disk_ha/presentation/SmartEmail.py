"""Render a self-contained SMART email with escaped data and inline styling."""

from datetime import datetime
from html import escape
import re

from disk_ha.entity.DiskCheckReport import DiskCheckReport


CELL = "padding:10px 12px;border:1px solid #d8e4e1;text-align:left;vertical-align:top;overflow-wrap:anywhere;"
HEADING = "color:#173b35;font-size:20px;margin:28px 0 12px;"


def table(headers: tuple[str, ...], rows: list[list[str]]) -> str:
    head = "".join(f'<th scope="col" style="{CELL}background:#e8f3f0;">{escape(value)}</th>' for value in headers)
    body = "".join("<tr>" + "".join(f'<td style="{CELL}">{escape(value)}</td>' for value in row)
                   + "</tr>" for row in rows)
    return (f'<table cellspacing="0" cellpadding="0" style="border-collapse:collapse;width:100%;font-size:14px;">'
            f'<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>')


def attributes(output: str) -> list[list[str]]:
    """Read the last standard or brief table, preserving compound raw values."""
    rows = []
    columns = None
    for line in output.splitlines():
        fields = line.split()
        if fields[:2] == ["ID#", "ATTRIBUTE_NAME"]:
            columns = fields if all(key in fields for key in ("VALUE", "WORST", "THRESH", "RAW_VALUE")) else None
            rows = []
            continue
        if columns is None:
            continue
        if not fields or not fields[0].isdigit():
            columns = None
            continue
        raw_column = columns.index("RAW_VALUE")
        values = line.split(maxsplit=raw_column)
        if len(values) <= raw_column:
            continue
        rows.append([values[0], values[1], values[columns.index("VALUE")],
                     values[columns.index("WORST")], values[columns.index("THRESH")], values[raw_column]])
    return rows


def render(report: DiskCheckReport, hostname: str, generated_at: datetime, verbose: bool = True) -> str:
    status = "FAIL" if report.failed else "PASS"
    color = "#a52c36" if report.failed else "#17654c"
    toc = ['<li><a href="#summary" style="color:#17654c;">Health summary</a></li>']
    summaries = []
    sections = []
    for number, health in enumerate(report.disks, 1):
        role = "Source" if number == 1 else "Target"
        disk_status = "FAIL" if health.failed else "PASS"
        toc.append(f'<li><a href="#disk-{number}" style="color:#17654c;">Disk {number} · {role}</a>'
                   f' — <a href="#attributes-{number}" style="color:#17654c;">Attributes</a>'
                   f' · <a href="#diagnostics-{number}" style="color:#17654c;">Diagnostics</a></li>')
        summaries.append([f"Disk {number}", role, disk_status,
                          "; ".join(health.problems) or "No problems detected"])
        identity = [["Device", health.disk.device_path], ["Role", role], ["Health", disk_status],
                    ["Health command status", str(health.smart_status) if health.smart_status is not None else "Unavailable"]]
        labels = ("Model Family", "Device Model", "Serial Number", "Firmware Version", "User Capacity",
                  "Sector Sizes", "Rotation Rate", "SMART support is")
        metadata = {}
        for line in health.smart_output.splitlines():
            match = re.match(r"^([^:]+):\s*(.+)$", line)
            if match and match[1].strip() in labels:
                metadata[match[1].strip()] = match[2].strip()
        identity.extend([[label, value] for label, value in metadata.items()])
        sections.append(f'<h2 id="disk-{number}" style="{HEADING}">Disk {number} · {role}</h2>'
                        + table(("Property", "Value"), identity))
        if health.problems:
            sections.append('<h3 style="color:#a52c36;">Issues requiring attention</h3><ul>'
                            + "".join(f"<li>{escape(problem)}</li>" for problem in health.problems) + "</ul>")
        sections.append(f'<h3 id="attributes-{number}" style="{HEADING}">SMART attributes</h3>')
        rows = attributes(health.smart_output)
        sections.append(table(("ID", "Attribute", "Value", "Worst", "Threshold", "Raw value"), rows)
                        if rows else '<p>No readable SMART attribute table is available.</p>')
        sections.append(f'<h3 id="diagnostics-{number}" style="{HEADING}">'
                        + ("Complete SMART diagnostics" if verbose else "SMART diagnostics") + '</h3>')
        if health.smart_output and (verbose or health.failed):
            sections.append('<pre style="white-space:pre-wrap;word-wrap:break-word;overflow-wrap:anywhere;'
                            'font:12px/1.5 monospace;background:#f1f5f4;border:1px solid #d8e4e1;padding:16px;">'
                            + escape(health.smart_output) + '</pre>')
        else:
            sections.append('<p>No additional diagnostics included.</p>')
        sections.append('<p><a href="#contents" style="color:#17654c;">Back to contents</a></p>')
    notification = ('<p style="color:#a52c36;">Notification failure: '
                    + escape(report.notification_error) + '</p>' if report.notification_error else "")
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>SMART disk report</title></head>'
            '<body style="margin:0;padding:20px;background:#edf3f1;color:#253c36;font:15px/1.6 Arial,sans-serif;">'
            '<div style="max-width:960px;margin:0 auto;padding:24px;background:#ffffff;border:1px solid #d8e4e1;">'
            '<p style="margin:0;color:#17654c;font-weight:bold;">disk-ha</p>'
            '<h1 style="margin:4px 0 12px;font-size:28px;color:#173b35;">SMART disk report</h1>'
            f'<p><strong>Host:</strong> {escape(hostname)}<br><strong>Generated:</strong> '
            f'{escape(generated_at.strftime("%Y-%m-%d %H:%M:%S %Z"))}</p>'
            f'<p style="padding:14px;background:#f1f5f4;color:{color};font-weight:bold;">Overall health: {status}</p>'
            '<h2 id="contents" style="' + HEADING + '">Table of contents</h2><ul>' + "".join(toc) + '</ul>'
            '<h2 id="summary" style="' + HEADING + '">Health summary</h2>'
            + table(("Disk", "Role", "Health", "Details"), summaries) + notification
            + '<p>Disk health comes from the normal SMART check. Optional extended-command errors are retained in diagnostics.</p>'
            + "".join(sections) + '</div></body></html>')
