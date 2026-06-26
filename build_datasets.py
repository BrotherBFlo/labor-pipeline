"""
build_datasets.py — assemble frequency-partitioned files + data dictionary.

Takes the raw FRED frames + Indeed dataframes and produces, in data/:
  monthly.csv / quarterly.csv / weekly.csv / daily.csv   (wide, date-indexed)
  *_long.csv                                              (tidy long variants)
  sources.csv                                             (data dictionary)

Hygiene honored here:
  - FRED '.' already coerced to NaN upstream; we DO NOT interpolate. Gaps
    (incl. the Oct-2025 appropriations lapse) are preserved as empty cells.
  - Indeed sector composites are equal-weight means of Indeed's per-sector
    index — documented as 'derived' in the data dictionary.
"""
import pandas as pd

import config


# ---------------------------------------------------------------------------
# Indeed shaping
# ---------------------------------------------------------------------------
def _shape_indeed(indeed):
    """Return (daily_df, monthly_add_df, indeed_dict_rows)."""
    rows = []

    # -- aggregate total/new postings (SA) ---------------------------------
    agg = indeed.get("job_postings_aggregate")
    tot = new = None
    if agg is not None:
        a = agg[agg["jobcountry"] == "US"].copy()
        a["date"] = pd.to_datetime(a["date"])
        tot = a[a["variable"] == "total postings"].set_index("date")["indeed_job_postings_index_SA"].sort_index()
        new = a[a["variable"] == "new postings"].set_index("date")["indeed_job_postings_index_SA"].sort_index()

    # -- sector composites --------------------------------------------------
    wc = ip = None
    sec = indeed.get("job_postings_by_sector")
    if sec is not None:
        s = sec[(sec["jobcountry"] == "US") & (sec["variable"] == "total postings")].copy()
        s["date"] = pd.to_datetime(s["date"])
        piv = s.pivot_table(index="date", columns="display_name",
                            values="indeed_job_postings_index").sort_index()
        wc_cols = [c for c in config.INDEED_WHITE_COLLAR_SECTORS if c in piv.columns]
        ip_cols = [c for c in config.INDEED_IN_PERSON_SECTORS if c in piv.columns]
        missing = (set(config.INDEED_WHITE_COLLAR_SECTORS) - set(wc_cols)) | \
                  (set(config.INDEED_IN_PERSON_SECTORS) - set(ip_cols))
        if missing:
            print(f"  [WARN] Indeed composite: sectors not found -> {sorted(missing)}")
        wc = piv[wc_cols].mean(axis=1) if wc_cols else None
        ip = piv[ip_cols].mean(axis=1) if ip_cols else None

    # -- AI share -----------------------------------------------------------
    ai_s = None
    ai = indeed.get("ai_postings_share")
    if ai is not None:
        a = ai[ai["jobcountry"] == "US"].copy()
        a["date"] = pd.to_datetime(a["date"])
        ai_s = a.set_index("date")["AI_share_postings"].sort_index()

    # -- posted wage growth (US, monthly) -----------------------------------
    wage = None
    wg = indeed.get("posted_wage_growth_country")
    if wg is not None:
        w = wg[wg["jobcountry"] == "US"].copy()
        w["date"] = pd.to_datetime(w["month"], format="%b-%y")
        wage = (w.set_index("date")["posted_wage_growth_yoy"] * 100.0).sort_index()

    # -- daily frame --------------------------------------------------------
    daily_cols = {}
    if tot is not None: daily_cols["indeed_total_postings"] = tot
    if new is not None: daily_cols["indeed_new_postings"] = new
    if wc is not None:  daily_cols["indeed_white_collar_postings"] = wc
    if ip is not None:  daily_cols["indeed_in_person_postings"] = ip
    if ai_s is not None: daily_cols["indeed_ai_share"] = ai_s
    daily_df = pd.DataFrame(daily_cols).sort_index()

    # -- monthly-aligned additions (month-start, to match FRED monthly) -----
    def to_ms(s):
        m = s.resample("MS").mean()
        return m
    monthly_add = {}
    if tot is not None: monthly_add["indeed_total_postings"] = to_ms(tot)
    if wc is not None:  monthly_add["indeed_white_collar_postings"] = to_ms(wc)
    if ip is not None:  monthly_add["indeed_in_person_postings"] = to_ms(ip)
    if ai_s is not None: monthly_add["indeed_ai_share"] = to_ms(ai_s)
    if wage is not None:
        wm = wage.copy()
        wm.index = wm.index.to_period("M").to_timestamp()  # snap to month start
        monthly_add["indeed_posted_wage_growth"] = wm
    monthly_add_df = pd.DataFrame(monthly_add).sort_index()

    # -- data-dictionary rows for Indeed/derived columns --------------------
    SRC = "Indeed Hiring Lab (CC BY 4.0)"
    rows += [
        dict(column="indeed_total_postings", source=SRC, series_id="aggregate_job_postings_US",
             concept="Indeed total job postings index", unit="index (Feb 2020=100)",
             seasonal_adjustment="Seasonally Adjusted", bucket="flow", lens=None, derived="no"),
        dict(column="indeed_new_postings", source=SRC, series_id="aggregate_job_postings_US",
             concept="Indeed new job postings index", unit="index (Feb 2020=100)",
             seasonal_adjustment="Seasonally Adjusted", bucket="flow", lens=None, derived="no"),
        dict(column="indeed_white_collar_postings", source=SRC, series_id="job_postings_by_sector_US",
             concept="Indeed white-collar postings composite (equal-weight mean of "
                     + ", ".join(config.INDEED_WHITE_COLLAR_SECTORS) + ")",
             unit="index (Feb 2020=100)", seasonal_adjustment="Seasonally Adjusted",
             bucket="1", lens="white_collar", derived="yes (equal-weight sector mean)"),
        dict(column="indeed_in_person_postings", source=SRC, series_id="job_postings_by_sector_US",
             concept="Indeed in-person postings composite (equal-weight mean of "
                     + ", ".join(config.INDEED_IN_PERSON_SECTORS) + ")",
             unit="index (Feb 2020=100)", seasonal_adjustment="Seasonally Adjusted",
             bucket="1", lens=None, derived="yes (equal-weight sector mean)"),
        dict(column="indeed_ai_share", source=SRC, series_id="AI_posting",
             concept="Share of US Indeed postings mentioning AI/GenAI", unit="percent of postings",
             seasonal_adjustment="Not Seasonally Adjusted", bucket="flow", lens=None, derived="no"),
        dict(column="indeed_posted_wage_growth", source=SRC, series_id="posted-wage-growth-by-country (US)",
             concept="Indeed posted-wage growth, year-over-year (independent income read)",
             unit="percent (YoY)", seasonal_adjustment="Not Seasonally Adjusted",
             bucket="inc", lens=None, derived="yes (yoy fraction x100)"),
    ]
    return daily_df, monthly_add_df, rows


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------
def _wide_from_fred(fred_frames, fred_meta, freq):
    cols = {}
    for k, spec in fred_meta.items():
        if spec["freq"] == freq:
            cols[k] = fred_frames[k]
    if not cols:
        return pd.DataFrame()
    df = pd.DataFrame(cols).sort_index()
    return df


