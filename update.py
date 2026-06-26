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
import fetch_nyfed
import build_datasets
import charts


# ---------------------------------------------------------------------------
# "What moved since last run"
# ---------------------------------------------------------------------------
def _latest_values(datasets):
    """Last non-NaN value + date for every column across all frequency files."""
    snap = {}
    for freq, df in datasets.items():
        if not isinstance(df, pd.DataFrame):  # skip geo_focus dict etc.
            continue
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
table.calc{width:100%;border-collapse:collapse;margin:8px 0;font-size:12.5px}
table.calc th{text-align:left;color:var(--muted);font-weight:600;border-bottom:2px solid var(--line);padding:6px 10px}
table.calc td{vertical-align:top;border-bottom:1px solid var(--line);padding:8px 10px}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11.5px;color:#33415c}
.calcnote{font-size:11.5px;color:var(--muted);margin-top:3px}
.mfilter{position:relative;display:inline-block;margin:2px 2px 10px}
.mbtn,.tglbtn{font-size:12px;padding:5px 11px;border:1px solid var(--line);background:#fff;border-radius:7px;cursor:pointer;color:var(--ink)}
.mbtn:hover,.tglbtn:hover{border-color:var(--accent)}
.tglbtn{margin:2px 2px 10px 4px;font-weight:600}
.tglbtn[hidden]{display:none}
.mfilter .mpanel{display:none;position:absolute;z-index:50;top:32px;left:0;background:#fff;border:1px solid var(--line);border-radius:9px;box-shadow:0 6px 18px rgba(16,24,40,.14);padding:8px 10px;width:230px;max-height:330px;overflow:auto}
.mfilter.open .mpanel{display:block}
.mpanel-act{display:flex;gap:12px;margin-bottom:6px;border-bottom:1px solid var(--line);padding-bottom:6px;position:sticky;top:0;background:#fff}
.mpanel-act a{cursor:pointer;font-size:12px;color:var(--accent);font-weight:600}
.mlist .trow{display:flex;align-items:center;gap:5px;padding:2px 0;font-size:12px;white-space:nowrap}
.mlist .trow input{margin:0;vertical-align:middle}
.mlist .tog{width:12px;display:inline-block;text-align:center;color:var(--muted);cursor:pointer;font-size:9px;user-select:none}
.mlist .tog.ph{cursor:default}
.mlist .lbl{cursor:pointer}
.mlist .yrow .lbl{font-weight:700}
.mlist .qrow .lbl{font-weight:600;color:#44546a}
.mlist .qnode{margin-left:14px}
.mlist .mrow{margin-left:14px}
.mlist .mrow .lbl{font-size:11.5px;color:var(--ink)}
@media(max-width:820px){.grid{grid-template-columns:1fr}}
"""


def _build_dashboard(chart_items, moved_lines, datasets, ts, toggles=None):
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
        "(the denominator). New-grad entry (NY Fed) is charted as a separate overlay below.</div>"
        "</div></div>")

    # what moved
    moved_html = escape("\n".join(moved_lines)) if moved_lines else "  (no prior snapshot — baseline established this run)"
    parts.append("<div class='panel'><h2>What moved since last run</h2>"
                 f"<div class='moved'>{moved_html}</div></div>")

    # charts by section
    section_order = ["Triangulation", "Bucket dashboard — flows", "White-collar lens",
                     "Bucket 2 — paid not producing", "Bucket 3 — unemployed",
                     "Secondary axis — denominator", "New-entrant axis (NY Fed)",
                     "Geo — postings by state/metro", "Thesis overlay"]
    ordered = [s for s in section_order if s in by_section] + \
              [s for s in by_section if s not in section_order]
    for section in ordered:
        parts.append(f"<div class='section'>{escape(section)}</div>")
        for c in by_section[section]:
            parts.append("<div class='card'>")
            parts.append(
                "<div class='mfilter'><button class='mbtn' type='button'>Months &#9662;</button>"
                "<div class='mpanel'><div class='mpanel-act'>"
                "<a class='mall'>All</a><a class='mnone'>None</a></div>"
                "<div class='mlist'></div></div></div>"
                "<button class='tglbtn' type='button' hidden>Show counts</button>")
            parts.append("<div class='chartholder'>" + c["div"] + "</div>")
            parts.append(f"<div class='note'>{escape(c['note'])}</div></div>")

    # calculations & definitions
    parts.append("<div class='panel'><h2>Definitions &amp; calculations</h2>"
                 "<div class='note'>Every formula and its source series, so nothing is a black box. "
                 "Note the participation rate is <i>not</i> employed ÷ total population — see the first row.</div>")
    for kind, label in [("definition", "How published rates are constructed"),
                        ("derived", "Derived in this pipeline")]:
        items = [c for c in config.CALCULATIONS if c["kind"] == kind]
        if not items:
            continue
        parts.append(f"<div class='section' style='margin-top:14px'>{escape(label)}</div>")
        parts.append("<table class='calc'>")
        parts.append("<tr><th>Metric</th><th>Formula</th><th>Source series</th></tr>")
        for c in items:
            note = f"<div class='calcnote'>{escape(c['note'])}</div>" if c.get("note") else ""
            parts.append(
                f"<tr><td><b>{escape(c['metric'])}</b>{note}</td>"
                f"<td class='mono'>{escape(c['formula'])}</td>"
                f"<td class='mono'>{escape(c['sources'])}</td></tr>")
        parts.append("</table>")
    parts.append("</div>")

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
    parts.append("<script>window.__toggle=" + json.dumps(toggles or {}) + ";</script>")
    parts.append(_MONTH_FILTER_JS)
    parts.append("</div></body></html>")
    return "".join(parts)


# Per-chart month multiselect. Reads each chart's data after Plotly renders,
# builds a year-grouped checkbox dropdown, and filters traces on change.
_MONTH_FILTER_JS = """
<script>
(function(){
  var clickBound=false, tries=0;
  // Plotly 6 may store x/y as plain arrays, typed arrays, or base64 specs
  // ({dtype,bdata}). Normalize any of them to a plain JS array.
  var DT={f8:Float64Array,f4:Float32Array,i4:Int32Array,i2:Int16Array,i1:Int8Array,
          u1:Uint8Array,u2:Uint16Array,u4:Uint32Array};
  function arr(v){
    if(v==null) return [];
    if(Array.isArray(v)) return v;
    if(ArrayBuffer.isView(v)) return Array.from(v);
    if(typeof v==='object' && v.bdata!==undefined){
      try{ var b=atob(v.bdata), n=b.length, by=new Uint8Array(n);
        for(var i=0;i<n;i++) by[i]=b.charCodeAt(i);
        return Array.from(new (DT[v.dtype]||Float64Array)(by.buffer)); }
      catch(e){ return []; }
    }
    try{ return Array.from(v); }catch(e){ return []; }
  }
  function init(){
    var pending=0;
    document.querySelectorAll('.card').forEach(function(card){
      var gd=card.querySelector('.plotly-graph-div');
      var dd=card.querySelector('.mfilter');
      if(!gd||!dd) return;
      if(dd.dataset.ready) return;
      if(!gd.data||!gd.data.length){ pending++; return; }
      try{ setup(card,gd,dd); dd.dataset.ready='1'; }
      catch(e){ /* leave for retry / skip */ }
    });
    if(!clickBound){ clickBound=true;
      document.addEventListener('click',function(){
        document.querySelectorAll('.mfilter.open').forEach(function(d){d.classList.remove('open');});});
    }
    if(pending>0 && tries++<30){ setTimeout(init,200); }
  }
  function setup(card,gd,dd){
      var orig=gd.data.map(function(t){return {x:arr(t.x),y:arr(t.y)};});
      var seen={};
      orig.forEach(function(t){t.x.forEach(function(v){var m=String(v).slice(0,7);
        if(/^\\d{4}-\\d{2}$/.test(m)) seen[m]=1;});});
      var months=Object.keys(seen).sort();
      var total=months.length;
      var list=dd.querySelector('.mlist'), btn=dd.querySelector('.mbtn');
      list.innerHTML='';
      // build year -> quarter -> [months] (only months present in the data)
      var tree={};
      months.forEach(function(m){
        var y=m.slice(0,4), mo=parseInt(m.slice(5,7),10), q='Q'+Math.ceil(mo/3);
        (tree[y]=tree[y]||{}); (tree[y][q]=tree[y][q]||[]).push(m);
      });
      function row(cls,cbcls,label,val){
        var r=document.createElement('div'); r.className='trow '+cls;
        var tog = cls==='mrow' ? '<span class="tog ph"></span>' : '<span class="tog">&#9656;</span>';
        var v = val!=null ? ' value="'+val+'"' : '';
        r.innerHTML=tog+'<input type="checkbox" class="'+cbcls+'" checked'+v+'>'
                    +'<span class="lbl">'+label+'</span>';
        return r;
      }
      Object.keys(tree).sort().forEach(function(y){
        var yn=document.createElement('div'); yn.className='ynode';
        yn.appendChild(row('yrow','ycb',y));
        var qwrap=document.createElement('div'); qwrap.className='subwrap'; qwrap.style.display='none';
        Object.keys(tree[y]).sort().forEach(function(q){
          var qn=document.createElement('div'); qn.className='qnode';
          qn.appendChild(row('qrow','qcb',q));
          var mwrap=document.createElement('div'); mwrap.className='subwrap'; mwrap.style.display='none';
          tree[y][q].forEach(function(m){ mwrap.appendChild(row('mrow','mcb',m,m)); });
          qn.appendChild(mwrap); qwrap.appendChild(qn);
        });
        yn.appendChild(qwrap); list.appendChild(yn);
      });
      // value modes: 'rate' (the rendered series) + optional 'count' from
      // window.__toggle (per-trace level arrays, same x/order as the rate).
      function lay(get,d){ try{ var v=get(); return v==null?d:v; }catch(e){ return d; } }
      var modes={ rate:{ ys:orig.map(function(t){return t.y;}),
        ytitle:lay(function(){return gd.layout.yaxis.title.text;},''),
        title:lay(function(){return gd.layout.title.text;},'') } };
      var curMode='rate';
      var tg=(window.__toggle||{})[gd.id];
      var tbtn=card.querySelector('.tglbtn');
      if(tbtn&&tg&&tg.count&&tg.count.ys&&tg.count.ys.length===orig.length){
        modes.count=tg.count;
        tbtn.hidden=false; tbtn.textContent='Show counts';
        tbtn.addEventListener('click',function(e){ e.preventDefault();
          curMode=curMode==='rate'?'count':'rate';
          tbtn.textContent=curMode==='rate'?'Show counts':'Show rates';
          render(); });
      }
      function setLabel(){ var n=list.querySelectorAll('.mcb:checked').length;
        btn.innerHTML='Months ('+n+'/'+total+') &#9662;'; }
      function render(){
        var sel={};
        list.querySelectorAll('.mcb:checked').forEach(function(i){sel[i.value]=1;});
        var ys=modes[curMode].ys, xs=[], nys=[];
        for(var t=0;t<orig.length;t++){
          var X=orig[t].x, Y=ys[t]||[], nx=[], ny=[];
          for(var i=0;i<X.length;i++){ if(sel[String(X[i]).slice(0,7)]){ nx.push(X[i]); ny.push(Y[i]); } }
          xs.push(nx); nys.push(ny);
        }
        Plotly.restyle(gd,{x:xs,y:nys});
        Plotly.relayout(gd,{'yaxis.title.text':modes[curMode].ytitle,'title.text':modes[curMode].title});
        setLabel();
      }
      // roll child state up into quarter + year tri-state boxes
      function refreshUp(){
        list.querySelectorAll('.qnode').forEach(function(qn){
          var ms=qn.querySelectorAll('.mcb'), c=0;
          ms.forEach(function(i){if(i.checked)c++;});
          var qcb=qn.querySelector('.qcb');
          qcb.checked=c===ms.length; qcb.indeterminate=c>0&&c<ms.length;
        });
        list.querySelectorAll('.ynode').forEach(function(yn){
          var qs=yn.querySelectorAll('.qcb'), full=0,any=0;
          qs.forEach(function(i){ if(i.checked)full++; if(i.checked||i.indeterminate)any++; });
          var ycb=yn.querySelector('.ycb');
          ycb.checked=full===qs.length; ycb.indeterminate=full!==qs.length&&any>0;
        });
      }
      // cascade a year/quarter checkbox down to all its months
      list.addEventListener('change',function(e){
        var cb=e.target;
        if(cb.classList.contains('ycb')||cb.classList.contains('qcb')){
          var scope=cb.closest('.qnode')||cb.closest('.ynode');
          scope.querySelectorAll('.mcb').forEach(function(i){i.checked=cb.checked;});
        }
        refreshUp(); render();
      });
      // expand / collapse on the triangle or the label
      list.addEventListener('click',function(e){
        var t=e.target;
        if(!(t.classList.contains('tog')||t.classList.contains('lbl'))) return;
        if(t.classList.contains('ph')) return;
        var r=t.closest('.trow'); if(r.classList.contains('mrow')) return;
        var node=r.parentNode, sub=node.children[1];
        if(!sub) return;
        var hide=sub.style.display==='none';
        sub.style.display=hide?'block':'none';
        var tog=r.querySelector('.tog'); if(tog) tog.innerHTML=hide?'&#9662;':'&#9656;';
      });
      btn.addEventListener('click',function(e){e.stopPropagation(); dd.classList.toggle('open');});
      dd.querySelector('.mpanel').addEventListener('click',function(e){e.stopPropagation();});
      function bulk(v){ list.querySelectorAll('.mcb').forEach(function(i){i.checked=v;}); refreshUp(); render(); }
      dd.querySelector('.mall').addEventListener('click',function(e){e.preventDefault(); bulk(true);});
      dd.querySelector('.mnone').addEventListener('click',function(e){e.preventDefault(); bulk(false);});
      setLabel();
  }
  if(document.readyState==='complete'){ init(); }
  else { window.addEventListener('load',init); }
})();
</script>
"""


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

    print("\n[2/5] Indeed Hiring Lab pulls (core + geo)...")
    indeed = fetch_indeed.fetch_indeed_files()
    geo = fetch_indeed.fetch_geo_files()
    nyfed_df, nyfed_rows = fetch_nyfed.fetch_nyfed()

    print("\n[3/5] Build datasets...")
    datasets = build_datasets.build(fred_frames, fred_meta, indeed,
                                    nyfed=nyfed_df, nyfed_rows=nyfed_rows, geo=geo)

    print("\n[4/5] Charts...")
    chart_items, toggles = charts.build_all(datasets)

    print("\n[5/5] Dashboard + 'what moved' diff...")
    snap = _latest_values(datasets)
    moved_lines, moved = _diff_snapshot(snap)

    ts_label = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    ts_file = dt.datetime.now().strftime("%Y-%m-%d_%H%M")
    html = _build_dashboard(chart_items, moved_lines, datasets, ts_label, toggles)
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
