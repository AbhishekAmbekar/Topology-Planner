"""
data_prep.py
Week 1 pipeline for the Tennessee and South Carolina topology project.

What it does:
  1. Pulls ACS 5 year data by ZIP (ZCTA) from the Census API
  2. Downloads the ZCTA to county relationship file and keeps TN (47) and SC (45)
  3. Downloads the Gazetteer ZCTA file for coordinates and land area
  4. Joins everything, drops small ZIPs, builds density and demand proxy
  5. Tags each ZIP with a metro group
  6. Picks candidate sites with demand weighted k-means, one run per state
  7. Builds the ZIP by site distance matrix (haversine x circuity factor)

Setup:
  pip install pandas numpy requests scikit-learn
  export CENSUS_API_KEY=your_key_here      (Windows PowerShell: $env:CENSUS_API_KEY="your_key")

Run from the repo root:
  python src/data_prep.py
"""
import io
import os
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from sklearn.cluster import KMeans

# ------------------------------------------------------------------
# SETTINGS. Every number here goes in your assumptions doc.
# ------------------------------------------------------------------
ACS_YEAR = 2023            # try 2024 first if the API accepts it
GAZ_YEAR = 2023            # Gazetteer vintage
STATES = {"47": "TN", "45": "SC"}
MIN_HOUSEHOLDS = 500       # placeholder threshold for dropping tiny ZIPs
SITES_PER_STATE = {"TN": 16, "SC": 12}   # placeholder, 28 candidate sites total
CIRCUITY = 1.3             # road distance = straight line x 1.3
METRO_RADIUS_MI = 40       # ZIP is tagged to a metro if within this many miles
INCOME_INDEX_CLIP = (0.6, 1.6)
RANDOM_SEED = 42

# Density tiers (households per square mile) and their demand multipliers.
DENSITY_BINS = [0, 100, 500, 1500, np.inf]
DENSITY_FACTORS = [0.8, 1.0, 1.15, 1.3]

ANCHORS = {   # metro name: (lat, lon)
    "Nashville": (36.1627, -86.7816),
    "Memphis": (35.1495, -90.0490),
    "Knoxville": (35.9606, -83.9207),
    "Chattanooga": (35.0456, -85.3097),
    "Tri-Cities TN": (36.3134, -82.3535),
    "Greenville-Spartanburg": (34.8526, -82.3940),
    "Columbia SC": (34.0007, -81.0348),
    "Charleston": (32.7765, -79.9311),
    "Myrtle Beach": (33.6891, -78.8867),
    "York County SC": (34.9249, -81.0251),
}

RAW = Path("data/raw")
OUT = Path("data/processed")

REL_URL = ("https://www2.census.gov/geo/docs/maps-data/data/rel2020/zcta520/"
           "tab20_zcta520_county20_natl.txt")


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------
def haversine_miles(lat1, lon1, lat2, lon2):
    """Straight line distance in miles. Works with numpy broadcasting."""
    r = 3958.8
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi = p2 - p1
    dlmb = np.radians(lon2) - np.radians(lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlmb / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(a))


