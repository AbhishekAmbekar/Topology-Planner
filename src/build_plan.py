"""
build_plan.py
Week 3: growth scenarios and a year by year build plan.

What it does:
  1. Downloads Census county population estimates and works out each county's growth rate
  2. Gives every ZIP the growth rate of its county
  3. Starts from the Week 2 optimized network as the "network we have today" (Year 0)
  4. Keeps a 90 percent safety buffer on every station, as real planners do
  5. For each scenario, steps through Years 1 to 5. Each year it decides
     which new sites to open and which ZIPs each station serves.
  6. Saves a build schedule, a yearly summary, and a chart

Run from the repo root (optimize.py must be in the same src folder):
  python src/build_plan.py
"""
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
from scipy import sparse
from scipy.optimize import Bounds, LinearConstraint, milp

sys.path.insert(0, str(Path(__file__).resolve().parent))
from optimize import BASE, load_data   # reuse the Week 2 settings and data loader

PROC = Path("data/processed")
RAW = Path("data/raw")
OUT = Path("outputs")

# ------------------------------------------------------------------
# SETTINGS. All placeholders. They go in your assumptions doc.
# ------------------------------------------------------------------
HORIZON = 5                      # years to plan
LAUNCHES_PER_YEAR = 2            # most new sites that can open in one year (stands in for budget)
HEADROOM = 0.90                  # safety buffer: a station counts as "full" at 90% of its capacity
OVERFLOW_PENALTY_MILES = 150     # cost of demand above a station's buffered capacity
GROWTH_CLIP = (-0.01, 0.05)      # keep county growth rates between -1% and +5% a year

SCENARIOS = {
    # growth_mult: multiplies the county growth rate
    # ecom: extra yearly volume growth per household (online shopping trend)
    # lead: first year a new site can open
    "Base": {"growth_mult": 1.0, "ecom": 0.02, "lead": 1},
    "High growth": {"growth_mult": 1.5, "ecom": 0.04, "lead": 1},
    "Delayed launches": {"growth_mult": 1.0, "ecom": 0.02, "lead": 3},
    "High growth, delayed": {"growth_mult": 1.5, "ecom": 0.04, "lead": 3},
}

POP_URLS = [
    "https://www2.census.gov/programs-surveys/popest/datasets/2020-2025/counties/totals/co-est2025-alldata.csv",
    "https://www2.census.gov/programs-surveys/popest/datasets/2020-2024/counties/totals/co-est2024-alldata.csv",
]
STATE_FIPS = ["45", "47"]


# ------------------------------------------------------------------
# Step 1: county growth
# ------------------------------------------------------------------
def get_county_growth():
    path = RAW / "county_pop_estimates.csv"
    if not path.exists():
        for url in POP_URLS:
            try:
                r = requests.get(url, timeout=300)
                r.raise_for_status()
                path.write_bytes(r.content)
                print("Downloaded:", url)
                break
            except Exception as e:
                print(f"Could not download {url}: {e}")
        else:
            raise SystemExit(
                "Could not download the county file. Download it in your browser from the "
                "Census 'County Population Totals and Components of Change: 2020-2025' page "
                "(the CO-EST2025-ALLDATA csv) and save it as data/raw/county_pop_estimates.csv")
    df = pd.read_csv(path, encoding="latin-1", dtype={"STATE": str, "COUNTY": str})
    df = df[pd.to_numeric(df["SUMLEV"], errors="coerce") == 50].copy()   # county rows only
    df["state_fips"] = df["STATE"].str.zfill(2)
    df["county_fips"] = df["state_fips"] + df["COUNTY"].str.zfill(3)
    df = df[df["state_fips"].isin(STATE_FIPS)].copy()

    years = sorted(int(c[11:]) for c in df.columns if c.startswith("POPESTIMATE"))
    latest = years[-1]
    df["pop2020"] = pd.to_numeric(df["POPESTIMATE2020"])
    df["pop_latest"] = pd.to_numeric(df[f"POPESTIMATE{latest}"])
    df["cagr"] = (df["pop_latest"] / df["pop2020"]) ** (1 / (latest - 2020)) - 1
    cols = ["county_fips", "state_fips", "CTYNAME", "pop2020", "pop_latest", "cagr"]
    return df[cols].reset_index(drop=True), latest


def zip_growth(zips):
    rel = pd.read_csv(RAW / "zcta_county_rel.txt", sep="|", dtype=str, encoding="utf-8-sig")
    rel = rel.dropna(subset=["GEOID_ZCTA5_20", "GEOID_COUNTY_20"]).copy()
    rel["AREALAND_PART"] = pd.to_numeric(rel["AREALAND_PART"], errors="coerce")
    rel = rel.sort_values("AREALAND_PART", ascending=False).drop_duplicates("GEOID_ZCTA5_20")
    rel = rel[["GEOID_ZCTA5_20", "GEOID_COUNTY_20"]]
    rel.columns = ["zcta", "county_fips"]

    cg, latest = get_county_growth()
    m = zips[["zcta", "state", "metro"]].merge(rel, on="zcta", how="left")
    m = m.merge(cg[["county_fips", "CTYNAME", "cagr"]], on="county_fips", how="left")
    n_missing = int(m["cagr"].isna().sum())
    m["cagr"] = m["cagr"].fillna(m.groupby("state")["cagr"].transform("median"))
    m["cagr"] = m["cagr"].fillna(cg["cagr"].median()).clip(*GROWTH_CLIP)
    return m, cg, latest, n_missing


