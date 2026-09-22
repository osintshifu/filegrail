"""The stylesheet of the HTML report, written into the page.

Kept apart from the renderer so the rules read as a stylesheet, and still
written inline: the report is one file that loads nothing.
"""

from __future__ import annotations

STYLE = """
:root{color-scheme:dark;
--bg:#0C0C0D;--surface:#141415;--surface-2:#1A1A1C;--line:#262628;--line-2:#353537;
--ink:#E6E8EB;--ink-2:#C3C8CE;--muted:#9AA1A9;--faint:#6B727B;
--accent:#7FB5A8;--accent-ink:#0C0C0D;--accent-soft:rgba(127,181,168,.14);
--brand:#5FA89A;--brand-soft:rgba(95,168,154,.14);
--origin:#5FA89A;--metadata:#A39BD9;--activity:#C9A66B;--alert:#D08770;
--alert-soft:rgba(208,135,112,.14);
--t-label:11px;--t-small:12px;--t-table:12.5px;--t-body:13.5px;--t-lead:15px;
--t-h2:21px;--t-num:28px;--track:.14em;
--g-file:#7FB5A8;--g-person:#C9A66B;--g-device:#A39BD9;--g-address:#6E9ED2;
--g-money:#C97B8F;--g-key:#7C93B5;--g-edge:#2A3A40;
--mono:"IBM Plex Mono","JetBrains Mono","SF Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,
"DejaVu Sans Mono",monospace;
--sans:"IBM Plex Sans",ui-sans-serif,system-ui,-apple-system,"Segoe UI","Noto Sans",
"Helvetica Neue",sans-serif;
--r:3px;--gutter:clamp(20px,4vw,64px);--nav:48px}
*{box-sizing:border-box}
*{scrollbar-width:thin;scrollbar-color:var(--line-2) transparent}
::-webkit-scrollbar{width:6px;height:6px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:var(--line-2);border-radius:3px}
::-webkit-scrollbar-thumb:hover{background:var(--faint)}
[hidden]{display:none!important}
html{scroll-padding-top:calc(var(--nav) + 24px);scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--ink);font:var(--t-body)/1.6 var(--mono);
font-variant-numeric:tabular-nums;-webkit-font-smoothing:antialiased;text-wrap:pretty}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline;text-underline-offset:3px}
code{font:inherit}
button{font:inherit;color:inherit;background:none;border:0;padding:0;cursor:pointer}
::selection{background:var(--accent);color:var(--accent-ink)}

/* ── masthead ─────────────────────────────────────────────── */
.mast{padding:22px var(--gutter) 24px;border-bottom:1px solid var(--line)}
.mast .word{margin:0 0 18px;font:500 var(--t-label)/1.4 var(--sans);letter-spacing:.2em;
text-transform:uppercase;color:var(--muted)}
.mast .word small{font-size:inherit;font-weight:400;color:var(--faint)}
.mast-body{display:grid;grid-template-columns:auto 1fr;gap:0 26px;align-items:stretch}
.mast-mark{display:flex;align-items:stretch}
.mast .mark{height:100%;max-height:112px;width:auto;flex:none}
.mast .tag{display:none}
.facts{display:grid;grid-template-columns:auto 1fr;gap:6px 24px;justify-content:start;margin:0;
font-size:var(--t-body);align-content:center}
.facts dt{font:500 var(--t-label)/1.5 var(--sans);letter-spacing:var(--track);
text-transform:uppercase;
color:var(--faint)}
.facts dd{margin:0;color:var(--ink);overflow-wrap:anywhere}
.mast-actions{display:none;gap:6px;align-items:center;margin-left:8px;flex:none}
.js .mast-actions{display:flex}
.btn{display:inline-flex;align-items:center;gap:8px;height:30px;padding:0 12px;
border:1px solid var(--line-2);border-radius:var(--r);color:var(--ink-2);
font:400 var(--t-small)/1 var(--sans);white-space:nowrap;background:var(--surface)}
.btn:hover{border-color:var(--accent);color:var(--ink)}
.btn.icon{width:30px;padding:0;justify-content:center}
.ic{width:14px;height:14px;fill:currentColor;flex:none;display:block}

/* ── sticky nav ───────────────────────────────────────────── */
.nav{position:sticky;top:0;z-index:20;height:var(--nav);padding:0 var(--gutter);
display:flex;align-items:center;gap:2px;overflow-x:auto;scrollbar-width:none;
background:color-mix(in srgb,var(--surface-2) 94%,transparent);backdrop-filter:blur(12px);
border-bottom:1px solid var(--line)}
.nav::-webkit-scrollbar{display:none}
.nav a{color:var(--muted);font:400 14px/1 var(--sans);padding:0 13px;height:var(--nav);
display:inline-flex;align-items:center;gap:7px;white-space:nowrap;
border-bottom:2px solid transparent;border-top:2px solid transparent}
.nav a b{font:400 13px/1 var(--mono);color:var(--faint)}
.nav a:hover{color:var(--ink);text-decoration:none}
.nav a.on{color:var(--ink);border-bottom-color:var(--accent)}
.nav a.on b{color:var(--accent)}
.nav .sp{flex:1}
.nav .home{display:none;padding:0 14px 0 0;border:0}
.js .nav.scrolled .home{display:inline-flex}
.nav .home .mark{width:16px;height:23px}
.search{position:relative;flex:none;display:none;margin-left:8px}
.js .search{display:block}
.search input{height:30px;width:30px;background:var(--surface);border:1px solid var(--line-2);
border-radius:var(--r);color:var(--ink);padding:0 0 0 30px;font:inherit;font-size:var(--t-small);
transition:width .18s ease,padding .18s ease;cursor:pointer}
.search input::placeholder{color:transparent}
.search input:focus,.search input:not(:placeholder-shown){width:250px;padding-right:30px;
cursor:text}
.search input:focus::placeholder{color:var(--faint)}
.search .ic{position:absolute;left:8px;top:8px;color:var(--muted);pointer-events:none}
.search:hover .ic,.search input:focus~.ic{color:var(--ink)}
.search input:focus{outline:none;border-color:var(--accent)}
.search kbd,.search .hits{display:none}
.search input:focus~kbd,.search input:not(:placeholder-shown)~.hits{display:block}
.search kbd{position:absolute;right:8px;top:7px;font-size:var(--t-label);color:var(--faint);
border:1px solid var(--line-2);border-radius:var(--r);padding:0 4px;line-height:14px}
.search .hits{position:absolute;right:34px;top:8px;font-size:var(--t-label);color:var(--accent)}

/* ── sections ─────────────────────────────────────────────── */
main{padding:0 var(--gutter) 80px;counter-reset:sec}
section{padding:56px 0 8px;counter-increment:sec}
main>section:first-child{padding-top:36px}
.h{display:flex;align-items:baseline;gap:14px;margin:0 0 22px;flex-wrap:wrap}
.js .h h2{cursor:pointer}
.fold{display:none;align-self:center;width:22px;height:22px;margin:0 -2px 0 -6px;
border-radius:var(--r);color:var(--faint);align-items:center;justify-content:center;flex:none}
.js .fold{display:inline-flex}
.fold:hover,.fold:focus-visible,.js .h:hover .fold{color:var(--accent);outline:none}
.fold .ic{width:14px;height:14px;transform:rotate(90deg);transition:transform .15s}
section.folded .fold .ic{transform:none}
section.folded .sec-body{display:none}
#detail .sec-body{overflow-x:auto}
section.folded .h{margin-bottom:0}
section.folded{padding-bottom:36px}
.h h2{margin:0;font:600 var(--t-h2)/1.25 var(--sans);letter-spacing:-.25px}
.h h2:before{content:counter(sec,decimal-leading-zero);color:var(--accent);
font:400 var(--t-label)/1 var(--mono);letter-spacing:var(--track);margin-right:13px;
vertical-align:3px}
.h .n{color:var(--accent);font-size:var(--t-small)}
.h .n b{font:400 var(--t-small)/1 var(--sans);color:var(--muted)}
h3{font:500 var(--t-label)/1.4 var(--sans);letter-spacing:var(--track);text-transform:uppercase;
color:var(--muted);margin:22px 0 8px}
p.note{color:var(--muted);font:400 var(--t-body)/1.6 var(--sans);margin:14px 0 0;max-width:78ch}

/* ── summary cards ────────────────────────────────────────── */
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(132px,1fr));gap:10px}
.card{--c:var(--line-2);background:var(--surface);border:1px solid var(--line);
border-top:2px solid var(--c);border-radius:var(--r);padding:16px 18px 15px;
display:flex;flex-direction:column;gap:4px;color:inherit;position:relative;min-width:0}
a.card:hover{background:var(--surface-2);border-color:var(--line-2);border-top-color:var(--c);
text-decoration:none}
.card .v{font-size:30px;line-height:1.05;font-weight:500;letter-spacing:-.7px;color:var(--ink)}
.card .v .of{color:var(--faint);font-size:var(--t-lead);letter-spacing:0}
.card .k{margin-top:3px;font:500 var(--t-label)/1.3 var(--sans);letter-spacing:var(--track);
text-transform:uppercase;color:var(--muted)}
.card .s{font:400 var(--t-small)/1.5 var(--sans);color:var(--muted);overflow-wrap:anywhere;
margin-top:4px;
display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.card.alert{--c:var(--alert)}
.card.accent{--c:var(--accent)}
.card.origin{--c:var(--origin)}
.card.metadata{--c:var(--metadata)}
.card.activity{--c:var(--activity)}
.card.alert .v,.card.accent .v,.card.origin .v,.card.metadata .v,.card.activity .v{color:var(--c)}
.legend{display:flex;gap:20px;flex-wrap:wrap;font:400 var(--t-small)/1.5 var(--sans);
color:var(--muted);margin:16px 0 0}

/* ── tables ───────────────────────────────────────────────── */
.tbl{width:100%;border-collapse:separate;border-spacing:0;font-size:var(--t-table)}
.tbl th{text-align:left;font:500 var(--t-label)/1.4 var(--sans);letter-spacing:var(--track);
text-transform:uppercase;color:var(--muted);padding:10px 14px 10px 0;
background:var(--surface);border-bottom:1px solid var(--line-2);white-space:nowrap;
user-select:none;position:sticky;top:0;z-index:1}
.tbl th:first-child,.tbl td:first-child{padding-left:14px}
.tbl th:last-child,.tbl td:last-child{padding-right:14px}
.tbl th[data-sort]{cursor:pointer}
.tbl th[data-sort]:hover,.tbl th[data-sort]:focus{color:var(--ink);outline:none}
.tbl th .dir{color:var(--accent);margin-left:4px;font-size:var(--t-label)}
.tbl td{padding:11px 14px 11px 0;border-bottom:1px solid var(--line);vertical-align:top;
color:var(--ink-2)}
.tbl tbody tr:last-child td{border-bottom:0}
.tbl tbody tr:hover td{background:var(--surface)}
.tbl td.num,.tbl th.num{text-align:right;white-space:nowrap}
.tbl th.num{letter-spacing:.04em}
.tbl .id{color:var(--faint);white-space:nowrap}
.tbl .pid,.rid{display:inline-flex;align-items:center;height:20px;padding:0 6px;
border:1px solid var(--accent);border-radius:var(--r);font-size:var(--t-label);
letter-spacing:.06em;color:var(--accent)}
.rid{height:18px;padding:0 5px;margin-right:2px;vertical-align:1px}
.rid:hover{text-decoration:none;background:var(--accent-soft)}
.rid.c{border-color:var(--alert);color:var(--alert)}
.rid.c:hover{background:var(--alert-soft)}
.tbl.pivots .kind{white-space:nowrap}
.tbl.pivots .kind i,.pill i{display:inline-block;width:8px;height:8px;border-radius:50%;
background:var(--g-key);margin-right:8px;vertical-align:1px}
.pill i{width:7px;height:7px;margin-right:6px;vertical-align:0}
.tbl.pivots .kind i.f-file,.pill i.f-file{background:var(--g-file)}
.tbl.pivots .kind i.f-person,.pill i.f-person{background:var(--g-person)}
.tbl.pivots .kind i.f-device,.pill i.f-device{background:var(--g-device)}
.tbl.pivots .kind i.f-address,.pill i.f-address{background:var(--g-address)}
.tbl.pivots .kind i.f-money,.pill i.f-money{background:var(--g-money)}
.rel-node a .ref{color:var(--accent)}
.tbl .corpus{white-space:nowrap}
.pill.corpus.both{border-color:var(--accent);color:var(--accent)}
.tbl .path{color:var(--ink);overflow-wrap:anywhere;min-width:18em}
.tbl .val{color:var(--ink);overflow-wrap:anywhere;min-width:16em;max-width:26em}
.tbl .dim{color:var(--muted)}
.tbl .where{color:var(--muted);overflow-wrap:break-word;min-width:26em}
.tbl .found{max-width:22em}
.tbl details{margin-top:4px}
.tbl summary{cursor:pointer;color:var(--accent)}
.tbl tr[hidden]{display:none}
.tbl tr.hit td{background:var(--accent-soft)}
.wrap{overflow-x:auto;border:1px solid var(--line);border-radius:var(--r);
background:var(--bg)}
.table-block{position:relative}
.table-actions{display:none;position:absolute;top:5px;right:6px;z-index:2}
.js .table-actions{display:block}
.js .table-block>.wrap>.tbl th:last-child{padding-right:44px}
.table-copy{width:26px;height:26px;border:0;color:var(--faint);background:transparent}
.table-copy:hover{color:var(--accent)}
.table-copy .ic{width:13px;height:13px}
.vh{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);
white-space:nowrap}
.table-copy.ok{color:var(--accent)}
.table-copy.no{color:var(--alert)}
.wrap>table.index,.wrap>table.pivots{min-width:860px}
.wrap>table.relationships{min-width:940px}

/* ── timeline ── */
.tl-chips{align-items:center}
.tl-chips .chip i{width:8px;height:8px;border-radius:50%;flex:none}
.tl-chips .chip i.f-origin{background:var(--origin)}
.tl-chips .chip i.f-metadata{background:var(--metadata)}
.tl-chips .chip i.f-activity{background:var(--activity)}
.tl-shown{margin-left:auto;color:var(--muted);font:400 var(--t-small)/1 var(--sans)}
.tl{list-style:none;margin:0;padding:0;--spine:calc(5.6em + 12px + 10px)}
.tl .tl-day{position:sticky;top:var(--nav);z-index:2;display:flex;align-items:baseline;gap:10px;
padding:16px 0 8px;background:var(--bg);color:var(--ink)}
.tl .tl-day time{font:500 var(--t-table)/1.4 var(--mono);letter-spacing:.02em}
.tl .tl-day .wd{color:var(--faint);font:400 var(--t-small)/1.4 var(--sans)}
.tl .tl-day:after{content:"";flex:1;border-top:1px solid var(--line-2);align-self:center}
.tl .ev{--c:var(--faint);position:relative;display:grid;
grid-template-columns:5.6em 22px 6.4em minmax(0,1fr);gap:0 12px;align-items:start;
padding:7px 0;font-size:var(--t-table)}
.tl .ev[data-f=origin]{--c:var(--origin)}
.tl .ev[data-f=metadata]{--c:var(--metadata)}
.tl .ev[data-f=activity]{--c:var(--activity)}
.tl .ev:hover{background:linear-gradient(90deg,transparent var(--spine),
var(--surface) var(--spine))}
.tl .ev time{color:var(--muted);font-variant-numeric:tabular-nums;white-space:nowrap;
line-height:1.6}
.tl .node{position:relative;align-self:stretch;min-height:1.6em}
.tl .node:before{content:"";position:absolute;left:10px;top:-7px;bottom:-7px;width:2px;
background:var(--line-2)}
.tl .tl-day+.ev .node:before{top:.5em}
.tl .ev:last-child .node:before,.tl .ev:has(+.tl-day) .node:before,
.tl .ev:has(+.tl-gap) .node:before{bottom:auto;height:calc(.5em + 7px)}
.tl .node:after{content:"";position:absolute;left:6px;top:.45em;width:10px;height:10px;
border-radius:50%;background:var(--c);box-shadow:0 0 0 3px var(--bg)}
.tl .ev:hover .node:after{box-shadow:0 0 0 3px var(--bg),0 0 0 6px color-mix(in srgb,
var(--c) 30%,transparent)}
.tl .verb{display:inline-block;justify-self:start;margin-top:1px;padding:1px 7px;
border-radius:var(--r);font:500 var(--t-label)/1.5 var(--sans);letter-spacing:.06em;
text-transform:uppercase;white-space:nowrap;color:var(--c);
background:color-mix(in srgb,var(--c) 14%,transparent)}
.tl .txt{display:flex;flex-wrap:wrap;gap:2px 14px;align-items:baseline;line-height:1.6;min-width:0}
.tl .txt a{color:var(--ink);overflow-wrap:anywhere}
.tl .src{color:var(--ink-2)}
.tl .src .pill{margin-left:6px}
.tl .detail{color:var(--muted);flex:1 1 22em;min-width:0;overflow-wrap:anywhere}
.tl .tl-gap{position:relative;padding:10px 0 10px calc(var(--spine) + 24px);
color:var(--faint);font:400 var(--t-small)/1.4 var(--sans)}
.tl .tl-gap:before{content:"";position:absolute;left:var(--spine);top:0;bottom:0;
border-left:2px dashed var(--line-2)}
.tl .tl-gap span:before{content:"";display:inline-block;width:14px;
border-top:1px dashed var(--line-2);
margin:0 8px 4px 0}
.tl.filtered .tl-gap{display:none}

/* ── graph ── */
.graph-panel{--field:#09090A;margin:0 0 22px;border:1px solid var(--line);border-radius:var(--r);
background:var(--field);overflow:hidden}
.graph-toolbar{display:grid;grid-template-columns:1fr auto;gap:12px 16px;align-items:end;
padding:12px 14px;background:var(--surface-2);border-bottom:1px solid var(--line)}
.graph-toolbar .rel-controls select,.graph-toolbar .rel-controls input,
.graph-toolbar .graph-arrange select,.graph-toolbar .graph-arrange .range,
.graph-toolbar .btn{background:var(--field);border-color:var(--line-2)}
.graph-toolbar .btn:hover,.graph-toolbar .rel-controls select:hover,
.graph-toolbar .rel-controls select:focus,.graph-toolbar .rel-controls input:focus,
.graph-toolbar .graph-arrange select:hover,.graph-toolbar .graph-arrange select:focus{
border-color:var(--accent)}
.graph-toolbar .rel-controls{grid-column:1/-1}
.graph-arrange{display:flex;align-items:end;gap:12px;flex-wrap:wrap}
.graph-arrange label{display:grid;gap:5px;color:var(--muted);
font:500 var(--t-label)/1.4 var(--sans);letter-spacing:var(--track);text-transform:uppercase}
.graph-arrange select{height:34px;padding:0 34px 0 10px;border:1px solid var(--line-2);
border-radius:var(--r);background:var(--surface);color:var(--ink);
font:var(--t-table)/1.4 var(--mono)}
.graph-arrange select:hover,.graph-arrange select:focus{border-color:var(--accent);outline:none}
.graph-arrange .range{display:inline-flex;align-items:center;gap:10px;height:34px;padding:0 10px;
border:1px solid var(--line-2);border-radius:var(--r);background:var(--surface)}
.graph-arrange input[type=range]{width:120px;margin:0;accent-color:var(--accent)}
.graph-arrange output{min-width:3.2em;text-align:right;color:var(--muted);
font:var(--t-table)/1 var(--mono);letter-spacing:0;text-transform:none}
.graph-tools{display:flex;align-items:center;gap:6px;flex:none}
.graph-tools .btn{height:34px}
.graph-tools .btn.icon{width:34px}
.graph-tools output{min-width:44px;text-align:center;color:var(--muted);
font-size:var(--t-small)}
.graph-filterbar{display:flex;align-items:center;gap:12px;padding:12px 14px 0;flex-wrap:wrap}
.graph-filterbar .rel-kinds{margin:0}
.graph{margin:0;padding:6px 0 0}
.graph-canvas{position:relative}
.graph-panel.full{position:fixed;inset:0;z-index:40;margin:0;border:0;border-radius:0;
display:flex;flex-direction:column;background:var(--field);overflow:auto}
.graph-panel.full .graph{flex:1;display:flex;flex-direction:column;min-height:0}
.graph-panel.full .graph-canvas{flex:1;min-height:0}
.graph-panel.full .graph-canvas>svg{height:100%;min-height:360px}
.graph-panel:fullscreen{background:var(--field)}
body.graph-full{overflow:hidden}
#graph-full .ic.out,#graph-full[aria-pressed=true] .ic.in{display:none}
#graph-full[aria-pressed=true] .ic.out{display:block}
.graph-canvas>svg{display:block;width:100%;height:clamp(360px,52vw,620px);border:0;
background:radial-gradient(circle,#1F1F21 1px,transparent 1.5px) 0 0/24px 24px,
radial-gradient(ellipse 70% 60% at 50% 42%,#161617 0%,#0E0E0F 45%,#0A0A0B 80%,var(--field) 100%);
touch-action:none;cursor:grab;user-select:none}
.graph-canvas>svg.dragging{cursor:grabbing}
.graph .graph-viewport{transform-origin:0 0}
.graph .e{stroke:var(--g-edge);stroke-width:1;stroke-opacity:.9;transition:stroke-opacity .15s}
.graph .node{--c:var(--g-key);transition:opacity .15s}
.graph .f-file{--c:var(--g-file)}
.graph .f-person{--c:var(--g-person)}
.graph .f-device{--c:var(--g-device)}
.graph .f-address{--c:var(--g-address)}
.graph .f-money{--c:var(--g-money)}
.graph .node circle{fill:var(--c);stroke:var(--bg);stroke-width:1.5}
.graph .node .halo{fill:var(--c);stroke:none;opacity:.14;transition:opacity .15s}
.graph .node:hover .halo,.graph .node:focus .halo,.graph .node.on .halo{opacity:.38}
.graph text.aux{display:none}
.graph[data-labels=all] text.aux{display:block}
.graph[data-labels=none] text{display:none}
.graph text{font:10.5px var(--mono);fill:var(--ink-2);text-anchor:middle;pointer-events:none;
paint-order:stroke;stroke:var(--surface);stroke-width:3px;stroke-linejoin:round}
.js .graph .node{cursor:pointer}
.graph .node:focus{outline:none}
.graph .node:hover circle:not(.halo),.graph .node:focus circle:not(.halo),
.graph .node.on circle:not(.halo){stroke:var(--ink);stroke-width:2}
.graph.focused .node:not(.on):not(.near){opacity:.14}
.graph.focused .e{stroke-opacity:.1}
.graph.focused .e.on{stroke:var(--accent);stroke-opacity:1;stroke-width:1.5}
.graph.kinded .node:not(.kind-near){opacity:.15}
.graph.kinded .e:not(.kind-on){stroke-opacity:.06}
.graph.kinded .e.kind-on{stroke:var(--accent);stroke-opacity:.9;stroke-width:1.3}
.graph.kinded .node.kind-near .halo{opacity:.3}
.graph figcaption{margin:6px 0 0;padding:9px 14px;border-top:1px solid var(--line);
background:var(--surface-2);color:var(--muted);font:400 var(--t-small)/1.4 var(--sans)}
.graph-detail{--c:var(--g-key);position:absolute;top:12px;right:12px;
width:min(380px,calc(100% - 24px));max-height:calc(100% - 24px);overflow:auto;
scrollbar-gutter:stable;
padding:0 0 4px;background:color-mix(in srgb,var(--surface) 96%,transparent);
backdrop-filter:blur(10px);border:1px solid var(--line-2);border-top:2px solid var(--c);
border-radius:4px;box-shadow:0 16px 40px rgba(0,0,0,.4);font-size:var(--t-small)}
.graph-detail[data-family=file]{--c:var(--g-file)}
.graph-detail[data-family=person]{--c:var(--g-person)}
.graph-detail[data-family=device]{--c:var(--g-device)}
.graph-detail[data-family=address]{--c:var(--g-address)}
.graph-detail[data-family=money]{--c:var(--g-money)}
.graph-detail-head{display:flex;align-items:center;gap:8px;padding:12px 10px 0 18px;
color:var(--muted);font:500 var(--t-label)/1.4 var(--sans);letter-spacing:var(--track);
text-transform:uppercase}
.graph-detail-head:before{content:"";width:8px;height:8px;border-radius:50%;background:var(--c);
flex:none}
.graph-detail-head button{margin-left:auto;width:26px;height:26px;border-radius:var(--r);
color:var(--faint);font:400 16px/1 var(--sans)}
.graph-detail-head button:hover,.graph-detail-head button:focus-visible{color:var(--ink);
background:var(--surface-2);outline:none}
.graph-detail>strong{display:block;margin:6px 18px 12px;color:var(--ink);overflow-wrap:anywhere;
font:500 var(--t-body)/1.45 var(--mono)}
.graph-detail dl{display:grid;gap:0;margin:0 18px 14px}
.graph-detail dl>div{display:grid;grid-template-columns:88px 1fr;gap:12px;padding:6px 0;
border-top:1px solid var(--line)}
.graph-detail dt{font-family:var(--sans);color:var(--faint)}
.graph-detail dd{margin:0;color:var(--ink-2);overflow-wrap:anywhere}
.graph-detail h4{margin:0 18px 4px;font:500 var(--t-label)/1.4 var(--sans);
letter-spacing:var(--track);text-transform:uppercase;color:var(--faint)}
.graph-detail ul{list-style:none;margin:0 18px 14px;padding:0}
.graph-detail li{display:grid;grid-template-columns:minmax(0,max-content) max-content
minmax(0,1fr) 22px;
gap:8px 10px;padding:6px 0;border-top:1px solid var(--line);align-items:start}
.graph-detail li .kind{font-family:var(--sans);color:var(--faint);white-space:nowrap}
.graph-detail li .rel-node{display:contents}
.graph-detail li .rel-node .pill{margin-top:1px}
.graph-detail li .rel-node a,.graph-detail li .rel-node .v{min-width:0;overflow-wrap:anywhere}
.graph-detail li .rel-node .copy{display:none}
.graph-detail li .rel-focus{margin:0;justify-self:end}
.graph-detail-actions{display:flex;gap:8px;flex-wrap:wrap;padding:0 18px 12px}
.to-top{position:fixed;right:20px;bottom:20px;z-index:20;width:36px;height:36px;
box-shadow:0 6px 18px rgba(0,0,0,.28)}
.relationship-bar{display:flex;align-items:center;gap:14px;flex-wrap:wrap;margin:6px 0 14px}
.relationship-bar h3{margin:0;flex:none}

/* ── relationships ────────────────────────────────────────── */
.rel-controls{display:flex;align-items:end;gap:12px;flex:1;flex-wrap:wrap;margin:0}
.rel-controls label{display:grid;gap:5px;flex:2 1 24em;min-width:0;color:var(--muted);
font:500 var(--t-label)/1.4 var(--sans);letter-spacing:var(--track);text-transform:uppercase}
.rel-controls select,.rel-controls input{width:100%;height:34px;padding:0 10px;
border:1px solid var(--line-2);border-radius:var(--r);background:var(--surface);
color:var(--ink);font:var(--t-table)/1.4 var(--mono)}
.rel-controls select{padding-right:34px}
.rel-controls select:hover,.rel-controls select:focus,.rel-controls input:focus{
border-color:var(--accent);outline:none}
.rel-find{display:none}
.js .rel-find{display:grid;flex:1 1 16em}
.rel-kinds{display:none;flex-wrap:wrap;gap:6px;margin:0 0 16px}
.js .rel-kinds{display:flex}
.rel-kinds .chip i{width:8px;height:8px;border-radius:50%;background:var(--g-key);flex:none}
.rel-kinds .chip i.f-file{background:var(--g-file)}
.rel-kinds .chip i.f-person{background:var(--g-person)}
.rel-kinds .chip i.f-device{background:var(--g-device)}
.rel-kinds .chip i.f-address{background:var(--g-address)}
.rel-kinds .chip i.f-money{background:var(--g-money)}
.rel-node{display:flex;align-items:flex-start;gap:8px;min-width:15em}
.rel-node .pill{margin-top:1px}
.rel-node a,.rel-node .v{overflow-wrap:anywhere}
.rel-focus{display:none;align-items:center;justify-content:center;flex:none;width:22px;
height:22px;border:1px solid var(--line-2);border-radius:var(--r);color:var(--faint);
margin-left:2px}
.rel-focus .ic{width:12px;height:12px}
.js .rel-focus{display:inline-flex}
.rel-focus:hover,.rel-focus:focus{color:var(--accent);border-color:var(--accent);outline:none}
.relationship .arrow{color:var(--faint);text-align:center;padding-top:12px}
.relationship .arrow .ic{display:inline-block}
.relationship .kind{color:var(--ink);min-width:13em}
.relationship .kind .dim{display:block;margin-top:2px}
.relationship details{min-width:18em}
.rel-proof{padding:8px 0;border-bottom:1px solid var(--line)}
.rel-proof:last-child{border-bottom:0}
.rel-proof.derived{border-left:2px solid var(--line);padding-left:10px}
.rel-derived{display:inline-block;margin-bottom:6px;font-size:var(--t-small);letter-spacing:.04em;text-transform:uppercase;color:var(--muted)}
.rel-proof .fields{grid-template-columns:minmax(80px,max-content) 1fr;margin-top:0}
.relationship-table-tools{display:none;flex:1;align-items:center;gap:10px;flex-wrap:wrap}
.relationship-table-tools .btn{height:34px}
.js .relationship-table-tools{display:flex}
.relationship-table-tools label{display:grid}
.relationship-table-tools label:first-child{flex:1;min-width:min(100%,18em)}
.relationship-table-tools input,.relationship-table-tools select{height:34px;padding:0 10px;
border:1px solid var(--line-2);border-radius:var(--r);background:var(--surface);color:var(--ink);
font:var(--t-table)/1.4 var(--mono)}
.relationship-table-tools input:focus,.relationship-table-tools select:focus{outline:none;
border-color:var(--accent)}

/* ── marks ────────────────────────────────────────────────── */
.cat{display:inline-flex;align-items:center;gap:6px;font:400 var(--t-small)/1.5 var(--sans);
letter-spacing:.02em;color:var(--ink-2);white-space:nowrap}
.cat:before{content:"";width:8px;height:8px;border-radius:2px;background:var(--c,var(--faint));
flex:none}
.cat.origin{--c:var(--origin)}
.cat.metadata{--c:var(--metadata)}
.cat.activity{--c:var(--activity)}
.cat.none{--c:transparent;color:var(--faint)}
.cat.none:before{box-shadow:inset 0 0 0 1px var(--line-2)}
.dots{display:inline-flex;gap:4px;vertical-align:middle}
.dots i{width:8px;height:8px;border-radius:2px;background:var(--line-2)}
.dots i.o{background:var(--origin)}
.dots i.m{background:var(--metadata)}
.dots i.a{background:var(--activity)}
.flag{display:inline-flex;align-items:center;justify-content:center;width:18px;height:18px;
border-radius:var(--r);background:var(--alert-soft);color:var(--alert);font-weight:500}
.pill{display:inline-block;font-size:var(--t-label);letter-spacing:.06em;padding:1px 7px;
border-radius:var(--r);border:1px solid var(--line-2);color:var(--muted);white-space:nowrap}
.pill.match{border-color:transparent;background:var(--surface-2);color:var(--ink-2)}
.pill.strong{border-color:var(--accent);background:none;color:var(--accent)}
.chips{display:none;flex-wrap:wrap;gap:6px;margin:0 0 16px}
.js .chips{display:flex}
.chip{height:28px;padding:0 11px;border:1px solid var(--line-2);border-radius:var(--r);
font:400 var(--t-small)/1 var(--sans);color:var(--muted);display:inline-flex;
align-items:center;gap:6px}
.chip b{font:400 var(--t-small)/1 var(--mono);color:var(--faint)}
.chip:hover{color:var(--ink);border-color:var(--ink-2)}
.chip.on{background:var(--accent);border-color:var(--accent);color:var(--accent-ink)}
.chip.on b{color:var(--accent-ink);opacity:.7}
.copy{display:none;color:var(--faint);margin-left:6px;vertical-align:-3px;opacity:0}
.js .copy{display:inline-flex}
.copy .ic{width:13px;height:13px}
.copy .ic.ok,.copy .ic.no{display:none}
.copy.ok .ic,.copy.no .ic{display:none}
.copy.ok .ic.ok{display:block;color:var(--accent)}
.copy.no .ic.no{display:block;color:var(--alert)}
tr:hover .copy,.rec:hover .copy,dd:hover .copy,.pair:hover .copy,.facts dd:hover .copy{opacity:1}
.copy:hover,.copy:focus{color:var(--accent);opacity:1;outline:none}
.copy.ok,.copy.no{opacity:1}

/* ── findings ─────────────────────────────────────────────── */
.findings{border-top:1px solid var(--line)}
.find{display:grid;grid-template-columns:56px 1fr;gap:0 18px;padding:20px 0 20px 14px;
border-bottom:1px solid var(--line);position:relative}
.find.warn:before{content:"";position:absolute;left:0;top:20px;bottom:20px;width:2px;
background:var(--alert);border-radius:1px}
.find:target{background:linear-gradient(90deg,var(--accent-soft),transparent 70%)}
.find .fid{display:inline-flex;align-items:center;height:22px;padding:0 7px;
border:1px solid var(--accent);border-radius:var(--r);font-size:var(--t-label);
letter-spacing:.06em;color:var(--accent)}
.find .fid:hover{text-decoration:none;background:var(--accent-soft)}
.find.warn .fid{border-color:var(--alert);color:var(--alert)}
.find.warn .fid:hover{background:var(--alert-soft)}
.find .head{display:flex;align-items:baseline;gap:6px 14px;flex-wrap:wrap}
.find .t{color:var(--ink);font:400 var(--t-lead)/1.5 var(--sans);overflow-wrap:anywhere}
.find .kind{color:var(--faint);font:500 var(--t-label)/1.4 var(--sans);
letter-spacing:var(--track);text-transform:uppercase;white-space:nowrap}
.find .fields{margin-top:10px;font-size:var(--t-table)}
.find .files{margin-top:12px;display:flex;flex-wrap:wrap;gap:6px;font-size:var(--t-small)}
.find .files a{display:inline-flex;align-items:center;gap:6px;height:24px;padding:0 9px;
border:1px solid var(--line);border-radius:var(--r);color:var(--ink);background:var(--surface)}
.find .files a .ref{color:var(--accent)}
.find.warn .files a .ref{color:var(--alert)}
.find .files a:hover{border-color:var(--accent);text-decoration:none}
.find .files+.fields{margin-top:8px;padding-bottom:6px}
.find details .files{margin-top:8px}
.find .note{color:var(--muted);font:400 var(--t-body)/1.6 var(--sans);margin-top:8px;max-width:78ch}
.find details{margin-top:8px}
.find summary{color:var(--accent);font-size:var(--t-table);cursor:pointer}

/* ── pivots ───────────────────────────────────────────────── */
.tabs{display:none;flex-wrap:wrap;gap:2px 0;border-bottom:1px solid var(--line-2);
margin-bottom:16px}
.js .tabs{display:flex}
.tabs button{padding:9px 12px;font:400 13px/1 var(--sans);color:var(--muted);
border-bottom:2px solid transparent;margin-bottom:-1px;white-space:nowrap}
.tabs button b{font:400 var(--t-small)/1 var(--mono);color:var(--faint);margin-left:6px}
.tabs button:hover{color:var(--ink)}
.tabs button.on{color:var(--ink);border-bottom-color:var(--accent)}
.tabs button.on b{color:var(--accent)}
.js .pane{display:none}
.js .pane.on{display:block}
.pane:before{content:attr(data-label);display:none;font:500 var(--t-label)/1.4 var(--sans);
letter-spacing:var(--track);
text-transform:uppercase;color:var(--muted);margin:14px 0 6px}
.holder{display:block;white-space:nowrap}

/* ── file detail ──────────────────────────────────────────── */
.file{border:1px solid var(--line);border-radius:var(--r);margin:0 0 12px;background:var(--surface)}
.file>summary{list-style:none;display:grid;grid-template-columns:52px 1fr auto;gap:16px;
align-items:center;padding:13px 18px;cursor:pointer}
.file>summary::-webkit-details-marker{display:none}
.file>summary .id{color:var(--muted)}
.file>summary .name{color:var(--ink);overflow-wrap:anywhere;font-size:var(--t-body)}
.file>summary .meta{color:var(--faint);font-size:var(--t-small);display:flex;gap:12px;
align-items:center;
flex-wrap:wrap}
.file>summary .chev{width:14px;height:14px;fill:currentColor;color:var(--faint);
transition:transform .15s}
.file[open]>summary .chev{transform:rotate(90deg)}
.file[open]>summary{border-bottom:1px solid var(--line)}
.file.review{border-left:2px solid var(--alert)}
.rec{display:grid;grid-template-columns:96px 1fr;gap:0 20px;padding:14px 18px;
border-bottom:1px solid var(--line)}
.rec>.fields{grid-column:2}
.rec:last-child{border-bottom:0}
.rec .cat{align-self:start;margin-top:2px}
.rec .src{color:var(--ink);display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.rec .note{color:var(--muted);margin-top:3px}
.rec.silent,.rec.silent .src{color:var(--faint)}
.fields{display:grid;grid-template-columns:minmax(120px,max-content) 1fr;gap:3px 18px;
margin:8px 0 0;font-size:var(--t-table)}
.fields dt{font-family:var(--sans);color:var(--muted);white-space:nowrap}
.fields dd{margin:0;color:var(--ink-2);overflow-wrap:anywhere}
.fields .sub{display:grid;grid-template-columns:minmax(80px,max-content) 1fr;gap:2px 12px;
margin:0;padding:4px 0 4px 10px;border-left:1px solid var(--line)}
.fields ol.numbered{margin:0;padding:0 0 0 1.6em;display:grid;gap:2px}
.extra{display:grid;grid-template-columns:96px 1fr;gap:0 20px;padding:12px 18px;
border-top:1px dashed var(--line);font-size:var(--t-table)}
.extra .k{color:var(--muted);font:500 var(--t-label)/1.4 var(--sans);letter-spacing:var(--track);
text-transform:uppercase;padding-top:2px}
.extra ul{margin:0;padding:0;list-style:none;display:grid;gap:4px}
.extra li{color:var(--ink-2);overflow-wrap:anywhere}

/* ── conflicts ────────────────────────────────────────────── */
.conf{display:grid;grid-template-columns:56px 1fr;gap:0 16px;padding:18px 0;
border-bottom:1px solid var(--line)}
.conf:last-child{border-bottom:0}
.conf .cid{display:inline-flex;align-items:center;height:22px;padding:0 7px;
border:1px solid var(--alert);border-radius:var(--r);font-size:var(--t-label);color:var(--alert)}
.conf .cid:hover{text-decoration:none;background:var(--alert-soft)}
.conf .t{color:var(--ink);font:400 var(--t-lead)/1.5 var(--sans);overflow-wrap:anywhere}
.conf .t a{color:var(--ink)}
.conf .t a .ref{color:var(--alert)}
.conf .field{color:var(--muted);font:500 var(--t-label)/1.4 var(--sans);letter-spacing:var(--track);
text-transform:uppercase;margin:16px 0 0}
.conf .pair{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,18em),1fr));
gap:1px;background:var(--line);border:1px solid var(--line);border-radius:var(--r);
overflow:hidden;margin-top:6px;font-size:var(--t-table)}
.conf .pair>div{background:var(--surface);padding:10px 14px;min-width:0}
.conf .pair .src{color:var(--muted);font:500 var(--t-label)/1.4 var(--sans);
letter-spacing:var(--track);
text-transform:uppercase;margin-bottom:4px}
.conf .pair .v{color:var(--ink);overflow-wrap:anywhere}
.conf .delta{margin-top:8px;color:var(--alert);font-size:var(--t-table)}
.conf .delta:before{content:"\u0394";margin-right:8px;color:var(--faint)}

footer{padding:24px var(--gutter);border-top:1px solid var(--line);display:flex;
justify-content:space-between;flex-wrap:wrap;gap:10px;font:500 var(--t-label)/1.5 var(--sans);
letter-spacing:var(--track);text-transform:uppercase;color:var(--faint)}

/* ── narrow ───────────────────────────────────────────────── */
@media (max-width:920px){
.facts{gap:4px 16px}
}
@media (max-width:820px){
.mast-body{grid-template-columns:1fr;gap:14px 0}
.mast-mark{align-items:start}
.mast .mark{height:64px;max-height:64px}
.facts{grid-template-columns:1fr;gap:2px 0}
.facts dt{margin-top:8px}
.facts dt:first-child{margin-top:0}
.rec{grid-template-columns:1fr}
.rec .cat{margin-bottom:4px}
.rec>.fields{grid-column:1}
.extra{grid-template-columns:1fr}
.search input:focus,.search input:not(:placeholder-shown){width:150px}
.rel-controls{display:grid;grid-template-columns:1fr}
.rel-controls label{min-width:0}
.graph-toolbar{grid-template-columns:1fr}
.graph-tools{justify-content:flex-end}
.graph-canvas>svg{height:420px}
.graph-panel.full .graph-canvas>svg{height:100%}
.graph-detail{position:absolute;width:calc(100% - 24px)}
.relationship-bar{flex-direction:column;align-items:stretch}
.find,.conf{grid-template-columns:1fr;gap:6px 0}
.find{padding:14px 0 14px 12px}
.tl .ev{grid-template-columns:5.6em 22px minmax(0,1fr);row-gap:4px}
.tl .ev .txt{grid-column:3}
}
/* ── print: paper, flat, everything open ──────────────────── */
@media print{
:root{color-scheme:light;--bg:#fff;--surface:#fff;--surface-2:#f2f3f5;--line:#d5d8dd;
--line-2:#b8bcc3;--ink:#000;--ink-2:#222;--muted:#555;--faint:#777;--accent:#3E7F6E;
--brand:#3E7F6E;--brand-soft:rgba(62,127,110,.14);
--origin:#2F8677;--metadata:#5F58AD;--activity:#8E6E2E;--alert:#B5563A}
@page{margin:14mm}
body{font-size:11px}
.nav,.mast-actions,.copy,.chips,.tabs,.chev,.btn,.search,.to-top,.fold{display:none!important}
.tl .tl-day{position:static}
section.folded .sec-body{display:block}
.graph-canvas>svg{background:none}
.rel-controls,.rel-kinds,.rel-focus,.graph-arrange{display:none!important}
.graph-toolbar,.table-actions,.relationship-table-tools{display:none!important}
.mast{padding-top:0}
summary{cursor:default;list-style:none}
summary::-webkit-details-marker{display:none}
details:not([open])>:not(summary){display:block}
.js .pane,.pane{display:block!important}
.pane:before{display:block}
section{padding:22px 0 6px}
.h{break-after:avoid}
.file,.conf,.find,.card,tr,.rec{break-inside:avoid}
thead{display:table-header-group}
a{color:inherit}
.wrap{overflow:visible;border:0;background:none}
.findings{border:0}
.tbl th{position:static;background:none}
.graph-panel{border:0;background:transparent}
.graph{padding:0}
.graph-canvas>svg{height:auto;max-height:none}
.graph.focused .node,.graph.focused .e{opacity:1;stroke-opacity:.9}
.wrap>table.index,.wrap>table.pivots,.wrap>table.relationships{min-width:0}
.tbl th,.tbl td{white-space:normal}
.tbl .path,.tbl .val,.tbl .where,.tbl .found{min-width:0;max-width:none}
.rel-node,.relationship .kind,.relationship details{min-width:0}
.tbl.relationships thead{display:none}
.tbl.relationships tr{display:grid;grid-template-columns:1fr auto 1fr 1fr;gap:4px 10px;
padding:6px 0;border-bottom:1px solid var(--line)}
.tbl.relationships td{display:block;border:0;padding:0}
.tbl.relationships td:last-child{grid-column:1/-1}
.tbl.relationships summary{display:none}
}
"""
