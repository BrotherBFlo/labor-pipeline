"""
update.py — the recurring entrypoint.

  python update.py            full cycle: pull -> files -> charts -> dashboard -> diff
  python update.py --verify   just resolve & verify FRED IDs (no files written)

Idempotent: re-pulls full series each run (so BLS benchmark/population-control
revisions flow through), rewrites data/ + charts/ + a dated dashboard in place,
and writes a "what moved since last run" summary.
"""
import sys
import json
import datetime as dt
from html import escape

import pandas as pd

import config
import fetch_fred
import fetch_indeed
import build_datasets
import charts


# ---------------------------------------------------------------------------
# "What moved since last run"
# ---------------------------------------------------------------------------
def _latest_values(datasets):
    """Last non-NaN value + date for every column across all frequency files."""
    snap = {}
    for freq, df in datasets.items():
        for col in df.columns:
            s = df[col].dropna()
            if s.empty:
                continue
            snap[col] = dict(value=float(s.iloc[-1]), date=str(s.index[-1].date()), freq=freq)
    return snap


def _diff_snapshot(new_snap):
    prev = {}
    if config.STATE_FILE.exists():
        try:
            prev = json.loads(config.STATE_FILE.read_text())
        except Exception:
            prev = {}
    lines, moved = [], []
    for col, cur in sorted(new_snap.items()):
        p = prev.get(col)
        if not p:
            lines.append(f"  + {col}: NEW — {cur['value']:.4g} ({cur['date']})")
            moved.append(col)
            continue
        if p["date"] != cur["date"] or abs(p["value"] - cur["value"]) > 1e-9:
            delta = cur["value"] - p["value"]
            arrow = "▲" if delta > 0 else ("▼" if delta < 0 else "•")
            lines.append(f"  {arrow} {col}: {p['value']:.4g} ({p['date']}) -> "
                         f"{cur['value']:.4g} ({cur['date']})  [{delta:+.4g}]")
            moved.append(col)
    config.STATE_FILE.write_text(json.dumps(new_snap, indent=2))
    return lines, moved


# ---------------------------------------------------------------------------
# Dashboard HTML
# ---------------------------------------------------------------------------
_CSS = """
:root{--ink:#1a2332;--muted:#667085;--line:#e4e7ec;--bg:#f7f8fa;--card:#fff;--accent:#1f4e79;}
*{box-sizing:border-box}body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;margin:0;background:var(--bg);color:var(--ink)}
header{background:linear-gradient(120deg,#1f4e79,#2e6da4);color:#fff;padding:28px 36px}
header h1{margin:0 0 4px;font-size:24px}header .sub{opacity:.9;font-size:13px}
.wrap{max-width:1180px;margin:0 auto;padding:24px 24px 80px}
.section{margin:34px 0 8px;font-size:13px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--accent);border-bottom:2px solid var(--line);padding-bottom:6px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px 6px;margin:16px 0;box-shadow:0 1px 3px rgba(16,24,40,.04)}
.note{font-size:12.5px;color:var(--muted);margin:2px 4px 12px}
.panel{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px 22px;margin:16px 0}
.panel h2{margin:0 0 10px;font-size:15px}
.caveat{background:#fff8e6;border:1px solid #f4d896;border-radius:12px;padding:16px 20px;margin:16px 0}
.caveat li{margin:6px 0;font-size:13px}
.moved{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12.5px;white-space:pre-wrap;line-height:1.55}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}
a{color:var(--accent)}.foot{color:var(--muted);font-size:12px;margin-top:40px;text-align:center}
@media(max-width:820px){.grid{grid-template-columns:1fr}}
"""


