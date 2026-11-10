"""Single-file HTML report: tags, broken links and orphan notes."""

from __future__ import annotations

from collections import Counter
from html import escape

from .graph import link_edges, orphans
from .linkcheck import BrokenLink
from .parse import extract_tags
from .scan import Note

_STYLE = """
body{font:16px/1.5 system-ui,sans-serif;max-width:52rem;margin:2rem auto;padding:0 1rem;color:#222;background:#fff}
@media (prefers-color-scheme:dark){body{color:#ddd;background:#181818}th,td{border-color:#444}}
h1{margin-bottom:.2rem}h2{margin-top:2rem}.muted{color:#888}
table{border-collapse:collapse;width:100%}th,td{text-align:left;padding:.25rem .6rem;border-bottom:1px solid #ccc}
code{font-family:ui-monospace,monospace}.ok{color:#2a7a2a}.bad{color:#c0392b}
"""


def _table(headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(f"<th>{escape(h)}</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _code(text: str) -> str:
    return f"<code>{escape(text)}</code>"


def render_report(notes: list[Note], broken: list[BrokenLink], checked: int,
                  title: str = "notefind report") -> str:
    """Build the report page as one self-contained HTML string (no scripts)."""
    counts: Counter[str] = Counter()
    for note in notes:
        counts.update(extract_tags(note.text))
    tag_rows = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    lonely = orphans(notes, link_edges(notes))

    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{escape(title)}</title><style>{_STYLE}</style></head><body>",
        f"<h1>{escape(title)}</h1>",
        f'<p class="muted">{len(notes)} notes, {len(tag_rows)} tags, '
        f"{checked} links checked, {len(broken)} broken, {len(lonely)} orphans.</p>",
        "<h2>Broken links</h2>",
    ]
    if broken:
        rows = []
        for b in broken:
            note = escape(b.detail) if b.detail else escape(b.reason)
            if b.suggestion:
                note += f" - did you mean {_code(b.suggestion)}?"
            rows.append([_code(f"{b.path}:{b.line}"), _code(b.target), note])
        parts.append(_table(["Where", "Target", "Problem"], rows))
    else:
        parts.append('<p class="ok">No broken links.</p>')

    parts.append("<h2>Tags</h2>")
    if tag_rows:
        parts.append(_table(["Tag", "Notes"], [[_code("#" + t), str(c)] for t, c in tag_rows]))
    else:
        parts.append('<p class="muted">No tags.</p>')

    parts.append("<h2>Orphans</h2>")
    if lonely:
        parts.append("<p>Notes that no other note links to.</p><ul>"
                     + "".join(f"<li>{_code(r)}</li>" for r in lonely) + "</ul>")
    else:
        parts.append('<p class="ok">Every note is linked from somewhere.</p>')
    parts.append("</body></html>\n")
    return "\n".join(parts)
