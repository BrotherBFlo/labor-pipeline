"""
charts.py — triangulation overlays + bucket dashboard (Plotly).

build_all(datasets) -> list of {id, title, html_div, note}
Each figure is also written as a standalone interactive HTML into charts/.
datasets: dict {'monthly': df, 'quarterly': df, 'weekly': df, 'daily': df}
"""
import plotly.graph_objects as go
from plotly.subplots import make_subplots

import config

TEMPLATE = "plotly_white"
GOV = "#1f4e79"      # government / BLS
INDEP = "#c0504d"    # independent (ADP / Indeed)
ACCENTS = ["#1f4e79", "#c0504d", "#2e7d32", "#8e44ad", "#e67e22", "#16a085", "#7f8c8d"]

CITE_TRI = "Sources: BLS & Census via FRED (gov); ADP via FRED / Indeed Hiring Lab CC BY 4.0 (independent)."
CITE_BLS = "Source: BLS via FRED."
CITE_INDEED = "Source: Indeed Hiring Lab (CC BY 4.0)."


def _finalize(fig, title, cite):
    fig.update_layout(
        title=dict(text=title, font=dict(size=17)),
        template=TEMPLATE, hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        margin=dict(l=60, r=60, t=70, b=70), height=460,
    )
    fig.add_annotation(text=cite, xref="paper", yref="paper", x=0, y=-0.18,
                       showarrow=False, font=dict(size=10, color="#666"), align="left")
    return fig


def _index_to_base(s, base_ts):
    s = s.dropna()
    if s.empty:
        return s
    base = s[s.index >= base_ts]
    if base.empty:
        return s
    return s / base.iloc[0] * 100.0


def _has(df, cols):
    return df is not None and not df.empty and all(c in df.columns for c in cols)


# ---------------------------------------------------------------------------
# Triangulation
# ---------------------------------------------------------------------------
def _tri_payrolls_vs_adp(m):
    if not _has(m, ["payems"]):
        return None
    fig = go.Figure()
    if _has(m, ["payems"]):
        fig.add_trace(go.Scatter(x=m.index, y=m["payems"], name="BLS total nonfarm (PAYEMS)",
                                 line=dict(color=GOV, width=2)))
    if _has(m, ["uspriv"]):
        fig.add_trace(go.Scatter(x=m.index, y=m["uspriv"], name="BLS total private (USPRIV)",
                                 line=dict(color=GOV, width=1.4, dash="dot")))
    if _has(m, ["adp_priv"]):
        fig.add_trace(go.Scatter(x=m.index, y=m["adp_priv"], name="ADP private (independent)",
                                 line=dict(color=INDEP, width=2)))
    fig.update_yaxes(title_text="thousands of persons")
    return _finalize(fig, "Payroll employment — BLS vs ADP (independent)", CITE_TRI)


def _tri_openings_vs_postings(m):
    if not (_has(m, ["jolts_openings_rate"]) or _has(m, ["indeed_total_postings"])):
        return None
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    if _has(m, ["jolts_openings_rate"]):
        fig.add_trace(go.Scatter(x=m.index, y=m["jolts_openings_rate"],
                                 name="JOLTS job-openings rate (BLS)", line=dict(color=GOV, width=2)),
                      secondary_y=False)
    if _has(m, ["indeed_total_postings"]):
        fig.add_trace(go.Scatter(x=m.index, y=m["indeed_total_postings"],
                                 name="Indeed total postings (independent)", line=dict(color=INDEP, width=2)),
                      secondary_y=True)
    fig.update_yaxes(title_text="JOLTS openings rate (%)", secondary_y=False)
    fig.update_yaxes(title_text="Indeed index (Feb 2020=100)", secondary_y=True)
    return _finalize(fig, "Labor demand — JOLTS openings rate vs Indeed postings", CITE_TRI)


def _tri_earnings_vs_wages(m):
    if not _has(m, ["avg_hourly_earnings"]) and not _has(m, ["indeed_posted_wage_growth"]):
        return None
    fig = go.Figure()
    if _has(m, ["avg_hourly_earnings"]):
        ahe_yoy = m["avg_hourly_earnings"].pct_change(12, fill_method=None) * 100.0
        fig.add_trace(go.Scatter(x=m.index, y=ahe_yoy, name="BLS avg hourly earnings, YoY %",
                                 line=dict(color=GOV, width=2)))
    if _has(m, ["indeed_posted_wage_growth"]):
        fig.add_trace(go.Scatter(x=m.index, y=m["indeed_posted_wage_growth"],
                                 name="Indeed posted-wage growth, YoY % (independent)",
                                 line=dict(color=INDEP, width=2)))
    fig.update_yaxes(title_text="percent (YoY)")
    return _finalize(fig, "Wage growth — BLS earnings vs Indeed posted wages", CITE_TRI)