def _write_pair(df, name):
    """Write wide + tidy long. Wide preserves NaN as empty cells."""
    df = df.sort_index()
    # global window clip — keeps Indeed-derived columns from reintroducing the
    # pre-window (COVID-era) rows via the outer joins.
    df = df[df.index >= pd.Timestamp(config.OBSERVATION_START)]
    df.index.name = "date"
    wide_path = config.DATA_DIR / f"{name}.csv"
    df.to_csv(wide_path, date_format="%Y-%m-%d")
    long = (df.reset_index()
              .melt(id_vars="date", var_name="series", value_name="value")
              .dropna(subset=["value"])
              .sort_values(["series", "date"]))
    long.to_csv(config.DATA_DIR / f"{name}_long.csv", index=False, date_format="%Y-%m-%d")
    return wide_path, len(df.columns), len(df)


def _write_geo(geo):
    """Write state (full) + metro (focus-subset) long files; return focus pivots."""
    focus = {}
    extra_rows = []
    start = pd.Timestamp(config.OBSERVATION_START)
    st = geo.get("state_postings")
    if st is not None:
        s = st.copy()
        s["date"] = pd.to_datetime(s["date"])
        s = s[s["date"] >= start]
        s.to_csv(config.DATA_DIR / "indeed_state_postings.csv", index=False, date_format="%Y-%m-%d")
        f = s[s["state"].isin(config.GEO_FOCUS_STATES)]
        focus["state"] = f.pivot_table(index="date", columns="state",
                                       values="indeed_job_postings_index").sort_index()
        print(f"  [ok] geo state    {s.shape[0]:>7} rows -> indeed_state_postings.csv")
        extra_rows.append(dict(column="indeed_state_postings", file="indeed_state_postings.csv",
            source="Indeed Hiring Lab (CC BY 4.0)", series_id="state_job_postings_us",
            concept="Job postings index by US state (long: date, state, index)",
            unit="index (Feb 2020=100)", frequency="daily",
            seasonal_adjustment="Seasonally Adjusted", bucket="flow", lens="", derived="no"))
    mt = geo.get("metro_postings")
    if mt is not None:
        m = mt.copy()
        m["date"] = pd.to_datetime(m["date"])
        mask = m["metro"].str.contains("|".join(config.GEO_FOCUS_METROS), case=False, na=False)
        m = m[mask & (m["date"] >= start)]
        m.to_csv(config.DATA_DIR / "indeed_metro_postings.csv", index=False, date_format="%Y-%m-%d")
        focus["metro"] = m.pivot_table(index="date", columns="metro",
                                       values="indeed_job_postings_index").sort_index()
        print(f"  [ok] geo metro    {m.shape[0]:>7} rows (focus subset) -> indeed_metro_postings.csv")
        extra_rows.append(dict(column="indeed_metro_postings", file="indeed_metro_postings.csv",
            source="Indeed Hiring Lab (CC BY 4.0)", series_id="metro_job_postings_us",
            concept="Job postings index by US metro/CBSA (long; filtered to focus metros)",
            unit="index (Feb 2020=100)", frequency="daily",
            seasonal_adjustment="Seasonally Adjusted", bucket="flow", lens="", derived="no"))
    return focus, extra_rows