# ------------------------------------------------------------------
# One year of planning
# ------------------------------------------------------------------
def solve_year(demand, dist, cap, fixed, forced, can_open, max_new, p):
    """forced: sites already open (they stay open). can_open: sites allowed to open now."""
    n, m = dist.shape
    available = forced | can_open
    ii, jj = np.where((dist <= p["radius"]) & available[None, :])
    P = len(ii)

    has_site = np.zeros(n, dtype=bool)
    has_site[ii] = True
    forced_share = demand[~has_site].sum() / demand.sum()
    allowed = max(1 - p["min_coverage"], forced_share + 0.0005)

    # Variable order: y (open, m), x (ZIP to site, P), u (unserved, n), o (overflow, m)
    nv = m + P + n + m
    x_idx = m + np.arange(P)
    u_idx = m + P + np.arange(n)
    o_idx = m + P + n + np.arange(m)
    c = np.concatenate([
        np.full(m, fixed),
        demand[ii] * dist[ii, jj],
        p["penalty_miles"] * demand,
        np.full(m, float(OVERFLOW_PENALTY_MILES)),
    ])

    r1 = sparse.coo_matrix(
        (np.ones(P + n), (np.concatenate([ii, np.arange(n)]), np.concatenate([x_idx, u_idx]))),
        shape=(n, nv))
    r2 = sparse.coo_matrix(
        (np.concatenate([np.ones(P), -np.ones(P)]),
         (np.concatenate([np.arange(P), np.arange(P)]), np.concatenate([x_idx, jj]))),
        shape=(P, nv))
    r3 = sparse.coo_matrix(
        (np.concatenate([demand[ii], np.full(m, -cap), -np.ones(m)]),
         (np.concatenate([jj, np.arange(m), np.arange(m)]),
          np.concatenate([x_idx, np.arange(m), o_idx]))),
        shape=(m, nv))
    r4 = sparse.coo_matrix((demand, (np.zeros(n, dtype=int), u_idx)), shape=(1, nv))
    new_cols = np.where(~forced)[0]
    r5 = sparse.coo_matrix((np.ones(len(new_cols)), (np.zeros(len(new_cols), dtype=int), new_cols)),
                           shape=(1, nv))

    cons = [
        LinearConstraint(r1.tocsr(), 1, 1),
        LinearConstraint(r2.tocsr(), -np.inf, 0),
        LinearConstraint(r3.tocsr(), -np.inf, 0),
        LinearConstraint(r4.tocsr(), -np.inf, allowed * demand.sum()),
        LinearConstraint(r5.tocsr(), 0, max_new),
    ]
    lb = np.zeros(nv)
    ub = np.ones(nv)
    ub[o_idx] = np.inf
    lb[:m][forced] = 1
    ub[:m][~available] = 0
    integrality = np.concatenate([np.ones(m + P), np.zeros(n + m)])

    res = milp(c, constraints=cons, integrality=integrality, bounds=Bounds(lb, ub),
               options={"time_limit": p["time_limit"], "mip_rel_gap": 0.01})
    if res.x is None:
        raise SystemExit("The solver found no solution for one year. Try a larger radius.")
    open_mask = res.x[:m] > 0.5
    assign = np.full(n, -1, dtype=int)
    chosen = res.x[m:m + P] > 0.5
    assign[ii[chosen]] = jj[chosen]
    return open_mask, assign


def year_metrics(demand, dist, cap, open_mask, assign, prev_open, total0, radius):
    n = len(demand)
    served = assign >= 0
    d = np.zeros(n)
    d[served] = dist[np.arange(n)[served], assign[served]]
    load = np.zeros(dist.shape[1])
    np.add.at(load, assign[served], demand[served])
    util = load / cap
    covered = served & (d <= radius + 1e-9)
    return {
        "demand_index": round(100 * demand.sum() / total0),
        "sites_open": int(open_mask.sum()),
        "new_sites": int((open_mask & ~prev_open).sum()),
        "avg_miles": round(float((demand[served] * d[served]).sum() / demand[served].sum()), 1),
        "busiest_pct_of_target": round(float(util[open_mask].max() * 100)),
        "sites_over_target": int((util > 1.0001).sum()),
        "demand_over_target_pct": round(100 * float(np.maximum(load - cap, 0).sum()) / demand.sum(), 1),
        "covered_demand_pct": round(100 * float(demand[covered].sum()) / demand.sum(), 1),
    }