# ---------------------------------------------------------------------------
# Bucket dashboard
# ---------------------------------------------------------------------------
def _flows(m):
    cols = [("jolts_hires_rate", "Hires", ACCENTS[2]),
            ("jolts_quits_rate", "Quits (voluntary)", ACCENTS[3]),
            ("jolts_layoffs_rate", "Layoffs & discharges", ACCENTS[1])]
    if not any(_has(m, [c]) for c, _, _ in cols):
        return None
    fig = go.Figure()
    for c, label, color in cols:
        if _has(m, [c]):
            fig.add_trace(go.Scatter(x=m.index, y=m[c], name=label, line=dict(color=color, width=2)))
    fig.update_yaxes(title_text="rate (% of employment)")
    return _finalize(fig, "Frozen-market flows — hires, quits, layoffs (JOLTS)", CITE_BLS)


def _white_collar_divergence(m):
    members = [("emp_prof_bus", "Professional & business svcs"),
               ("emp_info", "Information"),
               ("emp_financial", "Financial activities"),
               ("payems", "Total nonfarm (benchmark)")]
    present = [(c, l) for c, l in members if _has(m, [c])]
    if not present:
        return None
    base = config.OBSERVATION_START
    import pandas as pd
    base_ts = pd.Timestamp(base)
    fig = go.Figure()
    for i, (c, l) in enumerate(present):
        idx = _index_to_base(m[c], base_ts)
        dash = "solid" if c != "payems" else "dash"
        fig.add_trace(go.Scatter(x=idx.index, y=idx, name=l,
                                 line=dict(color=ACCENTS[i % len(ACCENTS)], width=2, dash=dash)))
    fig.update_yaxes(title_text=f"index ({base[:7]}=100)")
    return _finalize(fig, "White-collar divergence — knowledge-work employment, indexed", CITE_BLS)


def _indeed_wc_vs_inperson(d):
    if not (_has(d, ["indeed_white_collar_postings"]) or _has(d, ["indeed_in_person_postings"])):
        return None
    fig = go.Figure()
    if _has(d, ["indeed_white_collar_postings"]):
        fig.add_trace(go.Scatter(x=d.index, y=d["indeed_white_collar_postings"],
                                 name="White-collar postings", line=dict(color=GOV, width=2)))
    if _has(d, ["indeed_in_person_postings"]):
        fig.add_trace(go.Scatter(x=d.index, y=d["indeed_in_person_postings"],
                                 name="In-person postings", line=dict(color=INDEP, width=2)))
    fig.update_yaxes(title_text="index (Feb 2020=100)")
    return _finalize(fig, "Indeed postings — white-collar vs in-person composites", CITE_INDEED)


def _unemployment_quality(m):
    cols = [("unrate", "U-3 (headline)", ACCENTS[0]),
            ("u6rate", "U-6 (underemployment)", ACCENTS[1]),
            ("unrate_bachelors", "Bachelor's+ (25+)", ACCENTS[2])]
    if not any(_has(m, [c]) for c, _, _ in cols):
        return None
    fig = go.Figure()
    for c, label, color in cols:
        if _has(m, [c]):
            fig.add_trace(go.Scatter(x=m.index, y=m[c], name=label, line=dict(color=color, width=2)))
    fig.update_yaxes(title_text="percent")
    return _finalize(fig, "Unemployment quality — U-3, U-6, and the bachelor's+ cut", CITE_BLS)


def _participation_vs_force(m):
    if not (_has(m, ["civpart"]) or _has(m, ["labor_force"])):
        return None
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    if _has(m, ["labor_force"]):
        fig.add_trace(go.Scatter(x=m.index, y=m["labor_force"], name="Civilian labor force (level)",
                                 line=dict(color=ACCENTS[4], width=2)), secondary_y=True)
    if _has(m, ["civpart"]):
        fig.add_trace(go.Scatter(x=m.index, y=m["civpart"], name="Participation rate",
                                 line=dict(color=GOV, width=2)), secondary_y=False)
    fig.update_yaxes(title_text="participation rate (%)", secondary_y=False)
    fig.update_yaxes(title_text="labor force (thousands)", secondary_y=True)
    return _finalize(fig, "The expanding workforce — participation vs labor force (denominator)", CITE_BLS)