def _build_dashboard(chart_items, moved_lines, datasets, ts):
    by_section = {}
    for c in chart_items:
        by_section.setdefault(c["section"], []).append(c)

    parts = [f"<!doctype html><html><head><meta charset='utf-8'>",
             "<meta name='viewport' content='width=device-width,initial-scale=1'>",
             "<title>Hidden labor-market economics</title>",
             "<script src='https://cdn.plot.ly/plotly-2.35.2.min.js'></script>",
             f"<style>{_CSS}</style></head><body>"]
    parts.append(
        "<header><h1>U.S. labor-market — hidden economics</h1>"
        f"<div class='sub'>Triangulated gov vs independent · generated {escape(ts)} · "
        "window from " + config.OBSERVATION_START + "</div></header><div class='wrap'>")

    # bucket framework
    parts.append(
        "<div class='panel'><h2>The three populations the official taxonomy collapses</h2>"
        "<div class='grid'>"
        "<div><b>Bucket 1 — paid AND producing.</b> Active payroll attachment; white-collar cut "
        "(professional &amp; business services, information, financial activities).</div>"
        "<div><b>Bucket 2 — paid but NOT producing.</b> <i>Partly modeled / proxied</i> — business "
        "formation, self-employment, the U-6−U-3 wedge, quits. No clean national monthly severance series.</div>"
        "<div><b>Bucket 3 — truly unemployed without pay.</b> Unemployment level/rate, U-6, continued UI claims.</div>"
        "<div><b>Secondary axis — the expanding workforce.</b> Civilian labor force &amp; participation "
        "(the denominator). New-grad entry (NY Fed) is a quarterly overlay, annotated separately.</div>"
        "</div></div>")

    # what moved
    moved_html = escape("\n".join(moved_lines)) if moved_lines else "  (no prior snapshot — baseline established this run)"
    parts.append("<div class='panel'><h2>What moved since last run</h2>"
                 f"<div class='moved'>{moved_html}</div></div>")

    # charts by section
    section_order = ["Triangulation", "Bucket dashboard — flows", "White-collar lens",
                     "Bucket 2 — paid not producing", "Bucket 3 — unemployed",
                     "Secondary axis — denominator", "Thesis overlay"]
    ordered = [s for s in section_order if s in by_section] + \
              [s for s in by_section if s not in section_order]
    for section in ordered:
        parts.append(f"<div class='section'>{escape(section)}</div>")
        for c in by_section[section]:
            parts.append("<div class='card'>")
            parts.append(c["div"])
            parts.append(f"<div class='note'>{escape(c['note'])}</div></div>")

    # caveats
    parts.append("<div class='caveat'><b>Methodology &amp; caveats</b><ul>")
    for cav in config.CAVEATS:
        parts.append(f"<li>{escape(cav)}</li>")
    parts.append("</ul></div>")

    parts.append("<div class='panel'><h2>Data</h2>"
                 "<div class='note'>Frequency-partitioned files in <code>data/</code>: "
                 "monthly.csv · quarterly.csv · weekly.csv · daily.csv (+ tidy <code>*_long.csv</code>). "
                 "Column-level data dictionary in <code>data/sources.csv</code>; "
                 "FRED ID resolution log in <code>data/_resolution_log.json</code>.</div></div>")

    parts.append("<div class='foot'>BLS &amp; Census via FRED · ADP via FRED · "
                 "Indeed Hiring Lab (CC BY 4.0). Personal research dashboard.</div>")
    parts.append("</div></body></html>")
    return "".join(parts)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def run(verify_only=False):
    key = fetch_fred.load_api_key()

    if verify_only:
        fetch_fred._verify_only()
        return

    print("=" * 70)
    print(f"labor-pipeline update — {dt.datetime.now():%Y-%m-%d %H:%M}")
    print("=" * 70)

    print("\n[1/5] FRED pulls (resolve + observations)...")
    fred_frames, fred_meta, reso_log = fetch_fred.fetch_all(key)
    (config.DATA_DIR / "_resolution_log.json").write_text(json.dumps(reso_log, indent=2))

    print("\n[2/5] Indeed Hiring Lab pulls...")
    indeed = fetch_indeed.fetch_indeed_files()

    print("\n[3/5] Build datasets...")
    datasets = build_datasets.build(fred_frames, fred_meta, indeed)

    print("\n[4/5] Charts...")
    chart_items = charts.build_all(datasets)

    print("\n[5/5] Dashboard + 'what moved' diff...")
    snap = _latest_values(datasets)
    moved_lines, moved = _diff_snapshot(snap)

    ts_label = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    ts_file = dt.datetime.now().strftime("%Y-%m-%d_%H%M")
    html = _build_dashboard(chart_items, moved_lines, datasets, ts_label)
    dated = config.DASHBOARD_DIR / f"dashboard_{ts_file}.html"
    latest = config.DASHBOARD_DIR / "latest.html"
    dated.write_text(html)
    latest.write_text(html)

    # changelog append
    changelog = config.ROOT / "CHANGELOG.md"
    with changelog.open("a") as f:
        f.write(f"\n## {ts_label}\n")
        if moved_lines:
            f.write("\n".join(moved_lines) + "\n")
        else:
            f.write("  (baseline established)\n")

    print("\n" + "=" * 70)
    print(f"Done. {len(chart_items)} charts · {len(moved)} series moved.")
    print(f"Dashboard: {latest}")
    print(f"           {dated}")
    print("=" * 70)


if __name__ == "__main__":
    run(verify_only="--verify" in sys.argv)
