"""
fetch_indeed.py — Indeed Hiring Lab pulls (CC BY 4.0).

raw.githubusercontent first; if GitHub rate-limits or the raw host 404s, fall
back to the codeload tarball for the whole repo and read the file out of it.

Public entry point:
  fetch_indeed_files()  -> dict[key] -> pandas.DataFrame (raw, untransformed)
"""
import io
import os
import tarfile

import requests
import pandas as pd

import config

UA = {"User-Agent": "labor-pipeline/1.0 (personal research)"}
_tarball_cache = {}  # (repo, branch) -> extracted {path: bytes}


def _token_headers():
    h = dict(UA)
    tok = os.environ.get("GITHUB_TOKEN", "").strip()
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h


def _fetch_raw(repo, branch, path):
    url = config.INDEED_RAW.format(repo=repo, branch=branch, path=path)
    r = requests.get(url, headers=_token_headers(), timeout=60)
    if r.status_code == 200:
        return r.content
    return None


def _fetch_via_tarball(repo, branch, path):
    """Download (once) the repo tarball and pull the file out of it."""
    cache_key = (repo, branch)
    if cache_key not in _tarball_cache:
        url = config.INDEED_TARBALL.format(repo=repo, branch=branch)
        r = requests.get(url, headers=_token_headers(), timeout=120)
        r.raise_for_status()
        extracted = {}
        with tarfile.open(fileobj=io.BytesIO(r.content), mode="r:gz") as tf:
            for m in tf.getmembers():
                if not m.isfile():
                    continue
                # member names are prefixed with "<repo>-<branch>/"
                rel = m.name.split("/", 1)[1] if "/" in m.name else m.name
                extracted[rel] = tf.extractfile(m).read()
        _tarball_cache[cache_key] = extracted
    return _tarball_cache[cache_key].get(path)


def fetch_indeed_files():
    """Return {key: DataFrame} for each Indeed file in the catalog."""
    out = {}
    for spec in config.INDEED_FILES:
        repo, branch, path, key = spec["repo"], spec["branch"], spec["path"], spec["key"]
        content = _fetch_raw(repo, branch, path)
        via = "raw"
        if content is None:
            try:
                content = _fetch_via_tarball(repo, branch, path)
                via = "tarball"
            except Exception as e:
                print(f"  [WARN] Indeed {key}: tarball fallback failed ({e})")
                continue
        if content is None:
            print(f"  [WARN] Indeed {key}: not found at {path} (raw + tarball both missed)")
            continue
        try:
            df = pd.read_csv(io.BytesIO(content))
        except Exception as e:
            print(f"  [WARN] Indeed {key}: parse failed ({e})")
            continue
        out[key] = df
        print(f"  [ok] indeed:{key:<28} {df.shape[0]:>5} rows x {df.shape[1]} cols  ({via})")
    return out


if __name__ == "__main__":
    files = fetch_indeed_files()
    for k, df in files.items():
        print(f"\n=== {k} ===")
        print(df.head(3).to_string())
        print("cols:", list(df.columns))
