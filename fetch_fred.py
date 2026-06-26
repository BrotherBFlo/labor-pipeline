"""
fetch_fred.py — FRED REST pulls + search-resolve fallback + authoritative metadata.

Public entry points:
  load_api_key()                 -> str   (from .env / environment; friendly error)
  resolve_series(spec, key)      -> dict  (resolved id + metadata, with logging)
  fetch_series_frame(id, key)    -> pandas.Series indexed by date (NaN-coerced)
  fetch_all(key)                 -> (frames: dict[key]->Series, meta: dict[key]->dict, log: list)

Run directly to verify every catalog ID against your key:
  python fetch_fred.py            # resolves + prints a table, no data files written
"""
import os
import sys
import time
import json

import requests

import config

UA = {"User-Agent": "labor-pipeline/1.0 (personal research)"}


# ---------------------------------------------------------------------------
# Key handling
# ---------------------------------------------------------------------------
def load_api_key():
    """Read FRED_API_KEY from .env (via python-dotenv) or the environment."""
    try:
        from dotenv import load_dotenv
        load_dotenv(config.ROOT / ".env")
    except Exception:
        pass
    key = os.environ.get("FRED_API_KEY", "").strip()
    if not key:
        sys.exit(
            "\nFRED_API_KEY is not set.\n"
            "  1. cp .env.example .env\n"
            "  2. paste your key after FRED_API_KEY= in .env\n"
            "  3. re-run.\n"
            "(.env is gitignored — your key never gets committed.)\n"
        )
    return key


# ---------------------------------------------------------------------------
# Low-level GET with light rate-limiting + retry
# ---------------------------------------------------------------------------
_MIN_INTERVAL = 60.0 / config.FRED_RATE_LIMIT_PER_MIN  # seconds between calls
_last_call = [0.0]


def _get(path, params, key, tries=4):
    params = {**params, "api_key": key, "file_type": "json"}
    url = f"{config.FRED_BASE}/{path}"
    for attempt in range(tries):
        # throttle
        wait = _MIN_INTERVAL - (time.monotonic() - _last_call[0])
        if wait > 0:
            time.sleep(wait)
        _last_call[0] = time.monotonic()
        try:
            r = requests.get(url, params=params, headers=UA, timeout=30)
        except requests.RequestException as e:
            if attempt == tries - 1:
                raise
            time.sleep(2 ** attempt)
            continue
        if r.status_code == 200:
            return r.json()
        if r.status_code == 404:
            return {"_status": 404, "_text": r.text}
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(2 ** attempt)
            continue
        # 400 etc — return body so caller can log the FRED error message
        return {"_status": r.status_code, "_text": r.text}
    return {"_status": "exhausted"}


# ---------------------------------------------------------------------------
# Metadata + search + observations
# ---------------------------------------------------------------------------
def get_metadata(series_id, key):
    """Authoritative series metadata: title, units, SA, frequency, last_updated."""
    js = _get("series", {"series_id": series_id}, key)
    if "_status" in js:
        return None
    items = js.get("seriess") or []
    if not items:
        return None
    s = items[0]
    return dict(
        series_id=s.get("id"),
        title=s.get("title"),
        units=s.get("units"),
        units_short=s.get("units_short"),
        seasonal_adjustment=s.get("seasonal_adjustment"),
        seasonal_adjustment_short=s.get("seasonal_adjustment_short"),
        frequency=s.get("frequency"),
        frequency_short=s.get("frequency_short"),
        last_updated=s.get("last_updated"),
        observation_start=s.get("observation_start"),
        observation_end=s.get("observation_end"),
    )


def search_series(text, key, limit=8):
    js = _get("series/search",
              {"search_text": text, "limit": limit,
               "order_by": "popularity", "sort_order": "desc"}, key)
    if "_status" in js:
        return []
    return js.get("seriess") or []


