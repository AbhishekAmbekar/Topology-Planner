"""
check_output.py
Quick review of the Week 1 files. Run from the repo root:
  python src/check_output.py
It prints a few checks and saves a picture to outputs/sites_map.png
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

OUT = Path("data/processed")
df = pd.read_csv(OUT / "zip_table.csv", dtype={"zcta": str})
sites = pd.read_csv(OUT / "candidate_sites.csv", dtype={"zcta": str})

print("CHECK 1: size")
print(f"  ZIPs: {len(df)}   Sites: {len(sites)}")
print(df["state"].value_counts().to_string())

print("\nCHECK 2: blank values (every number should be 0)")
cols = ["lat", "lon", "households", "median_income", "demand"]
print(df[cols].isna().sum().to_string())

print("\nCHECK 3: top 10 ZIPs by demand")
top = df.sort_values("demand", ascending=False).head(10)
print(top[["zcta", "state", "metro", "county_name", "households", "demand"]]
      .round(0).to_string(index=False))

print("\nCHECK 4: share of total demand by metro")
share = (df.groupby("metro")["demand"].sum() / df["demand"].sum()).sort_values(ascending=False)
print((share * 100).round(1).astype(str).add(" %").to_string())

print("\nCHECK 5: candidate sites by metro")
print(sites["metro"].value_counts().to_string())

# Picture: gray dots are ZIPs, red squares are candidate sites
fig, ax = plt.subplots(figsize=(11, 6))
ax.scatter(df["lon"], df["lat"], s=df["demand"] / df["demand"].max() * 80 + 3,
           c="lightgray", edgecolors="gray", linewidths=0.3, label="ZIPs (size = demand)")
ax.scatter(sites["lon"], sites["lat"], s=70, c="red", marker="s", label="Candidate sites")
ax.set_xlabel("Longitude")
ax.set_ylabel("Latitude")
ax.set_title("Tennessee and South Carolina: ZIPs and candidate sites")
ax.legend()
Path("outputs").mkdir(exist_ok=True)
fig.savefig("outputs/sites_map.png", dpi=150, bbox_inches="tight")
print("\nSaved picture: outputs/sites_map.png")
