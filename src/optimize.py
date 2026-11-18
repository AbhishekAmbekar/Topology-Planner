"""
optimize.py
Week 2: decide which candidate sites to open and which ZIPs each one serves.

What it does:
  1. Builds a simple baseline (a naive layout, NOT Amazon's real network)
  2. Solves a capacitated facility location model
  3. Compares baseline and optimized layouts
  4. Optionally runs sensitivity tests (--sensitivity)
  5. Saves tables and a before and after picture

Setup (inside your .venv):
  pip install scipy

Run from the repo root:
  python src/optimize.py                 base case only
  python src/optimize.py --sensitivity   base case plus 10 what if tests
"""
import argparse
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import sparse
from scipy.optimize import Bounds, LinearConstraint, milp

PROC = Path("data/processed")
OUT = Path("outputs")

# ------------------------------------------------------------------
# SETTINGS. All of these are placeholders. They go in your assumptions doc.
# ------------------------------------------------------------------
BASE = {
    # One station can handle this share of the total two state demand.
    "capacity_share": 0.10,
    # Opening a site costs the same as moving one full station's demand this many miles.
    "fixed_cost_miles": 10,
    # A ZIP can only be served by a site within this many road miles.
    "radius": 45,
    # Must match CIRCUITY in data_prep.py unless you are running a what if test.
    "circuity": 1.3,
    # At least this share of total demand must be served within the radius.
    "min_coverage": 0.95,
    # A small cost for leaving a ZIP unserved, in miles. Kept low on purpose so the
    # model does not open extra sites just for a few remote ZIPs.
    "penalty_miles": 50,
    # The naive baseline opens this many sites.
    "baseline_open": 14,
    # Seconds the solver may spend on each run.
    "time_limit": 60,
}
DATA_CIRCUITY = 1.3   # the circuity already built into distance_matrix.csv


# ------------------------------------------------------------------
def load_data():
    zips = pd.read_csv(PROC / "zip_table.csv", dtype={"zcta": str})
    sites = pd.read_csv(PROC / "candidate_sites.csv", dtype={"zcta": str})
    raw = pd.read_csv(PROC / "distance_matrix.csv", dtype=str)
    raw = raw.set_index(raw.columns[0])
    dm = raw.astype(float).loc[zips["zcta"], sites["site_id"]]
    return zips, sites, dm.values


def get_cap(zips, p):
    return p["capacity_share"] * zips["demand"].sum()


def get_fixed(zips, p):
    # Site cost is tied to the BASE capacity, so the capacity test changes only capacity.
    return p["fixed_cost_miles"] * BASE["capacity_share"] * zips["demand"].sum()


# ------------------------------------------------------------------
# Baseline: open the busiest sites under a nearest site rule. No capacity checks.
# ------------------------------------------------------------------
def make_baseline(zips, dist, p):
    demand = zips["demand"].values
    nearest = dist.argmin(axis=1)
    load = np.bincount(nearest, weights=demand, minlength=dist.shape[1])
    top = np.argsort(-load)[: p["baseline_open"]]
    open_mask = np.zeros(dist.shape[1], dtype=bool)
    open_mask[top] = True
    masked = np.where(open_mask[None, :], dist, np.inf)
    assign = masked.argmin(axis=1)
    return open_mask, assign


# ------------------------------------------------------------------
# Optimizer
# ------------------------------------------------------------------
def solve(zips, dist, p):
    n, m = dist.shape
    demand = zips["demand"].values
    cap = get_cap(zips, p)
    fixed = get_fixed(zips, p)

    ii, jj = np.where(dist <= p["radius"])      # only ZIP and site pairs inside the radius
    P = len(ii)
    # Some ZIPs have no site inside the radius at all. They cannot be covered.
    has_site = np.zeros(n, dtype=bool)
    has_site[ii] = True
    forced = demand[~has_site].sum() / demand.sum()
    allowed = max(1 - p["min_coverage"], forced + 0.0005)
    # Variable order: y (open site, m of them), x (ZIP to site, P), u (unserved share, n)
    nv = m + P + n
    c = np.concatenate([
        np.full(m, fixed),
        demand[ii] * dist[ii, jj],
        p["penalty_miles"] * demand,
    ])
    x_idx = m + np.arange(P)
    u_idx = m + P + np.arange(n)

    # Rule 1: each ZIP is served by exactly one site, or left unserved
    r1 = sparse.coo_matrix(
        (np.ones(P + n), (np.concatenate([ii, np.arange(n)]),
                                     np.concatenate([x_idx, u_idx]))),
        shape=(n, nv))
    # Rule 2: a ZIP can only use a site that is open
    r2 = sparse.coo_matrix(
        (np.concatenate([np.ones(P), -np.ones(P)]),
         (np.concatenate([np.arange(P), np.arange(P)]), np.concatenate([x_idx, jj]))),
        shape=(P, nv))
    # Rule 3: demand sent to a site cannot pass its capacity
    r3 = sparse.coo_matrix(
        (np.concatenate([demand[ii], np.full(m, -cap)]),
         (np.concatenate([jj, np.arange(m)]), np.concatenate([x_idx, np.arange(m)]))),
        shape=(m, nv))

    # Rule 4: at most a small share of demand may be left unserved
    r4 = sparse.coo_matrix((demand, (np.zeros(n, dtype=int), u_idx)), shape=(1, nv))

    cons = [
        LinearConstraint(r1.tocsr(), 1, 1),
        LinearConstraint(r4.tocsr(), -np.inf, allowed * demand.sum()),
        LinearConstraint(r2.tocsr(), -np.inf, 0),
        LinearConstraint(r3.tocsr(), -np.inf, 0),
    ]
    integrality = np.concatenate([np.ones(m + P), np.zeros(n)])

    t0 = time.time()
    res = milp(c, constraints=cons, integrality=integrality, bounds=Bounds(0, 1),
               options={"time_limit": p["time_limit"], "mip_rel_gap": 0.01})
    secs = time.time() - t0
    if res.x is None:
        raise SystemExit("The solver found no solution. Try a larger radius, larger capacity, or lower min_coverage.")

    open_mask = res.x[:m] > 0.5
    assign = np.full(n, -1, dtype=int)
    chosen = res.x[m:m + P] > 0.5
    assign[ii[chosen]] = jj[chosen]
    hit_limit = res.status == 1
    return open_mask, assign, secs, hit_limit, 1 - allowed