def run_scenario(name, sc, zips, dist, start_open, cagr, p):
    demand0 = zips["demand"].values
    total0 = demand0.sum()
    cap_full = p["capacity_share"] * total0             # Week 2 capacity, fixed over time
    fixed = p["fixed_cost_miles"] * cap_full
    cap = HEADROOM * cap_full                           # buffered capacity used for planning
    growth = sc["growth_mult"] * cagr + sc["ecom"]
    m = dist.shape[1]

    open_prev = start_open.copy()
    rows, opened = [], []
    for t in range(HORIZON + 1):
        demand = demand0 * (1 + growth) ** t
        can_open = np.zeros(m, dtype=bool)
        if t >= 1 and t >= sc["lead"]:
            can_open = ~open_prev
        o, a = solve_year(demand, dist, cap, fixed, open_prev, can_open, LAUNCHES_PER_YEAR, p)
        met = year_metrics(demand, dist, cap, o, a, open_prev, total0, p["radius"])
        met.update({"scenario": name, "year": t})
        rows.append(met)
        for j in np.where(o & ~open_prev)[0]:
            opened.append((int(j), t))
        open_prev = o
    return pd.DataFrame(rows), opened


# ------------------------------------------------------------------
def main():
    OUT.mkdir(exist_ok=True)
    zips, sites, dist = load_data()
    so = pd.read_csv(PROC / "sites_opened.csv")
    assert list(so["site_id"]) == list(sites["site_id"]), "sites_opened.csv does not match candidate_sites.csv"
    start_open = so["opened_optimized"].astype(str).str.lower().eq("true").values

    gz, cg, latest, n_missing = zip_growth(zips)
    gz.to_csv(PROC / "zip_growth.csv", index=False)
    cg.to_csv(PROC / "county_growth.csv", index=False)
    cagr = gz["cagr"].values

    print(f"County estimates run from 2020 to {latest}.")
    print(f"ZIPs with no county match (filled with the state median): {n_missing}")
    print(f"Starting network: {int(start_open.sum())} open sites (the Week 2 optimized layout)")
    print(f"Safety buffer: a station counts as full at {HEADROOM:.0%} of its Week 2 capacity.")
    print("In the tables below, 100 means a station is at that 90% target.")
    print("\nFastest growing counties (yearly growth):")
    top = cg.sort_values("cagr", ascending=False).head(8)
    for _, r in top.iterrows():
        print(f"  {r['CTYNAME']:<22} {r['cagr'] * 100:4.1f}%")
    print(f"Median county growth: {cg['cagr'].median() * 100:.1f}% a year\n")

    all_rows, all_opened = [], {}
    for name, sc in SCENARIOS.items():
        print(f"Running scenario: {name} ...")
        df, opened = run_scenario(name, sc, zips, dist, start_open, cagr, BASE)
        all_rows.append(df)
        all_opened[name] = opened

    summary = pd.concat(all_rows, ignore_index=True)
    cols = ["scenario", "year", "demand_index", "sites_open", "new_sites", "avg_miles",
            "busiest_pct_of_target", "sites_over_target", "demand_over_target_pct",
            "covered_demand_pct"]
    summary = summary[cols]
    summary.to_csv(OUT / "scenario_summary.csv", index=False)

    for name in SCENARIOS:
        print(f"\n=== {name} ===")
        print(summary[summary["scenario"] == name].drop(columns="scenario").to_string(index=False))

    # Build schedule: which site opens in which year, per scenario
    sched = sites[["site_id", "zcta", "state", "metro"]].copy()
    for name in SCENARIOS:
        yr = {j: t for j, t in all_opened[name]}
        sched[name] = [f"Year {yr[j]}" if j in yr else "" for j in range(len(sites))]
    sched = sched[sched[list(SCENARIOS)].ne("").any(axis=1)]
    sched.to_csv(OUT / "build_schedule.csv", index=False)
    print("\nBuild schedule (year each new site opens):")
    print(sched.to_string(index=False) if len(sched) else "No new sites needed in any scenario.")

    sets = [set(j for j, _ in all_opened[n]) for n in SCENARIOS]
    safe = set.intersection(*sets) if sets else set()
    print("\nSites that open in ALL scenarios (safe bets):",
          ", ".join(sites["site_id"][j] for j in sorted(safe)) or "none")

    # Chart
    fig, axes = plt.subplots(1, 3, figsize=(16, 4.5))
    panels = [("sites_open", "Sites open"),
              ("busiest_pct_of_target", "Busiest station (% of 90% target)"),
              ("demand_over_target_pct", "Demand above the 90% target (%)")]
    for ax, (col, title) in zip(axes, panels):
        for name in SCENARIOS:
            s = summary[summary["scenario"] == name]
            ax.plot(s["year"], s[col], marker="o", label=name)
        ax.set_title(title)
        ax.set_xlabel("Year")
        ax.grid(alpha=0.3)
    axes[1].axhline(100, color="red", linestyle="--", linewidth=1)   # the 90% target
    axes[0].legend()
    fig.savefig(OUT / "build_plan.png", dpi=150, bbox_inches="tight")
    print("\nSaved: outputs/scenario_summary.csv, outputs/build_schedule.csv, outputs/build_plan.png,")
    print("       data/processed/county_growth.csv, data/processed/zip_growth.csv")


if __name__ == "__main__":
    main()