def _write_nyfed(nyfed_df):
    if nyfed_df is None or nyfed_df.empty:
        return
    df = nyfed_df.sort_index()
    df.index.name = "date"
    df.to_csv(config.DATA_DIR / "nyfed_recent_grads.csv", date_format="%Y-%m-%d")
    long = (df.reset_index().melt(id_vars="date", var_name="series", value_name="value")
              .dropna(subset=["value"]).sort_values(["series", "date"]))
    long.to_csv(config.DATA_DIR / "nyfed_recent_grads_long.csv", index=False, date_format="%Y-%m-%d")
    print(f"  [ok] nyfed        {df.shape[1]} series x {len(df)} months -> nyfed_recent_grads.csv")


def build(fred_frames, fred_meta, indeed, nyfed=None, nyfed_rows=None, geo=None):
    print("\nAssembling frequency-partitioned datasets...")
    daily_df, monthly_add_df, indeed_rows = _shape_indeed(indeed)

    # ---- monthly: FRED monthly + Indeed monthly-aligned + derived ---------
    monthly = _wide_from_fred(fred_frames, fred_meta, "monthly")
    if not monthly_add_df.empty:
        monthly = monthly.join(monthly_add_df, how="outer")
    # derived: U-6 minus U-3 wedge (bucket-2 proxy)
    if {"u6rate", "unrate"}.issubset(monthly.columns):
        monthly["u6_minus_u3_wedge"] = monthly["u6rate"] - monthly["unrate"]

    quarterly = _wide_from_fred(fred_frames, fred_meta, "quarterly")
    weekly = _wide_from_fred(fred_frames, fred_meta, "weekly")

    written = {}
    start = pd.Timestamp(config.OBSERVATION_START)
    for name, df in [("monthly", monthly), ("quarterly", quarterly),
                     ("weekly", weekly), ("daily", daily_df)]:
        if df.empty:
            print(f"  [skip] {name}: no columns")
            continue
        # clip BEFORE writing AND before charting — Indeed-derived columns reach
        # back to 2019/2020, so the in-memory frame must be windowed too.
        df = df[df.index >= start]
        path, ncols, nrows = _write_pair(df, name)
        written[name] = df
        print(f"  [ok] {name:<10} {ncols:>2} cols x {nrows:>4} rows -> {path.name}")

    # ---- NY Fed new-entrant overlay (separate file) -----------------------
    _write_nyfed(nyfed)
    if nyfed is not None and not nyfed.empty:
        written["nyfed"] = nyfed

    # ---- optional geo (separate long files) -------------------------------
    geo_focus, geo_rows = ({}, [])
    if geo:
        geo_focus, geo_rows = _write_geo(geo)
    written["geo_focus"] = geo_focus

    # ---- data dictionary --------------------------------------------------
    _write_sources(fred_meta, indeed_rows, monthly, daily_df,
                   extra_rows=(nyfed_rows or []) + geo_rows)
    return written


