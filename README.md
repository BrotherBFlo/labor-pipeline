# labor-pipeline — triangulated U.S. labor-market "hidden economics"

A small, reproducible pipeline that pulls U.S. labor, employment, and income time
series from **multiple independent sources**, partitions them into files **by
frequency**, builds analytical charts, and re-runs on a schedule so the view stays
current.

The point is **triangulation**: wherever a government series (BLS / Census / DOL via
FRED) and an independent series (ADP, Indeed) measure the same thing, they are charted
together so divergences are visible. No reliance on BLS alone.

## The bucket framework

The official "employed / unemployed" taxonomy collapses three populations this project
separates:

| Bucket | Meaning | Series |
|---|---|---|
| **1 — paid AND producing** | active payroll attachment | payroll employment + white-collar cut (prof & business services, information, financial activities) |
| **2 — paid but NOT producing** *(partly modeled)* | severance/salary-continuation, pivots, new ventures not yet earning | business formation, self-employment, U-6−U-3 wedge, quits rate |
| **3 — truly unemployed without pay** | | unemployment level/rate, U-6, continued UI claims |
| **secondary — the expanding workforce** | the denominator | civilian labor force level + participation rate |

> **Bucket 2 is explicitly partly modeled / proxied, not measured.** Business formation
> can't confirm a founder left a corporate job or has revenue, and there is **no clean
> national monthly series for people drawing severance**. The dashboard states this.

A **white-collar / professional lens** runs throughout: education-based unemployment
(bachelor's+), the three knowledge-work industries, and Indeed's white-collar posting
sectors. New-graduate entry (NY Fed, quarterly) is annotated as a separate overlay — not
forced into the monthly file.

## Setup

```bash
cd labor-pipeline
python3 -m venv .venv && source .venv/bin/activate
pip install requests pandas plotly python-dotenv kaleido

# secrets — paste your FRED key into .env yourself (never committed)
cp .env.example .env
# edit .env -> FRED_API_KEY=your_key_here
```

Get a free FRED API key at <https://fredaccount.stlouisfed.org/apikeys>.

### Verify your key resolves every series

```bash
python update.py --verify      # resolves all FRED IDs, writes no data
```

This prints how each ID resolved (explicit / candidate / search) and logs search-resolved
IDs to `data/_resolution_log.json`. Any 404 is resolved automatically via FRED series
search and logged.

### Run the full cycle

```bash
python update.py
```

Pulls everything, writes `data/`, regenerates `charts/`, and writes a dated dashboard to
`dashboard/` plus `dashboard/latest.html`. Open `dashboard/latest.html` in a browser.

## Outputs

```
data/
  monthly.csv  quarterly.csv  weekly.csv  daily.csv     # wide, date-indexed (core frequency partition)
  monthly_long.csv ...                                  # tidy long variants
  nyfed_recent_grads.csv                                # NY Fed new-entrant axis (separate, not merged)
  indeed_state_postings.csv  indeed_metro_postings.csv  # optional geo (long; metro = focus subset)
  sources.csv                                           # data dictionary (col -> source/id/unit/SA/bucket)
  _resolution_log.json                                  # how each FRED id resolved
  _last_values.json                                     # snapshot for the "what moved" diff
charts/   <chart>.html                                  # standalone interactive charts
dashboard/  dashboard_<date>_<time>.html, latest.html   # dated dashboard
CHANGELOG.md                                            # appended "what moved" each run
```

Each run **re-pulls full series** (does not append) so BLS benchmark / population-control
revisions flow through. FRED missing values (`.`) and gaps are coerced to NaN and **not
interpolated** — the Oct 2025 appropriations-lapse gap is preserved and marked.

## Triangulation charts (the core ask)

- **Payrolls — BLS (PAYEMS/USPRIV) vs ADP** (independent payroll processor)
- **Labor demand — JOLTS job-openings rate (BLS) vs Indeed total postings** (independent, near-real-time)
- **Wage growth — BLS avg hourly earnings YoY vs Indeed posted-wage growth** (independent)

Plus the bucket dashboard: frozen-market flows (hires/quits/layoffs), white-collar
divergence (indexed), unemployment quality incl. bachelor's+, business formation,
self-employment, U-6−U-3 wedge, weekly claims, participation vs labor force, and the
AI-postings-share overlay.

## Sources

- **FRED** (St. Louis Fed) — BLS, Census BFS, DOL/ETA, ADP. API key required.
- **Indeed Hiring Lab** — job postings, posted-wage growth, AI postings share. CC BY 4.0;
  cited on every Indeed chart. No key. Pulled from `raw.githubusercontent.com` with a
  `codeload` tarball fallback if GitHub rate-limits.
- **NY Fed** "Labor Market for Recent College Graduates" — recent-grad
  unemployment/underemployment, pulled from the published `.xlsx` (monthly 3-mo MA,
  updated quarterly). Kept in its own file `nyfed_recent_grads.csv` as the
  new-entrant axis — never merged into the core frequency partition.

## Scheduling (macOS)

Refresh cadences (so the schedule is sane):

| Series | Cadence |
|---|---|
| UI claims | weekly, Thursday ~8:30am ET |
| Payrolls (PAYEMS) | monthly, ~1st Friday |
| JOLTS | ~5-week lag |
| Business formation (BFS) | ~11–12 days after month-end |
| Indeed postings / wages | daily / weekly |
| ECI, earnings | quarterly |

**A weekly cron is a reasonable default.** Two options:

**launchd (recommended on macOS)** — copy the provided plist and load it:

```bash
cp local.labor-pipeline.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/local.labor-pipeline.plist
# runs Thursdays 09:00 local (after the weekly claims print)
```

Edit the plist's `StandardOutPath` / paths if you move the repo. Unload with
`launchctl unload ~/Library/LaunchAgents/local.labor-pipeline.plist`.

**cron** — weekly Thursday 9am:

```cron
0 9 * * 4 cd /Users/bjflo/labor-pipeline && .venv/bin/python update.py >> run.log 2>&1
```

`run.sh` wraps the venv activation so either scheduler can call a single entrypoint.