# ------------------------------------------------------------------
# Step 2: ACS data
# ------------------------------------------------------------------
def get_acs():
    path = RAW / f"acs_{ACS_YEAR}.csv"
    if path.exists():
        return pd.read_csv(path, dtype={"zcta": str})
    key = os.environ.get("CENSUS_API_KEY")
    if not key:
        raise SystemExit("Set the CENSUS_API_KEY environment variable first.")
    url = f"https://api.census.gov/data/{ACS_YEAR}/acs/acs5"
    params = {
        "get": "B01003_001E,B11001_001E,B19013_001E",
        "for": "zip code tabulation area:*",
        "key": key,
    }
    r = requests.get(url, params=params, timeout=180)
    r.raise_for_status()
    rows = r.json()
    df = pd.DataFrame(rows[1:], columns=rows[0])
    df = df.rename(columns={
        "B01003_001E": "population",
        "B11001_001E": "households",
        "B19013_001E": "median_income",
        "zip code tabulation area": "zcta",
    })
    for c in ["population", "households", "median_income"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
        df[c] = df[c].where(df[c] >= 0)   # Census uses -666666666 for missing
    df = df[["zcta", "population", "households", "median_income"]]
    df.to_csv(path, index=False)
    return df


# ------------------------------------------------------------------
# Step 3: ZCTA to county relationship file, filter to TN and SC
# ------------------------------------------------------------------
def get_rel():
    path = RAW / "zcta_county_rel.txt"
    if not path.exists():
        r = requests.get(REL_URL, timeout=300)
        r.raise_for_status()
        path.write_bytes(r.content)
    rel = pd.read_csv(path, sep="|", dtype=str, encoding="utf-8-sig")
    rel = rel.dropna(subset=["GEOID_ZCTA5_20", "GEOID_COUNTY_20"]).copy()
    rel["AREALAND_PART"] = pd.to_numeric(rel["AREALAND_PART"], errors="coerce")
    # A ZIP can touch several counties. Keep the county with the most land.
    rel = rel.sort_values("AREALAND_PART", ascending=False)
    rel = rel.drop_duplicates("GEOID_ZCTA5_20")
    out = rel[["GEOID_ZCTA5_20", "GEOID_COUNTY_20", "NAMELSAD_COUNTY_20"]].copy()
    out.columns = ["zcta", "county_fips", "county_name"]
    out["state_fips"] = out["county_fips"].str[:2]
    return out[out["state_fips"].isin(STATES)].copy()


# ------------------------------------------------------------------
# Step 4: Gazetteer file
# ------------------------------------------------------------------
def get_gaz():
    path = RAW / f"gaz_zcta_{GAZ_YEAR}.txt"
    if not path.exists():
        url = ("https://www2.census.gov/geo/docs/maps-data/data/gazetteer/"
               f"{GAZ_YEAR}_Gazetteer/{GAZ_YEAR}_Gaz_zcta_national.zip")
        r = requests.get(url, timeout=300)
        r.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            path.write_bytes(z.read(z.namelist()[0]))
    g = pd.read_csv(path, sep="\t", dtype={"GEOID": str})
    g.columns = g.columns.str.strip()   # the last column name has trailing spaces
    g = g.rename(columns={"GEOID": "zcta", "ALAND_SQMI": "land_sqmi",
                          "INTPTLAT": "lat", "INTPTLONG": "lon"})
    return g[["zcta", "land_sqmi", "lat", "lon"]]


# ------------------------------------------------------------------
# Steps 5 and 6: join, threshold, density, demand proxy, metro tag
# ------------------------------------------------------------------
def build_table():
    acs, rel, gaz = get_acs(), get_rel(), get_gaz()
    df = rel.merge(acs, on="zcta", how="left").merge(gaz, on="zcta", how="left")
    df["state"] = df["state_fips"].map(STATES)
    n_start = len(df)

    df = df.dropna(subset=["lat", "lon", "households"])
    df = df[df["land_sqmi"] > 0]
    n_after_missing = len(df)

    keep = df["households"] >= MIN_HOUSEHOLDS
    n_dropped_small = int((~keep).sum())
    hh_dropped = float(df.loc[~keep, "households"].sum())
    hh_total = float(df["households"].sum())
    df = df[keep].copy()

    # Income index: ZIP income vs the median ZIP income in its state.
    state_median = df.groupby("state")["median_income"].transform("median")
    df["median_income"] = df["median_income"].fillna(state_median)
    df["income_index"] = (df["median_income"] / state_median).clip(*INCOME_INDEX_CLIP)

    df["density"] = df["households"] / df["land_sqmi"]
    df["density_factor"] = pd.cut(
        df["density"], bins=DENSITY_BINS, labels=DENSITY_FACTORS, right=False
    ).astype(float)

    df["demand"] = df["households"] * df["income_index"] * df["density_factor"]

    # Metro tag
    names = list(ANCHORS)
    d = np.column_stack([
        haversine_miles(df["lat"].values, df["lon"].values, ANCHORS[n][0], ANCHORS[n][1])
        for n in names
    ])
    nearest = d.argmin(axis=1)
    df["metro"] = np.where(d.min(axis=1) <= METRO_RADIUS_MI,
                           np.array(names)[nearest], "Other")

    df = df.sort_values(["state", "zcta"]).reset_index(drop=True)
    cols = ["zcta", "state", "metro", "county_name", "lat", "lon", "population",
            "households", "median_income", "income_index", "land_sqmi", "density",
            "density_factor", "demand"]
    df = df[cols]

    log = [
        f"ZIPs in TN and SC from relationship file: {n_start}",
        f"Dropped for missing ACS or coordinates: {n_start - n_after_missing}",
        f"Dropped for under {MIN_HOUSEHOLDS} households: {n_dropped_small}",
        f"Share of households dropped by threshold: {hh_dropped / hh_total:.2%}",
        f"ZIPs kept: {len(df)}",
    ]
    return df, log


# ------------------------------------------------------------------
# Step 7: candidate sites and distance matrix
# ------------------------------------------------------------------
def make_sites(df):
    rows = []
    for st, k in SITES_PER_STATE.items():
        sub = df[df["state"] == st].reset_index(drop=True)
        km = KMeans(n_clusters=k, n_init=10, random_state=RANDOM_SEED)
        km.fit(sub[["lat", "lon"]], sample_weight=sub["demand"])
        for c in range(k):
            members = sub[km.labels_ == c]
            if members.empty:
                continue
            cen = km.cluster_centers_[c]
            dist = haversine_miles(members["lat"].values, members["lon"].values,
                                   cen[0], cen[1])
            pick = members.iloc[int(dist.argmin())]
            rows.append({
                "site_id": f"{st}-{c + 1:02d}", "state": st, "zcta": pick["zcta"],
                "lat": pick["lat"], "lon": pick["lon"], "metro": pick["metro"],
            })
    return pd.DataFrame(rows)


def distance_matrix(df, sites):
    d = haversine_miles(
        df["lat"].values[:, None], df["lon"].values[:, None],
        sites["lat"].values[None, :], sites["lon"].values[None, :],
    ) * CIRCUITY
    return pd.DataFrame(d, index=df["zcta"].values, columns=sites["site_id"].values)


# ------------------------------------------------------------------
def main():
    RAW.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)

    df, log = build_table()
    sites = make_sites(df)
    dm = distance_matrix(df, sites)

    df.to_csv(OUT / "zip_table.csv", index=False)
    sites.to_csv(OUT / "candidate_sites.csv", index=False)
    dm.to_csv(OUT / "distance_matrix.csv")

    # Sanity check: assign every ZIP to its nearest site (a rough baseline).
    nearest_miles = dm.min(axis=1).values
    w = df["demand"].values
    log += [
        f"Candidate sites: {len(sites)}",
        f"Demand weighted average distance to nearest site: "
        f"{np.average(nearest_miles, weights=w):.1f} miles (circuity included)",
        f"Longest nearest site distance: {nearest_miles.max():.1f} miles",
    ]
    (OUT / "prep_log.txt").write_text("\n".join(log))
    print("\n".join(log))
    print("\nZIPs by metro:")
    print(df["metro"].value_counts().to_string())


if __name__ == "__main__":
    main()
