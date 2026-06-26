"""
config.py — series catalog, date window, paths.

The catalog is the analytical source of truth. Each FRED entry carries the
*intended* frequency and the *bucket* it serves (my analytical choice);
authoritative unit / seasonal-adjustment / title / frequency are fetched from
the FRED series-metadata endpoint at run time and merged into the data
dictionary, so we never hand-wave the units.

Bucket framework (see README):
  1  = paid AND producing      (active payroll attachment)
  2  = paid but NOT producing  (PARTLY MODELED / proxied — see README)
  3  = truly unemployed without pay
  sec = secondary axis: the expanding workforce (denominator)
  inc = income / earnings read (cross-cutting)
  flow = labor-market flows (JOLTS churn)
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
CHARTS_DIR = ROOT / "charts"
DASHBOARD_DIR = ROOT / "dashboard"
STATE_FILE = DATA_DIR / "_last_values.json"  # for "what moved" diff

for _d in (DATA_DIR, CHARTS_DIR, DASHBOARD_DIR):
    _d.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Date window (configurable). 2022-01-01 keeps the post-COVID-normalization era
# so scales stay legible — the 2020-21 spikes (6M initial claims, 14.7% U-3)
# otherwise crush every level chart. Applied globally: FRED pulls use it as
# observation_start; Indeed/geo/NY-Fed frames are clipped to it on assembly.
# ---------------------------------------------------------------------------
OBSERVATION_START = "2022-01-01"

# FRED API
FRED_BASE = "https://api.stlouisfed.org/fred"
FRED_RATE_LIMIT_PER_MIN = 120

# ---------------------------------------------------------------------------
# FRED series catalog
# ---------------------------------------------------------------------------
# key            -> wide-file column name (stable slug)
# series_id      -> FRED id, or None when it must be search-resolved
# search_text    -> used to resolve when series_id is None OR a candidate 404s
# candidate_id   -> a best-guess id to try before falling back to search
# freq           -> which frequency file it lands in
# bucket         -> analytical bucket (see header)
# lens           -> 'white_collar' tag for the professional cut, else None
# ---------------------------------------------------------------------------
FRED_SERIES = [
    # ---- MONTHLY ----------------------------------------------------------
    dict(key="payems",        series_id="PAYEMS",       freq="monthly", bucket="1",   lens=None,
         concept="Total nonfarm payrolls"),
    dict(key="uspriv",        series_id="USPRIV",       freq="monthly", bucket="1",   lens=None,
         concept="Total private payrolls"),
    dict(key="adp_priv",      series_id="ADPMNUSNERSA", freq="monthly", bucket="1",   lens=None,
         concept="ADP private payrolls (independent of BLS)"),
    dict(key="emp_prof_bus",  series_id="USPBS",        freq="monthly", bucket="1",   lens="white_collar",
         concept="Professional & business services employment"),
    dict(key="emp_info",      series_id="USINFO",       freq="monthly", bucket="1",   lens="white_collar",
         concept="Information employment"),
    dict(key="emp_financial", series_id="USFIRE",       freq="monthly", bucket="1",   lens="white_collar",
         concept="Financial activities employment"),
    dict(key="avg_hourly_earnings", series_id="CES0500000003", freq="monthly", bucket="inc", lens=None,
         concept="Average hourly earnings, total private"),
    dict(key="unrate",        series_id="UNRATE",       freq="monthly", bucket="3",   lens=None,
         concept="Unemployment rate (U-3)"),
    dict(key="u6rate",        series_id="U6RATE",       freq="monthly", bucket="3",   lens=None,
         concept="U-6 underemployment rate"),
    dict(key="civpart",       series_id="CIVPART",      freq="monthly", bucket="sec", lens=None,
         concept="Labor force participation rate"),
    dict(key="labor_force",   series_id="CLF16OV",      freq="monthly", bucket="sec", lens=None,
         concept="Civilian labor force level"),
    # Employment ratios — answer "what share of the working-age pop is employed?"
    # CIVPART's denominator is everyone 16+ (incl. retirees) and its numerator
    # includes the unemployed; these isolate employed ÷ a tighter age base.
    dict(key="emp_pop_ratio", series_id="EMRATIO",      freq="monthly", bucket="sec", lens=None,
         concept="Employment-population ratio, 16+ (employed ÷ civ. noninstitutional pop 16+)"),
    dict(key="emp_rate_15_64", series_id="LREM64TTUSM156S", freq="monthly", bucket="sec", lens=None,
         concept="Employment rate, 15-64 working age (employed ÷ pop 15-64; ≈ your 18-65 ask)"),
    dict(key="emp_pop_ratio_prime", series_id="LNS12300060", freq="monthly", bucket="sec", lens=None,
         concept="Employment-population ratio, prime age 25-54 (employed ÷ pop 25-54)"),
    dict(key="civpart_prime", series_id="LNS11300060",  freq="monthly", bucket="sec", lens=None,
         concept="Labor force participation rate, prime age 25-54"),
    dict(key="emp_level",     series_id="CE16OV",       freq="monthly", bucket="1",   lens=None,
         concept="Civilian employment level"),
    dict(key="unemploy",      series_id="UNEMPLOY",     freq="monthly", bucket="3",   lens=None,
         concept="Unemployed level"),
    # JOLTS — flows
    dict(key="jolts_openings_rate",  series_id="JTSJOR", freq="monthly", bucket="flow", lens=None,
         concept="JOLTS job openings rate"),
    dict(key="jolts_openings_level", series_id="JTSJOL", freq="monthly", bucket="flow", lens=None,
         concept="JOLTS job openings level"),
    dict(key="jolts_quits_rate",     series_id="JTSQUR", freq="monthly", bucket="2",   lens=None,
         concept="JOLTS quits rate (voluntary movement)"),
    dict(key="jolts_quits_level",    series_id="JTSQUL", freq="monthly", bucket="2",   lens=None,
         concept="JOLTS quits level"),
    dict(key="jolts_layoffs_rate",   series_id="JTSLDR", freq="monthly", bucket="flow", lens=None,
         concept="JOLTS layoffs & discharges rate"),
    dict(key="jolts_layoffs_level",  series_id="JTSLDL", freq="monthly", bucket="flow", lens=None,
         concept="JOLTS layoffs & discharges level"),
    dict(key="jolts_hires_rate",     series_id="JTSHIR", freq="monthly", bucket="flow", lens=None,
         concept="JOLTS hires rate"),
    dict(key="jolts_hires_level",    series_id="JTSHIL", freq="monthly", bucket="flow", lens=None,
         concept="JOLTS hires level"),
    # Census BFS via FRED
    dict(key="business_apps_total",  series_id="BABATOTALSAUS", freq="monthly", bucket="2", lens=None,
         concept="Business applications, total (Census BFS)"),
    # search-resolved monthly
    dict(key="unrate_bachelors", series_id=None, candidate_id="LNS14027662",
         search_text="unemployment rate bachelor's degree and higher 25 years",
         freq="monthly", bucket="3", lens="white_collar",
         concept="Unemployment rate, bachelor's+ (25+)"),
    dict(key="business_apps_high_propensity", series_id=None, candidate_id="BABPBIAPPSAUS",
         search_text="high-propensity business applications",
         freq="monthly", bucket="2", lens=None,
         concept="High-propensity business applications"),
    # NOTE: brief's suggested LNS12032194 is actually "Part-Time for Economic
    # Reasons" — wrong concept. Correct incorporated self-employed level is
    # LNU02048984 (NSA, monthly). Unincorporated LNS12027714 is SA. SA mismatch
    # is flagged in the data dictionary (units/SA pulled live from FRED).
    dict(key="self_emp_incorporated", series_id=None, candidate_id="LNU02048984",
         search_text="incorporated self-employed employment level",
         freq="monthly", bucket="2", lens=None,
         concept="Self-employed, incorporated (NSA)"),
    dict(key="self_emp_unincorporated", series_id=None, candidate_id="LNS12027714",
         search_text="self-employed unincorporated",
         freq="monthly", bucket="2", lens=None,
         concept="Self-employed, unincorporated (SA)"),

    # ---- WEEKLY -----------------------------------------------------------
    dict(key="initial_claims",   series_id="ICSA",   freq="weekly", bucket="3", lens=None,
         concept="Initial UI claims (SA)"),
    dict(key="continued_claims", series_id="CCSA",   freq="weekly", bucket="3", lens=None,
         concept="Continued UI claims / insured unemployment (SA)"),
    dict(key="initial_claims_4wk", series_id="IC4WSA", freq="weekly", bucket="3", lens=None,
         concept="Initial claims, 4-week moving average"),

    # ---- QUARTERLY --------------------------------------------------------
    dict(key="eci_total_comp", series_id="ECIALLCIV", freq="quarterly", bucket="inc", lens=None,
         concept="Employment Cost Index, total comp, all civilian (SA)"),
    # CIS1020000000000I = ECI wages & salaries, ALL CIVILIAN, SA — matches
    # eci_total_comp's universe (ECIALLCIV). The popular 'ECIWAG' is private-
    # industry only, an apples-to-oranges pair with all-civilian total comp.
    dict(key="eci_wages", series_id=None, candidate_id="CIS1020000000000I",
         search_text="employment cost index wages and salaries all civilian seasonally adjusted",
         freq="quarterly", bucket="inc", lens=None,
         concept="ECI, wages & salaries (all civilian, SA)"),
    dict(key="median_real_earnings", series_id="LES1252881600Q", freq="quarterly", bucket="inc", lens=None,
         concept="Median usual weekly real earnings, full-time"),
]

# ---------------------------------------------------------------------------
# Triangulation pairs — government vs independent for the same signal.
# Rendered as overlay charts. 'gov' / 'indep' reference column keys that exist
# after build_datasets assembles the frequency files.
# ---------------------------------------------------------------------------
TRIANGULATION = [
    dict(name="payrolls_vs_adp",
         title="Payroll employment — BLS vs ADP (independent)",
         gov=["payems", "uspriv"], indep=["adp_priv"],
         freq="monthly", note="Both are payroll-attachment counts; ADP is an independent processor read."),
    dict(name="openings_vs_postings",
         title="Labor demand — JOLTS job-openings rate (BLS) vs Indeed job postings (independent)",
         gov=["jolts_openings_rate"], indep=["indeed_total_postings"],
         freq="monthly", note="JOLTS rate (%) on left axis; Indeed postings index (Feb 2020=100) on right axis."),
    dict(name="earnings_vs_posted_wages",
         title="Wage growth — BLS avg hourly earnings (YoY) vs Indeed posted-wage growth (independent)",
         gov=["avg_hourly_earnings"], indep=["indeed_posted_wage_growth"],
         freq="monthly", note="BLS AHE converted to YoY % to match Indeed's posted-wage-growth %."),
]

# ---------------------------------------------------------------------------
# Indeed Hiring Lab (CC BY 4.0). No key. raw.githubusercontent with codeload
# tarball fallback. branch differs per repo.
# ---------------------------------------------------------------------------
INDEED_RAW = "https://raw.githubusercontent.com/hiring-lab/{repo}/{branch}/{path}"
INDEED_TARBALL = "https://codeload.github.com/hiring-lab/{repo}/tar.gz/refs/heads/{branch}"

INDEED_FILES = [
    dict(key="job_postings_aggregate", repo="job_postings_tracker", branch="master",
         path="US/aggregate_job_postings_US.csv", freq="daily",
         concept="Indeed US job postings index (total + new), SA, Feb 2020=100"),
    dict(key="job_postings_by_sector", repo="job_postings_tracker", branch="master",
         path="US/job_postings_by_sector_US.csv", freq="daily",
         concept="Indeed US job postings by occupational sector (40 sectors)"),
    dict(key="posted_wage_growth_country", repo="indeed-wage-tracker", branch="main",
         path="posted-wage-growth-by-country.csv", freq="monthly",
         concept="Indeed posted-wage growth by country (filter United States)"),
    dict(key="posted_wage_growth_sector", repo="indeed-wage-tracker", branch="main",
         path="posted-wage-growth-by-sector.csv", freq="monthly",
         concept="Indeed posted-wage growth by sector (US)"),
    dict(key="ai_postings_share", repo="ai-tracker", branch="main",
         path="AI_posting.csv", freq="daily",
         concept="Indeed share of postings mentioning AI/GenAI"),
]

# Optional geo postings (state + metro). Written to their own long files, NOT
# merged into daily.csv (too many series). Metro is ~1.4M rows / 60MB raw, so it
# is filtered to GEO_FOCUS_METROS on write.
INDEED_GEO = [
    dict(key="state_postings", repo="job_postings_tracker", branch="master",
         path="US/state_job_postings_us.csv", entity="state",
         concept="Indeed job postings index by US state"),
    dict(key="metro_postings", repo="job_postings_tracker", branch="master",
         path="US/metro_job_postings_us.csv", entity="metro",
         concept="Indeed job postings index by US metro (CBSA)"),
]
# States charted in the geo overlay (lowercase, matching Indeed's 'state' column).
GEO_FOCUS_STATES = ["ca", "tx", "ny", "fl", "wa", "dc"]
# Metro name substrings used both to subset the metro file and to chart it.
GEO_FOCUS_METROS = [
    "New York", "Los Angeles", "San Francisco", "San Jose", "Seattle",
    "Austin", "Chicago", "Dallas", "Boston", "Washington-Arlington",
]

# White-collar vs in-person sector composites built from job_postings_by_sector.
# Sector names must match Indeed's 'display_name' / sector column values.
INDEED_WHITE_COLLAR_SECTORS = [
    "Software Development", "Data & Analytics", "Banking & Finance", "Marketing",
    "Management", "Project Management", "Media & Communications", "Human Resources",
    "Accounting", "Legal",
]
INDEED_IN_PERSON_SECTORS = [
    "Nursing", "Food Preparation & Service", "Cleaning & Sanitation",
    "Childcare", "Loading & Stocking",
]

# ---------------------------------------------------------------------------
# Calculations & definitions — surfaced verbatim in the dashboard so every
# metric's formula and source series are visible. kind: 'definition' (how the
# published rate is constructed) or 'derived' (computed in this pipeline).
# ---------------------------------------------------------------------------
CALCULATIONS = [
    # --- participation / employment ratios (the denominator question) ------
    dict(kind="definition", metric="Labor force participation rate (CIVPART)",
         formula="(Employed + Unemployed, 16+) ÷ Civilian noninstitutional population 16+ × 100",
         sources="CIVPART (published). Numerator = CLF16OV; denominator = CNP16OV.",
         note="Denominator includes everyone 16+ — retirees, students, etc. Numerator counts the "
              "unemployed too. This is NOT employed ÷ total population."),
    dict(kind="definition", metric="Employment-population ratio, 16+ (EMRATIO)",
         formula="Employed (16+) ÷ Civilian noninstitutional population 16+ × 100",
         sources="EMRATIO (published). Numerator = CE16OV; denominator = CNP16OV.",
         note="Drops the unemployed from the numerator vs CIVPART; still uses the 16+ denominator."),
    dict(kind="definition", metric="Employment rate, 15-64 working age",
         formula="Employed (15-64) ÷ Population 15-64 × 100",
         sources="LREM64TTUSM156S (OECD/BLS, published).",
         note="Closest published match to 'employed ÷ 18-65 population' — a true working-age base."),
    dict(kind="definition", metric="Employment-population ratio, prime age 25-54",
         formula="Employed (25-54) ÷ Civilian noninstitutional population 25-54 × 100",
         sources="LNS12300060 (published).",
         note="The economist's standard for core working-age employment; strips out students & retirees."),
    dict(kind="definition", metric="Unemployment rates U-3 / U-6",
         formula="U-3 = Unemployed ÷ labor force × 100.  U-6 = (Unemployed + marginally attached + "
                 "part-time for economic reasons) ÷ (labor force + marginally attached) × 100",
         sources="UNRATE (U-3), U6RATE (U-6), published.", note=""),
    # --- derived in this pipeline -----------------------------------------
    dict(kind="derived", metric="U-6 minus U-3 wedge",
         formula="U6RATE − UNRATE  (percentage points)",
         sources="U6RATE, UNRATE.",
         note="Bucket-2 proxy: marginal attachment + involuntary part-time."),
    dict(kind="derived", metric="BLS avg hourly earnings, YoY %",
         formula="(AHE_t ÷ AHE_{t−12} − 1) × 100",
         sources="CES0500000003 (level, $/hr).",
         note="Converted to YoY % to compare against Indeed posted-wage growth."),
    dict(kind="derived", metric="White-collar divergence (indexed)",
         formula="series_t ÷ series_[2022-01] × 100",
         sources="USPBS, USINFO, USFIRE, PAYEMS.",
         note="Re-based to the window start so each line shows cumulative % change since 2022-01."),
    dict(kind="derived", metric="Indeed white-collar / in-person composites",
         formula="equal-weight mean of the member sectors' postings index, per day",
         sources="job_postings_by_sector_US (white-collar = Software Dev, Data & Analytics, Banking & "
                 "Finance, Marketing, Management, Project Mgmt, Media & Comms, HR, Accounting, Legal).",
         note="Indeed's own index is Feb-2020 = 100, seasonally adjusted."),
    dict(kind="derived", metric="Indeed posted-wage growth, YoY %",
         formula="posted_wage_growth_yoy (fraction) × 100",
         sources="posted-wage-growth-by-country.csv, filtered to United States.", note=""),
    dict(kind="derived", metric="Payroll levels in millions of persons",
         formula="BLS: thousands ÷ 1,000.   ADP: persons ÷ 1,000,000.",
         sources="PAYEMS, USPRIV (thousands); ADPMNUSNERSA (persons).",
         note="Unit-aligned so BLS and ADP plot at true comparable headcounts, un-indexed."),
]

# ---------------------------------------------------------------------------
# Known data caveats surfaced in the dashboard.
# ---------------------------------------------------------------------------
CAVEATS = [
    "Bucket 2 (paid-but-not-producing) is PARTLY MODELED. Business formation can't "
    "confirm a founder left a corporate job or has revenue, and there is no clean "
    "national monthly series for people drawing severance. Treat this bucket as "
    "proxied, not measured.",
    "PAYEMS carries an annual February benchmark revision (population & business "
    "establishment controls); month-to-month comparisons across the benchmark seam "
    "can shift.",
    "The Oct 2025 federal appropriations-lapse data gap is PRESERVED as NaN, not "
    "interpolated. Missing values from FRED ('.') are coerced to NaN.",
    "Sources: BLS via FRED; Census Business Formation Statistics via FRED; "
    "Indeed Hiring Lab (CC BY 4.0). New-graduate entry (NY Fed) is a separate "
    "overlay — kept in its own file, not forced into the monthly frequency file.",
    "NY Fed recent-grad series are monthly 3-month moving averages (NSA), updated "
    "quarterly. Source: NY Fed, Labor Market for Recent College Graduates.",
]