def _claims(w):
    if not (_has(w, ["initial_claims"]) or _has(w, ["continued_claims"])):
        return None
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    if _has(w, ["initial_claims"]):
        fig.add_trace(go.Scatter(x=w.index, y=w["initial_claims"], name="Initial claims",
                                 line=dict(color=GOV, width=1.5)), secondary_y=False)
    if _has(w, ["initial_claims_4wk"]):
        fig.add_trace(go.Scatter(x=w.index, y=w["initial_claims_4wk"], name="Initial, 4-wk avg",
                                 line=dict(color="#0d2b45", width=2)), secondary_y=False)
    if _has(w, ["continued_claims"]):
        fig.add_trace(go.Scatter(x=w.index, y=w["continued_claims"], name="Continued claims (insured unemp.)",
                                 line=dict(color=INDEP, width=2)), secondary_y=True)
    fig.update_yaxes(title_text="initial claims", secondary_y=False)
    fig.update_yaxes(title_text="continued claims", secondary_y=True)
    return _finalize(fig, "UI claims (weekly) — initial vs continued", CITE_BLS)


def _business_formation(m):
    cols = [("business_apps_total", "All business applications", ACCENTS[0]),
            ("business_apps_high_propensity", "High-propensity applications", ACCENTS[3])]
    if not any(_has(m, [c]) for c, _, _ in cols):
        return None
    fig = go.Figure()
    for c, label, color in cols:
        if _has(m, [c]):
            fig.add_trace(go.Scatter(x=m.index, y=m[c], name=label, line=dict(color=color, width=2)))
    fig.update_yaxes(title_text="applications (thousands, SA)")
    return _finalize(fig, "Business formation (bucket 2, partly modeled) — Census BFS",
                     "Source: Census Business Formation Statistics via FRED. Bucket 2 is partly modeled.")


def _self_employment(m):
    cols = [("self_emp_incorporated", "Self-employed, incorporated", ACCENTS[2]),
            ("self_emp_unincorporated", "Self-employed, unincorporated", ACCENTS[5])]
    if not any(_has(m, [c]) for c, _, _ in cols):
        return None
    fig = go.Figure()
    for c, label, color in cols:
        if _has(m, [c]):
            fig.add_trace(go.Scatter(x=m.index, y=m[c], name=label, line=dict(color=color, width=2)))
    fig.update_yaxes(title_text="thousands of persons")
    return _finalize(fig, "Self-employment (bucket 2 proxy)", CITE_BLS)


def _u6_u3_wedge(m):
    if not _has(m, ["u6_minus_u3_wedge"]):
        return None
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=m.index, y=m["u6_minus_u3_wedge"], name="U-6 minus U-3 wedge",
                             line=dict(color=ACCENTS[3], width=2), fill="tozeroy"))
    fig.update_yaxes(title_text="percentage points")
    return _finalize(fig, "U-6 minus U-3 wedge (bucket-2 proxy: marginal attachment + involuntary part-time)", CITE_BLS)


def _nyfed_unemp(n):
    cols = [("nyfed_recent_grad_unemp", "Recent grads (21-27)", INDEP),
            ("nyfed_college_grad_unemp", "All college grads", ACCENTS[3]),
            ("nyfed_all_worker_unemp", "All workers", GOV),
            ("nyfed_young_worker_unemp", "All young workers", ACCENTS[5])]
    if not any(_has(n, [c]) for c, _, _ in cols):
        return None
    fig = go.Figure()
    for c, label, color in cols:
        if _has(n, [c]):
            w = 2.4 if c == "nyfed_recent_grad_unemp" else 1.6
            fig.add_trace(go.Scatter(x=n.index, y=n[c], name=label, line=dict(color=color, width=w)))
    fig.update_yaxes(title_text="unemployment rate (%)")
    return _finalize(fig, "New-entrant axis — recent-grad unemployment (NY Fed)",
                     "Source: NY Fed, Labor Market for Recent College Graduates (monthly 3-mo MA).")


def _nyfed_underemp(n):
    cols = [("nyfed_recent_grad_underemp", "Recent grads", INDEP),
            ("nyfed_college_grad_underemp", "All college grads", ACCENTS[3])]
    if not any(_has(n, [c]) for c, _, _ in cols):
        return None
    fig = go.Figure()
    for c, label, color in cols:
        if _has(n, [c]):
            fig.add_trace(go.Scatter(x=n.index, y=n[c], name=label, line=dict(color=color, width=2)))
    fig.update_yaxes(title_text="underemployment rate (%)")
    return _finalize(fig, "New-entrant axis — recent-grad underemployment (NY Fed)",
                     "Source: NY Fed. Underemployment = working a job that doesn't require a degree.")


