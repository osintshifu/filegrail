"""Shared, offline report identity and technical provenance."""

from html import escape

from . import __version__

STYLE = """
.mast.report-head{padding:32px max(24px,calc((100% - 1360px)/2)) 20px;
border-top:3px solid var(--brand);border-bottom:1px solid var(--line)}
.report-head .report-eyebrow{display:flex;gap:12px;align-items:center;color:var(--accent);
font:500 11px/1.5 var(--mono);letter-spacing:.13em;text-transform:uppercase}
.report-head .report-eyebrow span{color:var(--muted);letter-spacing:0;text-transform:none}
.report-head .report-title{font:500 clamp(28px,3vw,42px)/1.15 var(--sans);
letter-spacing:-.035em;margin:12px 0 14px;color:var(--ink)}
.report-head .report-meta{font-family:var(--mono);display:flex;
flex-wrap:wrap;gap:8px 24px;margin:0 0 14px;
font-size:12px;color:var(--ink-2)}
.report-head .report-meta div{display:flex;gap:8px;align-items:baseline}
.report-head dt{color:var(--muted);font-weight:400}
.report-head dd{margin:0;overflow-wrap:anywhere}
.report-head .report-scope{display:flex;align-items:baseline;gap:12px;
font:12px/1.6 var(--mono);color:var(--ink-2);overflow-wrap:anywhere}
.report-head .report-scope span{flex:none;color:var(--muted)}
.report-head details{margin-top:12px;font-size:12px;color:var(--muted)}
.report-head summary{cursor:pointer;width:fit-content}
.report-head details dl{display:grid;grid-template-columns:auto minmax(0,1fr);
gap:6px 18px;padding:12px 0;font:12px/1.6 var(--mono)}
.report-head .figures{justify-content:flex-start;flex-wrap:wrap;gap:16px 0;
margin-top:22px;padding-top:16px;border-top:1px solid var(--line)}
.report-head .figures li{padding:0 22px;border-left:1px solid var(--line)}
.report-head .figures li:first-child{padding-left:0;border:0}
.report-head .figures .n{font-size:22px}
.report-head .figures .label{font-size:10px;letter-spacing:.08em}
.cards{gap:18px 0}.cards .card{background:transparent;border:0;border-left:1px solid var(--line);
border-radius:0;box-shadow:none;min-height:0;padding:0 16px}.cards .card:first-child{border-left:0}
.cards .card{gap:4px}.cards .card .v{font-family:var(--mono);font-size:24px}
.cards .card .s{font-size:11px}
@media(max-width:600px){.mast.report-head{padding:22px 16px 16px}
.report-head .report-meta{gap:6px 16px}.report-head .figures{display:grid;
grid-template-columns:repeat(3,minmax(0,1fr));gap:16px 8px}
.report-head .figures li{padding:0;border:0}.report-head .figures .label{white-space:normal}}
@media print{.report-head details dl{display:grid}.report-head summary{display:none}}
"""


def header(
    title: str,
    target: str,
    metadata: list[tuple[str, str]],
    details: list[tuple[str, str]],
    *,
    figures: str = "",
) -> str:
    """Render escaped identity fields; figures are trusted renderer markup."""
    pairs = "".join(
        f"<div><dt>{escape(key)}</dt><dd>{escape(value)}</dd></div>" for key, value in metadata
    )
    technical = "".join(
        f"<dt>{escape(key)}</dt><dd>{escape(value)}</dd>"
        for key, value in [("FileGrail", __version__), *details]
    )
    return (
        '<header class="mast report-head" id="top">'
        '<div class="report-eyebrow">FileGrail <span>Evidence examination report</span></div>'
        f'<h1 class="report-title">{escape(title)}</h1>'
        f'<dl class="report-meta">{pairs}</dl>'
        f'<div class="report-scope"><span>Scope</span><b>{escape(target)}</b></div>'
        f"<details><summary>Report details</summary><dl>{technical}</dl></details>"
        f"{figures}</header>"
    )
