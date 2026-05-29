"""Memo export + human approval gate (Part 3, agent 7 + Part 3.3).

Export to Markdown and styled HTML (browser → PDF is the zero-dependency path;
WeasyPrint/ReportLab can slot in later for server-side PDF). The approval gate
enforces that nothing is "issued" without sign-off — agent proposes, human disposes.
"""
from __future__ import annotations

from datetime import datetime, timezone

from regradar.agents.state import GapMemo, HumanApproval


def to_markdown(memo: GapMemo) -> str:
    return memo.body_markdown


def to_html(memo: GapMemo) -> str:
    """Render the memo Markdown to a self-contained, printable HTML document."""
    try:
        import markdown as md

        body = md.markdown(memo.body_markdown, extensions=["tables", "fenced_code"])
    except Exception:
        body = "<pre>" + memo.body_markdown.replace("<", "&lt;") + "</pre>"
    return _HTML_TEMPLATE.format(title=memo.title, status=memo.status.upper(), body=body)


# ---- human approval gate --------------------------------------------------
def approve(memo: GapMemo, approver: str, notes: str = "") -> tuple[GapMemo, HumanApproval]:
    memo = memo.model_copy(update={"status": "approved"})
    gate = HumanApproval(status="approved", approver=approver,
                         decided_at=datetime.now(timezone.utc), notes=notes)
    return memo, gate


def reject(memo: GapMemo, approver: str, notes: str = "") -> tuple[GapMemo, HumanApproval]:
    memo = memo.model_copy(update={"status": "rejected"})
    gate = HumanApproval(status="rejected", approver=approver,
                         decided_at=datetime.now(timezone.utc), notes=notes)
    return memo, gate


_HTML_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>{title}</title>
<style>
  @page {{ margin: 2cm; }}
  body {{ font-family: -apple-system, Inter, Segoe UI, Helvetica, sans-serif;
         color: #1a1a1f; max-width: 820px; margin: 2rem auto; line-height: 1.55; padding: 0 1rem; }}
  h1 {{ font-size: 1.6rem; border-bottom: 2px solid #4f46e5; padding-bottom: .4rem; }}
  h2 {{ font-size: 1.15rem; margin-top: 1.8rem; color: #4f46e5; }}
  table {{ border-collapse: collapse; width: 100%; font-size: .85rem; margin: .6rem 0; }}
  th, td {{ border: 1px solid #d6d6e0; padding: .4rem .6rem; text-align: left; vertical-align: top; }}
  th {{ background: #f2f2f8; }}
  blockquote {{ border-left: 3px solid #c7c7d6; margin: .3rem 0; padding: .1rem .9rem; color: #44454f;
               font-family: "JetBrains Mono", ui-monospace, monospace; font-size: .8rem; }}
  code, em {{ color: #6b6b76; }}
  .badge {{ display:inline-block; background:#4f46e5; color:#fff; padding:.15rem .6rem;
           border-radius:999px; font-size:.7rem; letter-spacing:.05em; }}
</style></head>
<body>
<div class="badge">{status}</div>
{body}
</body></html>"""
