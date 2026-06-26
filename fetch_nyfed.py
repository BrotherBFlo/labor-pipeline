"""
fetch_nyfed.py — NY Fed "Labor Market for Recent College Graduates".

The new-entrant axis. NOT on FRED. Published as a single .xlsx (updated quarterly;
the series themselves are monthly 3-month moving averages back to 1990). Kept in
its own file — never forced into the core monthly frequency partition.

Sheets used: 'unemployed' and 'underemployed'. Header row is "Date, Young workers,
All workers, Recent graduates, College graduates" (underemployed: recent/college only).

fetch_nyfed() -> (wide DataFrame indexed by date, list[dict] dictionary rows) or (None, []).
"""
import io

import requests
import pandas as pd

import config

URL = ("https://www.newyorkfed.org/medialibrary/Research/Interactives/Data/"
       "college-labor-market/College-labor-data")
# NY Fed 403s a default python UA; a browser UA is required.
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"}

# sheet -> {source column -> output column}
_MAP = {
    "unemployed": {
        "Recent graduates": "nyfed_recent_grad_unemp",
        "College graduates": "nyfed_college_grad_unemp",
        "Young workers": "nyfed_young_worker_unemp",
        "All workers": "nyfed_all_worker_unemp",
    },
    "underemployed": {
        "Recent graduates": "nyfed_recent_grad_underemp",
        "College graduates": "nyfed_college_grad_underemp",
    },
}


def _read_sheet(content, sheet):
    # header sits at row index 10 (0-based) -> skip the 10 branding/blank rows above
    df = pd.read_excel(io.BytesIO(content), sheet_name=sheet, skiprows=10, engine="openpyxl")
    df = df.rename(columns={df.columns[0]: "date"})
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    return df.dropna(subset=["date"]).set_index("date")


def fetch_nyfed(start=None):
    start = start or config.OBSERVATION_START
    try:
        r = requests.get(URL, headers=UA, timeout=90)
        r.raise_for_status()
    except Exception as e:
        print(f"  [WARN] NY Fed pull failed ({e}); new-entrant overlay skipped this run")
        return None, []
    content = r.content

    cols = {}
    rows = []
    for sheet, mapping in _MAP.items():
        try:
            df = _read_sheet(content, sheet)
        except Exception as e:
            print(f"  [WARN] NY Fed sheet '{sheet}' parse failed ({e})")
            continue
        for src, out in mapping.items():
            if src in df.columns:
                cols[out] = pd.to_numeric(df[src], errors="coerce")
                kind = "unemployment" if sheet == "unemployed" else "underemployment"
                rows.append(dict(
                    column=out, source="NY Fed (Labor Market for Recent College Graduates)",
                    series_id=f"{sheet}:{src}", concept=f"{src} {kind} rate (NY Fed)",
                    unit="percent", seasonal_adjustment="NSA (3-mo moving avg)",
                    bucket="new_entrant", lens="white_collar" if "grad" in out else "",
                    derived="no",
                ))
    if not cols:
        return None, []
    wide = pd.DataFrame(cols).sort_index()
    wide = wide[wide.index >= pd.Timestamp(start)]
    print(f"  [ok] nyfed recent-grad overlay     {wide.shape[1]} series x {len(wide)} months")
    return wide, rows


if __name__ == "__main__":
    w, rows = fetch_nyfed()
    if w is not None:
        print(w.tail(4).to_string())