def _geo(pivot, title):
    if pivot is None or pivot.empty:
        return None
    fig = go.Figure()
    for i, col in enumerate(pivot.columns):
        fig.add_trace(go.Scatter(x=pivot.index, y=pivot[col], name=str(col).upper()
                                 if len(str(col)) <= 3 else str(col),
                                 line=dict(color=ACCENTS[i % len(ACCENTS)], width=1.6)))
    fig.update_yaxes(title_text="postings index (Feb 2020=100)")
    return _finalize(fig, title, CITE_INDEED)


def _ai_share(d):
    if not _has(d, ["indeed_ai_share"]):
        return None
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=d.index, y=d["indeed_ai_share"], name="AI/GenAI postings share",
                             line=dict(color="#8e44ad", width=2)))
    fig.update_yaxes(title_text="percent of postings")
    return _finalize(fig, "AI as a new buyer — share of US postings mentioning AI/GenAI", CITE_INDEED)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def build_all(datasets):
    m = datasets.get("monthly")
    q = datasets.get("quarterly")
    w = datasets.get("weekly")
    d = datasets.get("daily")
    n = datasets.get("nyfed")
    geo = datasets.get("geo_focus") or {}

    specs = [
        # (id, section, builder, note)
        ("payrolls_vs_adp", "Triangulation", _tri_payrolls_vs_adp(m),
         "Gov vs independent payroll count. Watch for persistent ADP-vs-BLS gaps."),
        ("openings_vs_postings", "Triangulation", _tri_openings_vs_postings(m),
         "JOLTS lags ~5 weeks; Indeed is near-real-time — divergence flags turning points early."),
        ("earnings_vs_posted_wages", "Triangulation", _tri_earnings_vs_wages(m),
         "BLS measures pay of the employed; Indeed measures pay offered to new hires."),
        ("flows", "Bucket dashboard — flows", _flows(m),
         "A 'frozen' market shows low hires AND low layoffs with falling quits."),
        ("white_collar_divergence", "White-collar lens", _white_collar_divergence(m),
         "Knowledge-work employment indexed against total nonfarm."),
        ("indeed_wc_vs_inperson", "White-collar lens", _indeed_wc_vs_inperson(d),
         "Independent read on the white-collar / in-person split."),
        ("unemployment_quality", "Bucket 3 — unemployed", _unemployment_quality(m),
         "Bachelor's+ cut isolates the white-collar unemployment signal."),
        ("u6_u3_wedge", "Bucket 2 — paid not producing", _u6_u3_wedge(m),
         "Proxy for marginal attachment + involuntary part-time."),
        ("business_formation", "Bucket 2 — paid not producing", _business_formation(m),
         "Partly modeled: formation can't confirm a corporate exit or revenue."),
        ("self_employment", "Bucket 2 — paid not producing", _self_employment(m),
         "Incorporated vs unincorporated self-employment."),
        ("claims", "Bucket 3 — unemployed", _claims(w),
         "Initial = new layoffs; continued = ongoing joblessness."),
        ("participation_vs_force", "Secondary axis — denominator", _participation_vs_force(m),
         "The expanding workforce: the denominator behind every rate."),
        ("ai_share", "Thesis overlay", _ai_share(d),
         "AI-as-buyer thesis: rising share of postings referencing AI/GenAI."),
        ("nyfed_unemp", "New-entrant axis (NY Fed)", _nyfed_unemp(n),
         "Recent grads now face HIGHER unemployment than all workers — a reversal of the historical edge."),
        ("nyfed_underemp", "New-entrant axis (NY Fed)", _nyfed_underemp(n),
         "Share of recent grads in jobs that don't require a degree."),
        ("geo_states", "Geo — postings by state/metro", _geo(geo.get("state"),
         "Job postings index — selected states"),
         "Independent state-level demand read."),
        ("geo_metros", "Geo — postings by state/metro", _geo(geo.get("metro"),
         "Job postings index — selected metros"),
         "Independent metro-level demand read (tech-heavy metros worth watching)."),
    ]

    out = []
    for cid, section, fig, note in specs:
        if fig is None:
            print(f"  [skip] chart {cid}: required columns missing")
            continue
        # standalone interactive file
        fig.write_html(config.CHARTS_DIR / f"{cid}.html", include_plotlyjs="cdn",
                       full_html=True)
        div = fig.to_html(include_plotlyjs=False, full_html=False,
                          config={"displayModeBar": False})
        out.append(dict(id=cid, section=section, title=fig.layout.title.text,
                        div=div, note=note))
        print(f"  [ok] chart {cid}")
    return out