# ------------------------------------------------------------------
def get_metrics(zips, dist, open_mask, assign, p):
    demand = zips["demand"].values
    cap = get_cap(zips, p)
    n = len(zips)
    served = assign >= 0
    d = np.zeros(n)
    d[served] = dist[np.arange(n)[served], assign[served]]
    load = np.zeros(dist.shape[1])
    np.add.at(load, assign[served], demand[served])
    util = np.where(open_mask, load / cap, 0.0)

    fixed = get_fixed(zips, p) * open_mask.sum()
    dist_cost = float((demand[served] * d[served]).sum())
    unserved = float(demand[~served].sum())
    network_cost = fixed + dist_cost
    covered = served & (d <= p["radius"] + 1e-9)
    return {
        "sites_open": int(open_mask.sum()),
        "avg_miles": round(dist_cost / demand[served].sum(), 1),
        "longest_miles": round(float(d[served].max()), 1),
        "avg_utilization_pct": round(float(util[open_mask].mean() * 100), 0),
        "max_utilization_pct": round(float(util.max() * 100), 0),
        "overloaded_sites": int((util > 1.0001).sum()),
        "covered_demand_pct": round(100 * float(demand[covered].sum()) / demand.sum(), 1),
        "zips_beyond_radius": int((d > p["radius"] + 1e-9).sum()),
        "unserved_zips": int((~served).sum()),
        "network_cost_millions": round(network_cost / 1e6, 1),
    }, load


def run_case(zips, dist_base, p):
    """Run baseline and optimizer for one set of settings."""
    dist = dist_base * (p["circuity"] / DATA_CIRCUITY)
    b_open, b_assign = make_baseline(zips, dist, p)
    o_open, o_assign, secs, hit, cov_used = solve(zips, dist, p)
    bm, b_load = get_metrics(zips, dist, b_open, b_assign, p)
    om, o_load = get_metrics(zips, dist, o_open, o_assign, p)
    return {
        "dist": dist, "secs": secs, "hit_limit": hit, "coverage_used": cov_used,
        "base": (b_open, b_assign, bm, b_load),
        "opt": (o_open, o_assign, om, o_load),
    }


# ------------------------------------------------------------------
# Picture
# ------------------------------------------------------------------
def draw(ax, zips, sites, dist, open_mask, assign, title):
    n = len(zips)
    served = assign >= 0
    d = np.full(n, np.nan)
    d[served] = dist[np.arange(n)[served], assign[served]]
    sc = ax.scatter(zips["lon"], zips["lat"], c=d, cmap="YlOrRd", vmin=0, vmax=60,
                    s=zips["demand"] / zips["demand"].max() * 60 + 4,
                    edgecolors="gray", linewidths=0.2)
    if (~served).any():
        ax.scatter(zips.loc[~served, "lon"], zips.loc[~served, "lat"], c="black",
                   marker="x", s=25, label="Unserved")
    ax.scatter(sites.loc[~open_mask, "lon"], sites.loc[~open_mask, "lat"],
               facecolors="none", edgecolors="gray", marker="s", s=60, label="Closed site")
    ax.scatter(sites.loc[open_mask, "lon"], sites.loc[open_mask, "lat"],
               c="blue", marker="s", s=70, label="Open site")
    ax.set_title(title)
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.legend(loc="lower left", fontsize=8)
    return sc