def _write_sources(fred_meta, indeed_rows, monthly, daily_df, extra_rows=None):
    rows = []
    file_for_freq = {"monthly": "monthly.csv", "quarterly": "quarterly.csv",
                     "weekly": "weekly.csv", "daily": "daily.csv"}
    for k, spec in fred_meta.items():
        rows.append(dict(
            column=k,
            file=file_for_freq.get(spec["freq"], ""),
            source="BLS/Census via FRED" if spec["series_id"] != "ADPMNUSNERSA" else "ADP via FRED",
            series_id=spec.get("series_id") or spec.get("candidate_id"),
            concept=spec.get("concept", spec.get("title", "")),
            unit=spec.get("units", ""),
            frequency=spec.get("frequency", spec["freq"]),
            seasonal_adjustment=spec.get("seasonal_adjustment", ""),
            bucket=spec.get("bucket", ""),
            lens=spec.get("lens") or "",
            resolved_via=spec.get("resolved_via", ""),
            derived="no",
        ))
    for r in indeed_rows:
        in_monthly = r["column"] in monthly.columns
        in_daily = r["column"] in daily_df.columns
        f = []
        if in_daily: f.append("daily.csv")
        if in_monthly: f.append("monthly.csv")
        rows.append(dict(
            column=r["column"], file=" + ".join(f), source=r["source"],
            series_id=r["series_id"], concept=r["concept"], unit=r["unit"],
            frequency="daily/monthly" if (in_daily and in_monthly) else ("daily" if in_daily else "monthly"),
            seasonal_adjustment=r["seasonal_adjustment"], bucket=r["bucket"],
            lens=r["lens"] or "", resolved_via="", derived=r["derived"],
        ))
    # derived wedge row
    if "u6_minus_u3_wedge" in monthly.columns:
        rows.append(dict(
            column="u6_minus_u3_wedge", file="monthly.csv", source="Derived (BLS via FRED)",
            series_id="U6RATE - UNRATE", concept="U-6 minus U-3 wedge (marginally attached + "
            "part-time-for-economic-reasons; bucket-2 proxy)", unit="percentage points",
            frequency="Monthly", seasonal_adjustment="Seasonally Adjusted", bucket="2",
            lens="", resolved_via="", derived="yes",
        ))
    for r in (extra_rows or []):
        rows.append(dict(
            column=r["column"], file=r.get("file", "nyfed_recent_grads.csv"),
            source=r["source"], series_id=r["series_id"], concept=r["concept"],
            unit=r["unit"], frequency=r.get("frequency", "Monthly (3-mo MA)"),
            seasonal_adjustment=r["seasonal_adjustment"], bucket=r["bucket"],
            lens=r.get("lens", "") or "", resolved_via="", derived=r.get("derived", "no"),
        ))
    cols = ["column", "file", "source", "series_id", "concept", "unit", "frequency",
            "seasonal_adjustment", "bucket", "lens", "derived", "resolved_via"]
    pd.DataFrame(rows)[cols].to_csv(config.DATA_DIR / "sources.csv", index=False)
    print(f"  [ok] data dictionary -> sources.csv ({len(rows)} columns documented)")