def resolve_series(spec, key, log):
    """
    Resolve a catalog entry to a concrete FRED series_id + metadata.
    Strategy: explicit id -> candidate_id -> search. Everything logged.
    Returns metadata dict (with 'resolved_via') or None.
    """
    label = spec["key"]

    # 1. explicit id
    sid = spec.get("series_id")
    if sid:
        meta = get_metadata(sid, key)
        if meta:
            log.append(dict(key=label, series_id=sid, resolved_via="explicit", title=meta["title"]))
            meta["resolved_via"] = "explicit"
            return meta
        log.append(dict(key=label, series_id=sid, resolved_via="explicit-FAILED",
                        title="(404 — falling back)"))

    # 2. candidate id
    cand = spec.get("candidate_id")
    if cand:
        meta = get_metadata(cand, key)
        if meta:
            log.append(dict(key=label, series_id=cand, resolved_via="candidate", title=meta["title"]))
            meta["resolved_via"] = "candidate"
            return meta
        log.append(dict(key=label, series_id=cand, resolved_via="candidate-FAILED",
                        title="(404 — searching)"))

    # 3. search
    text = spec.get("search_text")
    if text:
        hits = search_series(text, key)
        if hits:
            top = hits[0]
            sid = top["id"]
            meta = get_metadata(sid, key)
            if meta:
                meta["resolved_via"] = f"search('{text}')"
                log.append(dict(key=label, series_id=sid, resolved_via=f"search",
                                title=meta["title"],
                                search_text=text,
                                alternatives=[h["id"] for h in hits[1:5]]))
                return meta

    log.append(dict(key=label, series_id=spec.get("series_id") or spec.get("candidate_id"),
                    resolved_via="UNRESOLVED", title="(could not resolve)"))
    return None


def fetch_series_frame(series_id, key, start=None):
    """Return a pandas Series indexed by date. FRED '.' -> NaN. No interpolation."""
    import pandas as pd
    start = start or config.OBSERVATION_START
    js = _get("series/observations",
              {"series_id": series_id, "observation_start": start}, key)
    if "_status" in js:
        return pd.Series(dtype="float64", name=series_id)
    rows = js.get("observations") or []
    idx, vals = [], []
    for o in rows:
        idx.append(pd.Timestamp(o["date"]))
        v = o["value"]
        vals.append(float("nan") if v in (".", "", None) else float(v))
    return pd.Series(vals, index=pd.DatetimeIndex(idx), name=series_id, dtype="float64")


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def fetch_all(key, start=None):
    """Resolve every catalog entry, pull observations. Returns (frames, meta, log)."""
    frames, meta, log = {}, {}, []
    for spec in config.FRED_SERIES:
        m = resolve_series(spec, key, log)
        if not m:
            print(f"  [WARN] could not resolve {spec['key']} — skipping")
            continue
        s = fetch_series_frame(m["series_id"], key, start=start)
        frames[spec["key"]] = s
        meta[spec["key"]] = {**spec, **m}
        print(f"  [ok] {spec['key']:<28} {m['series_id']:<16} "
              f"{len(s):>4} obs  ({m['resolved_via']})")
    return frames, meta, log


def _verify_only():
    """python fetch_fred.py — resolve all IDs, print a table, write no data."""
    key = load_api_key()
    print(f"Verifying {len(config.FRED_SERIES)} FRED series against your key...\n")
    log = []
    for spec in config.FRED_SERIES:
        resolve_series(spec, key, log)
    print(f"\n{'key':<30}{'series_id':<18}{'how':<14}title")
    print("-" * 100)
    searched, unresolved = [], []
    for e in log:
        if e["resolved_via"].startswith("search"):
            searched.append(e)
        if e["resolved_via"] == "UNRESOLVED" or "FAILED" in e["resolved_via"]:
            if e["resolved_via"] == "UNRESOLVED":
                unresolved.append(e)
        print(f"{e['key']:<30}{str(e['series_id']):<18}{e['resolved_via']:<14}{e.get('title','')[:50]}")
    if searched:
        print("\nSearch-resolved (logged for your records):")
        for e in searched:
            print(f"  - {e['key']}: used {e['series_id']}  "
                  f"(query: \"{e.get('search_text','')}\"; "
                  f"alternatives: {', '.join(e.get('alternatives', [])) or 'none'})")
    if unresolved:
        print("\n[!] UNRESOLVED — need attention:")
        for e in unresolved:
            print(f"  - {e['key']}")
    else:
        print("\nAll series resolved. ✓")
    # persist the resolution log
    (config.DATA_DIR / "_resolution_log.json").write_text(json.dumps(log, indent=2))
    print(f"\nResolution log written to {config.DATA_DIR / '_resolution_log.json'}")


if __name__ == "__main__":
    _verify_only()