def save_picture(zips, sites, res):
    fig, axes = plt.subplots(1, 2, figsize=(16, 6), sharey=True)
    b_open, b_assign, bm, _ = res["base"]
    o_open, o_assign, om, _ = res["opt"]
    sc = draw(axes[0], zips, sites, res["dist"], b_open, b_assign,
              f"Baseline: {bm['sites_open']} sites, nearest site rule")
    draw(axes[1], zips, sites, res["dist"], o_open, o_assign,
         f"Optimized: {om['sites_open']} sites, capacity and radius respected")
    fig.colorbar(sc, ax=axes, label="Road miles to assigned site", shrink=0.8)
    OUT.mkdir(exist_ok=True)
    fig.savefig(OUT / "before_after.png", dpi=150, bbox_inches="tight")


# ------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sensitivity", action="store_true", help="also run what if tests")
    args = ap.parse_args()

    OUT.mkdir(exist_ok=True)
    zips, sites, dist_base = load_data()
    cap = get_cap(zips, BASE)
    print(f"ZIPs: {len(zips)}   Candidate sites: {len(sites)}")
    print(f"Station capacity: {BASE['capacity_share']:.0%} of total demand "
          f"(minimum sites needed: {zips['demand'].sum() / cap:.0f})")
    print("Solving the base case. This can take up to a minute or two...\n")

    res = run_case(zips, dist_base, BASE)
    b_open, b_assign, bm, b_load = res["base"]
    o_open, o_assign, om, o_load = res["opt"]

    table = pd.DataFrame({"Baseline": bm, "Optimized": om})
    print(table.to_string())
    print(f"\nSolve time: {res['secs']:.0f} seconds"
          + ("  (hit the time limit, answer may be a little above the best possible)"
             if res["hit_limit"] else ""))
    table.to_csv(OUT / "week2_comparison.csv")
    if abs(res["coverage_used"] - BASE["min_coverage"]) > 1e-6:
        print(f"Note: coverage target was raised to {res['coverage_used']:.1%} because some "
              "ZIPs have no site inside the radius.")

    # Opened sites with load
    s = sites.copy()
    s["opened_baseline"] = b_open
    s["opened_optimized"] = o_open
    s["load_optimized_pct"] = np.round(o_load / cap * 100, 0)
    s.to_csv(PROC / "sites_opened.csv", index=False)
    print("\nOptimized sites opened, by metro:")
    print(s[s["opened_optimized"]].groupby("metro").size().sort_values(ascending=False).to_string())

    # ZIP assignments
    a = zips[["zcta", "state", "metro", "demand"]].copy()
    a["baseline_site"] = [sites["site_id"][j] for j in b_assign]
    a["optimized_site"] = [sites["site_id"][j] if j >= 0 else "UNSERVED" for j in o_assign]
    a["optimized_miles"] = [res["dist"][i, j] if j >= 0 else np.nan
                            for i, j in enumerate(o_assign)]
    a.to_csv(PROC / "assignments.csv", index=False)

    if om["unserved_zips"] > 0:
        print("\nUnserved ZIPs by metro (these areas may need more candidate sites):")
        print(a[a["optimized_site"] == "UNSERVED"].groupby("metro").size().to_string())

    save_picture(zips, sites, res)
    print("\nSaved: outputs/week2_comparison.csv, outputs/before_after.png,")
    print("       data/processed/sites_opened.csv, data/processed/assignments.csv")

    if args.sensitivity:
        tests = [
            ("Base case", {}),
            ("Capacity minus 20%", {"capacity_share": BASE["capacity_share"] * 0.8}),
            ("Capacity plus 20%", {"capacity_share": BASE["capacity_share"] * 1.2}),
            ("Site cost minus 20%", {"fixed_cost_miles": BASE["fixed_cost_miles"] * 0.8}),
            ("Site cost plus 20%", {"fixed_cost_miles": BASE["fixed_cost_miles"] * 1.2}),
            ("Coverage 90%", {"min_coverage": 0.90}),
            ("Coverage 98%", {"min_coverage": 0.98}),
            ("Radius 35 miles", {"radius": 35}),
            ("Radius 60 miles", {"radius": 60}),
            ("Circuity 1.2", {"circuity": 1.2}),
            ("Circuity 1.4", {"circuity": 1.4}),
        ]
        rows = []
        for name, change in tests:
            p = {**BASE, **change}
            print(f"Running: {name} ...")
            r = run_case(zips, dist_base, p)
            m = dict(r["opt"][2])
            m["scenario"] = name
            m["coverage_target_used"] = round(r["coverage_used"] * 100, 1)
            m["solve_seconds"] = round(r["secs"])
            m["hit_time_limit"] = r["hit_limit"]
            rows.append(m)
        sens = pd.DataFrame(rows).set_index("scenario")
        show = ["sites_open", "avg_miles", "longest_miles", "avg_utilization_pct",
                "max_utilization_pct", "covered_demand_pct", "coverage_target_used",
                "network_cost_millions"]
        print("\nSensitivity results (optimized layout):")
        print(sens[show].to_string())
        sens.to_csv(OUT / "sensitivity.csv")
        print("\nSaved: outputs/sensitivity.csv")


if __name__ == "__main__":
    main()
