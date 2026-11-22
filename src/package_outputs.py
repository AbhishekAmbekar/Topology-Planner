"""
package_outputs.py
Week 4: package the project so someone else can open it and use it.

What it makes:
  1. A SQL database (data/topology.db) and the SQL queries in the sql/ folder
  2. An Excel workbook (outputs/topology_planner.xlsx) with live formulas
  3. An interactive map (outputs/network_map.html) that opens in any browser

It reads the files from Weeks 1 to 3, so run those first.

Setup (inside your .venv):
  pip install openpyxl folium

Run from the repo root:
  python src/package_outputs.py
"""
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from optimize import BASE                                    # Week 2 settings
from build_plan import (HEADROOM, HORIZON, LAUNCHES_PER_YEAR,  # Week 3 settings
                        OVERFLOW_PENALTY_MILES)

PROC = Path("data/processed")
OUT = Path("outputs")
SQLDIR = Path("sql")
DB = Path("data/topology.db")
XLSX = OUT / "topology_planner.xlsx"
MAP = OUT / "network_map.html"


# ------------------------------------------------------------------
# Load the files from Weeks 1 to 3
# ------------------------------------------------------------------
def load():
    need = [PROC / "zip_table.csv", PROC / "assignments.csv", PROC / "sites_opened.csv",
            PROC / "zip_growth.csv", OUT / "scenario_summary.csv",
            OUT / "build_schedule.csv", OUT / "week2_comparison.csv"]
    missing = [str(p) for p in need if not p.exists()]
    if missing:
        raise SystemExit("These files are missing. Run Weeks 1 to 3 first:\n  " + "\n  ".join(missing))

    zips = pd.read_csv(PROC / "zip_table.csv", dtype={"zcta": str})
    asg = pd.read_csv(PROC / "assignments.csv", dtype={"zcta": str})
    growth = pd.read_csv(PROC / "zip_growth.csv", dtype={"zcta": str})
    sites = pd.read_csv(PROC / "sites_opened.csv", dtype={"zcta": str})
    scen = pd.read_csv(OUT / "scenario_summary.csv")
    sched = pd.read_csv(OUT / "build_schedule.csv", dtype={"zcta": str})
    comp = pd.read_csv(OUT / "week2_comparison.csv", index_col=0)

    for c in ["opened_baseline", "opened_optimized"]:
        sites[c] = sites[c].astype(str).str.lower().eq("true")

    z = zips.merge(asg[["zcta", "baseline_site", "optimized_site", "optimized_miles"]],
                   on="zcta", how="left")
    z = z.merge(growth[["zcta", "cagr"]], on="zcta", how="left")
    z["optimized_site"] = z["optimized_site"].fillna("UNSERVED")
    if len(z) != len(zips):
        raise SystemExit("The ZIP files do not line up. Rerun Weeks 1 and 2 in order.")
    z = z[["zcta", "state", "metro", "county_name", "lat", "lon", "households", "demand",
           "cagr", "baseline_site", "optimized_site", "optimized_miles"]]
    return z, sites, scen, sched, comp


def parse_schedule(sched, names):
    """Turn 'Year 3' text cells into one row per site and scenario."""
    rows = []
    for _, r in sched.iterrows():
        for nm in names:
            v = r.get(nm)
            if isinstance(v, str) and v.strip().lower().startswith("year"):
                rows.append((r["site_id"], nm, int(v.split()[1])))
    return pd.DataFrame(rows, columns=["site_id", "scenario", "year_opened"])


# ------------------------------------------------------------------
# 1. SQL
# ------------------------------------------------------------------
QUERIES = {
    "01_metro_summary": """-- Demand, service and open stations by metro group (optimized layout)
SELECT
  z.metro,
  COUNT(*)                                   AS zips,
  ROUND(SUM(z.households))                   AS households,
  ROUND(SUM(z.demand))                       AS demand,
  ROUND(100.0 * SUM(z.demand) / SUM(SUM(z.demand)) OVER (), 1) AS demand_share_pct,
  ROUND(SUM(CASE WHEN z.optimized_site <> 'UNSERVED' THEN z.demand * z.optimized_miles END)
      / SUM(CASE WHEN z.optimized_site <> 'UNSERVED' THEN z.demand END), 1) AS avg_miles,
  SUM(CASE WHEN z.optimized_site = 'UNSERVED' THEN 1 ELSE 0 END) AS unserved_zips,
  (SELECT COUNT(*) FROM sites s WHERE s.metro = z.metro AND s.opened_optimized = 1) AS open_stations
FROM zips z
GROUP BY z.metro
ORDER BY demand DESC;
""",
    "02_station_load": """-- How full each station is, and how far its ZIPs have to travel
SELECT
  s.site_id, s.state, s.metro, s.zcta, s.opened_optimized AS open_now,
  COUNT(z.zcta)                                         AS zips_served,
  ROUND(COALESCE(SUM(z.demand), 0))                     AS demand_served,
  ROUND(100.0 * COALESCE(SUM(z.demand), 0) / (SELECT capacity_demand FROM settings), 0) AS utilization_pct,
  ROUND(MAX(z.optimized_miles), 1)                      AS longest_trip_miles,
  ROUND(SUM(z.demand * z.optimized_miles) / SUM(z.demand), 1) AS avg_miles
FROM sites s
LEFT JOIN zips z ON z.optimized_site = s.site_id
GROUP BY s.site_id
ORDER BY utilization_pct DESC, s.site_id;
""",
    "03_longest_trips": """-- The 15 ZIPs that add the most demand times miles
SELECT z.zcta, z.metro, z.optimized_site AS station,
       ROUND(z.demand) AS demand, ROUND(z.optimized_miles, 1) AS miles,
       ROUND(z.demand * z.optimized_miles) AS demand_x_miles
FROM zips z
WHERE z.optimized_site <> 'UNSERVED'
ORDER BY demand_x_miles DESC
LIMIT 15;
""",
    "04_unserved_by_metro": """-- ZIPs the optimized layout leaves unserved
SELECT z.metro, COUNT(*) AS unserved_zips, ROUND(SUM(z.demand)) AS unserved_demand,
       ROUND(100.0 * SUM(z.demand) / (SELECT SUM(demand) FROM zips), 2) AS pct_of_all_demand
FROM zips z
WHERE z.optimized_site = 'UNSERVED'
GROUP BY z.metro
ORDER BY unserved_demand DESC;
""",
    "05_fastest_counties": """-- Counties with the fastest yearly population growth (capped in Week 3)
SELECT z.state, z.county_name, COUNT(*) AS zips, ROUND(SUM(z.demand)) AS demand,
       ROUND(100.0 * MAX(z.cagr), 1) AS yearly_growth_pct
FROM zips z
GROUP BY z.state, z.county_name
ORDER BY yearly_growth_pct DESC, demand DESC
LIMIT 10;
""",
    "06_scenario_stress": """-- Worst year for each scenario
SELECT scenario,
       MAX(demand_index)           AS demand_index_year5,
       MAX(sites_open)             AS stations_year5,
       MAX(busiest_pct_of_target)  AS busiest_station_peak,
       MAX(demand_over_target_pct) AS worst_demand_over_target_pct
FROM scenario_summary
GROUP BY scenario
ORDER BY demand_index_year5, scenario;
""",
    "07_new_sites_by_year": """-- Which stations open in which year, by scenario
SELECT scenario, year_opened, COUNT(*) AS new_stations, GROUP_CONCAT(site_id, ', ') AS stations
FROM build_schedule
GROUP BY scenario, year_opened
ORDER BY scenario, year_opened;
""",
}


def make_database(z, sites, scen, sched_long):
    SQLDIR.mkdir(exist_ok=True)
    DB.parent.mkdir(exist_ok=True)
    if DB.exists():
        DB.unlink()
    con = sqlite3.connect(DB)
    z.to_sql("zips", con, index=False)
    sites.to_sql("sites", con, index=False)
    scen.to_sql("scenario_summary", con, index=False)
    sched_long.to_sql("build_schedule", con, index=False)
    total = float(z["demand"].sum())
    pd.DataFrame([{
        "capacity_share": BASE["capacity_share"],
        "capacity_demand": BASE["capacity_share"] * total,
        "radius_miles": BASE["radius"],
        "min_coverage": BASE["min_coverage"],
        "headroom": HEADROOM,
    }]).to_sql("settings", con, index=False)

    results = {}
    (OUT / "sql_results").mkdir(parents=True, exist_ok=True)
    for name, text in QUERIES.items():
        (SQLDIR / f"{name}.sql").write_text(text)
        df = pd.read_sql_query(text, con)
        df.to_csv(OUT / "sql_results" / f"{name}.csv", index=False)
        results[name] = df
    con.close()
    return results


# ------------------------------------------------------------------
# 2. Excel workbook
# ------------------------------------------------------------------
SUMMARY_ROWS = [
    ("sites_open", "Stations open", "0"),
    ("avg_miles", "Average road miles to station (demand weighted)", "0.0"),
    ("longest_miles", "Longest trip, road miles", "0.0"),
    ("covered_demand_pct", "Demand served within the radius (%)", "0.0"),
    ("zips_beyond_radius", "ZIPs assigned beyond the radius", "0"),
    ("unserved_zips", "ZIPs left unserved", "0"),
    ("overloaded_sites", "Stations over capacity", "0"),
    ("max_utilization_pct", "Busiest station use (%)", "0"),
    ("avg_utilization_pct", "Average station use, open stations (%)", "0"),
    ("network_cost_millions", "Network cost, placeholder units (millions)", "0.0"),
]


def build_workbook(z, sites, scen, sched, sched_long, comp, names):
    from openpyxl import Workbook
    from openpyxl.chart import BarChart, LineChart, Reference
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter as CL

    def font(**k):
        return Font(name="Arial", size=k.pop("size", 10), **k)

    head_fill = PatternFill("solid", fgColor="1F3864")
    input_fill = PatternFill("solid", fgColor="FFF2CC")
    BLUE = "0000FF"

    def title(ws, text, note=None):
        ws["A1"] = text
        ws["A1"].font = font(size=14, bold=True)
        if note:
            ws["A2"] = note
            ws["A2"].font = font(italic=True, color="595959")

    def header(ws, row, labels, col=1):
        for i, lab in enumerate(labels):
            c = ws.cell(row=row, column=col + i, value=lab)
            c.font = font(bold=True, color="FFFFFF")
            c.fill = head_fill
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.row_dimensions[row].height = 32

    def widths(ws, w):
        for col, val in w.items():
            ws.column_dimensions[col].width = val

    def style_range(ws, rng, fmt=None, color=None, bold=False):
        for row in ws[rng]:
            for c in row:
                c.font = font(color=color, bold=bold) if color or bold else font()
                if fmt:
                    c.number_format = fmt

    wb = Workbook()
    ws_about = wb.active
    ws_about.title = "About"
    ws_sum = wb.create_sheet("Summary")
    ws_met = wb.create_sheet("Metro summary")
    ws_sta = wb.create_sheet("Stations")
    ws_scn = wb.create_sheet("Scenarios")
    ws_bld = wb.create_sheet("Build schedule")
    ws_inp = wb.create_sheet("Inputs")
    ws_sd = wb.create_sheet("Scenario data")
    ws_zip = wb.create_sheet("Zips")

    n = len(z)
    zl = n + 1                      # last data row on the Zips sheet
    zr = lambda col: f"Zips!${col}$2:${col}${zl}"

    # ---------------- Zips (data plus formulas) ----------------
    zcols = ["ZIP", "State", "Metro", "County", "Latitude", "Longitude", "Households",
             "Demand (proxy)", "Yearly growth", "Baseline station", "Optimized station",
             "Miles to station", "Station metro", "Station use", "Served demand",
             "Demand x miles"]
    header(ws_zip, 1, zcols)
    m_sites = len(sites)
    s_first, s_last = 5, 4 + m_sites                # Stations data rows
    for i, r in enumerate(z.itertuples(index=False), start=2):
        ws_zip.cell(i, 1, r.zcta)
        ws_zip.cell(i, 2, r.state)
        ws_zip.cell(i, 3, r.metro)
        ws_zip.cell(i, 4, r.county_name)
        ws_zip.cell(i, 5, float(r.lat))
        ws_zip.cell(i, 6, float(r.lon))
        ws_zip.cell(i, 7, float(r.households))
        ws_zip.cell(i, 8, float(r.demand))
        ws_zip.cell(i, 9, None if pd.isna(r.cagr) else float(r.cagr))
        ws_zip.cell(i, 10, r.baseline_site)
        ws_zip.cell(i, 11, r.optimized_site)
        ws_zip.cell(i, 12, None if pd.isna(r.optimized_miles) else float(r.optimized_miles))
        ws_zip.cell(i, 13, f'=IFERROR(VLOOKUP(K{i},Stations!$A${s_first}:$L${s_last},3,FALSE),"")')
        ws_zip.cell(i, 14, f'=IFERROR(VLOOKUP(K{i},Stations!$A${s_first}:$L${s_last},9,FALSE),"")')
        ws_zip.cell(i, 15, f'=IF(K{i}="UNSERVED",0,H{i})')
        ws_zip.cell(i, 16, f'=IF(K{i}="UNSERVED",0,H{i}*L{i})')
    for col, fmt in {"E": "0.0000", "F": "0.0000", "G": "#,##0", "H": "#,##0", "I": "0.0%",
                     "L": "0.0", "N": "0%", "O": "#,##0", "P": "#,##0"}.items():
        style_range(ws_zip, f"{col}2:{col}{zl}", fmt)
    for col in "ABCDJKM":
        style_range(ws_zip, f"{col}2:{col}{zl}")
    ws_zip.freeze_panes = "B2"
    ws_zip.auto_filter.ref = f"A1:P{zl}"
    widths(ws_zip, {"A": 9, "B": 7, "C": 22, "D": 22, "E": 11, "F": 11, "G": 12, "H": 14,
                    "I": 10, "J": 12, "K": 13, "L": 10, "M": 22, "N": 10, "O": 13, "P": 14})

    # ---------------- Inputs ----------------
    title(ws_inp, "Inputs and model settings",
          "Every value is a placeholder I chose, not company data. See docs/assumptions.md.")
    header(ws_inp, 3, ["Setting", "Value", "Used in this workbook?", "Meaning"])
    settings = [
        ("Station capacity (share of total demand)", BASE["capacity_share"], "0%", "Yes",
         "One station handles this share of all demand. Change it to see station use update."),
        ("Cost to open a site (miles of driving)", BASE["fixed_cost_miles"], "0", "No",
         "Reference only. Used when the optimizer ran."),
        ("Maximum drive radius (road miles)", BASE["radius"], "0", "No",
         "Reference only. Used when the optimizer ran."),
        ("Minimum demand served within radius", BASE["min_coverage"], "0%", "No",
         "Reference only. Used when the optimizer ran."),
        ("Safety buffer (share of capacity)", HEADROOM, "0%", "No",
         "Reference only. Week 3 treats a station as full at this level."),
        ("New stations allowed per year", LAUNCHES_PER_YEAR, "0", "No",
         "Reference only. Stands in for a budget limit."),
        ("Cost of demand above the buffer (miles)", OVERFLOW_PENALTY_MILES, "0", "No",
         "Reference only. Week 3 setting."),
        ("Road distance factor", BASE["circuity"], "0.0", "No",
         "Reference only. Straight line miles times this number."),
        ("Stations in the naive baseline", BASE["baseline_open"], "0", "No",
         "Reference only. The baseline opens the busiest sites with no capacity check."),
    ]
    for i, (lab, val, fmt, used, mean) in enumerate(settings, start=4):
        ws_inp.cell(i, 1, lab).font = font()
        c = ws_inp.cell(i, 2, val)
        c.font = font(color=BLUE)
        c.number_format = fmt
        ws_inp.cell(i, 3, used).font = font()
        ws_inp.cell(i, 4, mean).font = font()
    ws_inp["B4"].fill = input_fill
    ws_inp["A14"] = "Total demand, all ZIPs (formula)"
    ws_inp["B14"] = f"=SUM({zr('H')})"
    ws_inp["A15"] = "Station capacity, demand units (formula)"
    ws_inp["B15"] = "=B4*B14"
    for a in ("A14", "A15", "B14", "B15"):
        ws_inp[a].font = font()
    ws_inp["B14"].number_format = "#,##0"
    ws_inp["B15"].number_format = "#,##0"
    ws_inp["A17"] = "Blue text is a typed input. The yellow cell is the only one that changes results here. "
    ws_inp["A18"] = "Changing it does not rerun the optimizer. It only changes the station use formulas."
    ws_inp["A17"].font = font(italic=True, color="595959")
    ws_inp["A18"].font = font(italic=True, color="595959")
    widths(ws_inp, {"A": 44, "B": 12, "C": 22, "D": 80})

    # ---------------- Stations ----------------
    title(ws_sta, "Stations: load and use (optimized layout, Week 2)",
          "Load and use are formulas that read the Zips sheet. The last two columns check them against the model.")
    header(ws_sta, 4, ["Site", "State", "Metro", "ZIP", "Open in baseline", "Open in optimized",
                       "ZIPs served", "Demand served", "Station use", "Model use (%)",
                       "Matches model?", "Avg miles"])
    st = sites.sort_values(["load_optimized_pct", "site_id"], ascending=[False, True]).reset_index(drop=True)
    for i, r in enumerate(st.itertuples(index=False), start=s_first):
        ws_sta.cell(i, 1, r.site_id)
        ws_sta.cell(i, 2, r.state)
        ws_sta.cell(i, 3, r.metro)
        ws_sta.cell(i, 4, r.zcta)
        ws_sta.cell(i, 5, "Yes" if r.opened_baseline else "No")
        ws_sta.cell(i, 6, "Yes" if r.opened_optimized else "No")
        ws_sta.cell(i, 7, f"=COUNTIFS({zr('K')},A{i})")
        ws_sta.cell(i, 8, f"=SUMIFS({zr('H')},{zr('K')},A{i})")
        ws_sta.cell(i, 9, f"=H{i}/Inputs!$B$15")
        ws_sta.cell(i, 10, float(r.load_optimized_pct))
        ws_sta.cell(i, 11, f'=IF(ROUND(I{i}*100,0)=J{i},"Yes","Check")')
        ws_sta.cell(i, 12, f'=IF(H{i}=0,"",SUMIFS({zr("P")},{zr("K")},A{i})/H{i})')
    style_range(ws_sta, f"A{s_first}:F{s_last}")
    style_range(ws_sta, f"G{s_first}:G{s_last}", "0")
    style_range(ws_sta, f"H{s_first}:H{s_last}", "#,##0")
    style_range(ws_sta, f"I{s_first}:I{s_last}", "0%")
    style_range(ws_sta, f"J{s_first}:J{s_last}", '0"%"', color=BLUE)
    style_range(ws_sta, f"K{s_first}:K{s_last}")
    style_range(ws_sta, f"L{s_first}:L{s_last}", "0.0")
    tr = s_last + 1
    ws_sta.cell(tr, 1, "Total")
    ws_sta.cell(tr, 7, f"=SUM(G{s_first}:G{s_last})")
    ws_sta.cell(tr, 8, f"=SUM(H{s_first}:H{s_last})")
    for c in (1, 7, 8):
        ws_sta.cell(tr, c).font = font(bold=True)
    ws_sta.cell(tr, 8).number_format = "#,##0"
    ws_sta.cell(tr + 1, 1, "Unserved ZIPs are not counted in any station. "
                "Model use is rounded to a whole percent, which is why the check compares rounded values.").font = \
        font(italic=True, color="595959")
    ws_sta.freeze_panes = "B5"
    widths(ws_sta, {"A": 9, "B": 7, "C": 22, "D": 9, "E": 11, "F": 11, "G": 10, "H": 13,
                    "I": 10, "J": 11, "K": 12, "L": 10})

    # ---------------- Metro summary ----------------
    metros = (z.groupby("metro")["demand"].sum().sort_values(ascending=False).index.tolist())
    mf, ml = 5, 4 + len(metros)
    title(ws_met, "Metro summary (optimized layout)",
          "Formulas over the Zips and Stations sheets. The same table comes from sql/01_metro_summary.sql.")
    header(ws_met, 4, ["Metro", "ZIPs", "Households", "Demand", "Share of demand",
                       "Served demand", "Avg miles", "Unserved ZIPs", "Open stations"])
    for i, mname in enumerate(metros, start=mf):
        ws_met.cell(i, 1, mname)
        ws_met.cell(i, 2, f"=COUNTIFS({zr('C')},A{i})")
        ws_met.cell(i, 3, f"=SUMIFS({zr('G')},{zr('C')},A{i})")
        ws_met.cell(i, 4, f"=SUMIFS({zr('H')},{zr('C')},A{i})")
        ws_met.cell(i, 5, f"=D{i}/D${ml + 1}")
        ws_met.cell(i, 6, f"=SUMIFS({zr('O')},{zr('C')},A{i})")
        ws_met.cell(i, 7, f'=IF(F{i}=0,"",SUMIFS({zr("P")},{zr("C")},A{i})/F{i})')
        ws_met.cell(i, 8, f'=COUNTIFS({zr("C")},A{i},{zr("K")},"UNSERVED")')
        ws_met.cell(i, 9, f'=COUNTIFS(Stations!$C${s_first}:$C${s_last},A{i},Stations!$F${s_first}:$F${s_last},"Yes")')
    t = ml + 1
    ws_met.cell(t, 1, "Total")
    for col in (2, 3, 4, 6, 8, 9):
        L = CL(col)
        ws_met.cell(t, col, f"=SUM({L}{mf}:{L}{ml})")
    ws_met.cell(t, 5, f"=SUM(E{mf}:E{ml})")
    ws_met.cell(t, 7, f"=SUM({zr('P')})/F{t}")
    style_range(ws_met, f"A{mf}:I{t}")
    for col, fmt in {"B": "#,##0", "C": "#,##0", "D": "#,##0", "E": "0.0%", "F": "#,##0",
                     "G": "0.0", "H": "0", "I": "0"}.items():
        style_range(ws_met, f"{col}{mf}:{col}{t}", fmt)
    for c in range(1, 10):
        ws_met.cell(t, c).font = font(bold=True)
    widths(ws_met, {"A": 24, "B": 9, "C": 13, "D": 13, "E": 12, "F": 14, "G": 10, "H": 12, "I": 12})
    bc = BarChart()
    bc.type = "bar"
    bc.title = "Demand by metro (proxy units)"
    bc.add_data(Reference(ws_met, min_col=4, min_row=4, max_row=ml), titles_from_data=True)
    bc.set_categories(Reference(ws_met, min_col=1, min_row=mf, max_row=ml))
    bc.legend = None
    bc.x_axis.delete = False
    bc.y_axis.delete = False
    bc.height, bc.width = 9, 16
    ws_met.add_chart(bc, f"A{t + 3}")

    # ---------------- Scenario data and comparison ----------------
    sd_cols = ["scenario", "year", "demand_index", "sites_open", "new_sites", "avg_miles",
               "busiest_pct_of_target", "sites_over_target", "demand_over_target_pct",
               "covered_demand_pct"]
    sdf = scen[sd_cols]
    header(ws_sd, 1, sd_cols)
    for i, row in enumerate(sdf.itertuples(index=False), start=2):
        for j, v in enumerate(row, start=1):
            ws_sd.cell(i, j, v).font = font()
    sl = len(sdf) + 1
    ws_sd.freeze_panes = "A2"
    widths(ws_sd, {CL(i): 16 for i in range(1, 11)})
    ws_sd.column_dimensions["A"].width = 24

    years = list(range(int(scen["year"].min()), int(scen["year"].max()) + 1))
    title(ws_scn, "Scenario comparison (Week 3 build plan)",
          "Numbers come from the Scenario data sheet. 100 on the station scale means a station is at the 90 percent target.")
    blocks = [("Stations open", "D", "0", "Stations open"),
              ("Demand above the 90 percent target (% of all demand)", "I", "0.0", "Demand over target (%)"),
              ("Busiest station (% of the 90 percent target)", "G", "0", "Busiest station (% of target)")]
    r0 = 4
    k = len(names)
    for title_txt, dcol, fmt, chart_title in blocks:
        ws_scn.cell(r0, 1, title_txt).font = font(bold=True)
        header(ws_scn, r0 + 1, ["Year"] + names)
        for yi, y in enumerate(years):
            rr = r0 + 2 + yi
            ws_scn.cell(rr, 1, y).font = font()
            for ci in range(k):
                colL = CL(2 + ci)
                f = (f"=SUMIFS('Scenario data'!${dcol}$2:${dcol}${sl},'Scenario data'!$A$2:$A${sl},{colL}${r0 + 1},"
                     f"'Scenario data'!$B$2:$B${sl},$A{rr})")
                c = ws_scn.cell(rr, 2 + ci, f)
                c.font = font()
                c.number_format = fmt
        ch = LineChart()
        ch.title = chart_title
        ch.add_data(Reference(ws_scn, min_col=2, min_row=r0 + 1, max_col=1 + k, max_row=r0 + 1 + len(years)),
                    titles_from_data=True)
        ch.set_categories(Reference(ws_scn, min_col=1, min_row=r0 + 2, max_row=r0 + 1 + len(years)))
        for ser in ch.series:
            ser.smooth = False
            ser.marker.symbol = "circle"
            ser.marker.size = 5
        ch.x_axis.title = "Year"
        ch.x_axis.delete = False
        ch.y_axis.delete = False
        ch.height, ch.width = 7.5, 15
        ws_scn.add_chart(ch, f"{CL(k + 3)}{r0}")
        r0 += len(years) + 6
    widths(ws_scn, {"A": 8, **{CL(2 + i): 20 for i in range(k)}})

    # ---------------- Build schedule ----------------
    title(ws_bld, "Build schedule: year each new station opens",
          "Blank means the station does not open in that scenario.")
    header(ws_bld, 4, ["Site", "Metro", "ZIP"] + names + ["Opens in", "Earliest year"])
    opened_sites = sorted(sched_long["site_id"].unique()) if len(sched_long) else []
    info = sites.set_index("site_id")
    if not opened_sites:
        ws_bld.cell(5, 1, "No new stations were needed in any scenario.").font = font(italic=True)
    for i, sid in enumerate(opened_sites, start=5):
        ws_bld.cell(i, 1, sid).font = font()
        ws_bld.cell(i, 2, info.loc[sid, "metro"]).font = font()
        ws_bld.cell(i, 3, info.loc[sid, "zcta"]).font = font()
        for ci, nm in enumerate(names):
            hit = sched_long[(sched_long["site_id"] == sid) & (sched_long["scenario"] == nm)]
            c = ws_bld.cell(i, 4 + ci, int(hit["year_opened"].iloc[0]) if len(hit) else None)
            c.font = font()
            c.number_format = '"Year "0'
            c.alignment = Alignment(horizontal="center")
        a, b = CL(4), CL(3 + k)
        ws_bld.cell(i, 4 + k, f'=COUNT({a}{i}:{b}{i})&" of "&COLUMNS({a}{i}:{b}{i})&" scenarios"').font = font()
        ws_bld.cell(i, 5 + k, f"=MIN({a}{i}:{b}{i})").font = font()
        ws_bld.cell(i, 5 + k).number_format = '"Year "0'
    if opened_sites:
        e = 4 + len(opened_sites)
        ws_bld.cell(e + 2, 1, "Safe bets are the stations that open in every scenario "
                    "(the Opens in column reads all scenarios).").font = font(italic=True, color="595959")
    widths(ws_bld, {"A": 9, "B": 24, "C": 9, **{CL(4 + i): 20 for i in range(k)},
                    CL(4 + k): 20, CL(5 + k): 14})

    # ---------------- Summary ----------------
    title(ws_sum, "Summary: naive baseline against optimized layout",
          "Public data and placeholder assumptions. No company data. The baseline is a simple nearest station layout, not a real network.")
    header(ws_sum, 4, ["Measure", "Baseline", "Optimized", "Change", "Change %"])
    r = 5
    row_of = {}
    for key, label, fmt in SUMMARY_ROWS:
        if key not in comp.index:
            continue
        row_of[key] = r
        ws_sum.cell(r, 1, label).font = font()
        for col, name in ((2, "Baseline"), (3, "Optimized")):
            c = ws_sum.cell(r, col, float(comp.loc[key, name]))
            c.font = font(color=BLUE)
            c.number_format = fmt
        ws_sum.cell(r, 4, f"=C{r}-B{r}").number_format = fmt
        ws_sum.cell(r, 5, f'=IF(B{r}=0,"",(C{r}-B{r})/B{r})').number_format = "0%"
        ws_sum.cell(r, 4).font = font()
        ws_sum.cell(r, 5).font = font()
        r += 1
    ws_sum.cell(r, 1, "Blue values are copied from outputs/week2_comparison.csv.").font = \
        font(italic=True, color="595959")
    r += 2
    ws_sum.cell(r, 1, "Tie out: this workbook against the model").font = font(bold=True)
    r += 1
    header(ws_sum, r, ["Check", "Recomputed here", "Model output", "Match?"])
    r += 1
    mt = ml + 1
    checks = [
        ("Stations open (optimized)", f'=COUNTIF(Stations!$F${s_first}:$F${s_last},"Yes")',
         "sites_open", "0", 0),
        ("Average miles (optimized, demand weighted)", f"='Metro summary'!G{mt}", "avg_miles", "0.0", 0.05),
        ("Unserved ZIPs (optimized)", f'=COUNTIF({zr("K")},"UNSERVED")', "unserved_zips", "0", 0),
    ]
    for lab, formula, key, fmt, tol in checks:
        ws_sum.cell(r, 1, lab).font = font()
        c = ws_sum.cell(r, 2, formula)
        c.font = font()
        c.number_format = fmt
        c2 = ws_sum.cell(r, 3, f"=C{row_of[key]}" if key in row_of else None)
        c2.font = font()
        c2.number_format = fmt
        ws_sum.cell(r, 4, f'=IF(ABS(B{r}-C{r})<={tol},"Yes","Check")').font = font()
        r += 1
    widths(ws_sum, {"A": 48, "B": 16, "C": 16, "D": 12, "E": 12})

    # ---------------- About ----------------
    title(ws_about, "Delivery Station Topology Planner: Tennessee and South Carolina")
    lines = [
        ("What this is", True),
        ("A portfolio project. It chooses which delivery stations to open in Tennessee and South Carolina, "
         "which ZIP codes each one serves, and in what order new stations should open over five years.", False),
        ("", False),
        ("What it is not", True),
        ("It does not use any company's delivery data. Demand is a proxy built from Census households, income and density. "
         "Candidate sites are statistical centers, not real locations. Capacity, cost, radius and growth "
         "trend values are placeholders I chose and tested.", False),
        ("", False),
        ("Tabs", True),
        ("Summary: baseline against optimized, with a tie out to the model output.", False),
        ("Metro summary: demand, service distance and stations by metro group.", False),
        ("Stations: load and use for each candidate site, with a check against the model.", False),
        ("Scenarios: Week 3 growth scenarios, with charts.", False),
        ("Build schedule: the year each new station opens, by scenario.", False),
        ("Inputs: settings used by the model. Station capacity can be changed to see use update.", False),
        ("Scenario data and Zips: the data behind the other tabs.", False),
        ("", False),
        ("Colors", True),
        ("Blue text is a typed value. Black text is a formula. The yellow cell is the one input to change.", False),
        ("", False),
        ("Known limits are in docs/assumptions.md. Rebuilt by src/package_outputs.py.", False),
    ]
    for i, (txt, bold) in enumerate(lines, start=3):
        c = ws_about.cell(i, 1, txt)
        c.font = font(bold=bold)
        c.alignment = Alignment(wrap_text=True, vertical="top")
    ws_about.column_dimensions["A"].width = 110

    OUT.mkdir(exist_ok=True)
    wb.save(XLSX)


# ------------------------------------------------------------------
# 3. Interactive map
# ------------------------------------------------------------------
def build_map(z, sites, sched_long, names):
    import branca.colormap as cm
    import folium

    radius = BASE["radius"]
    cmap = cm.LinearColormap(["#2e7d32", "#f9a825", "#c62828"], vmin=0, vmax=radius,
                             caption="Road miles from ZIP to its station")
    m = folium.Map(location=[34.9, -84.4], zoom_start=6, tiles="OpenStreetMap")

    served = z[z["optimized_site"] != "UNSERVED"]
    max_d = float(z["demand"].max())
    g_zip = folium.FeatureGroup(name="ZIPs (color = miles to station, size = demand)", show=True)
    for r in served.itertuples(index=False):
        folium.CircleMarker(
            [r.lat, r.lon], radius=2.5 + 8 * float(np.sqrt(r.demand / max_d)),
            color="#555555", weight=0.4, fill=True, fill_color=cmap(min(float(r.optimized_miles), radius)),
            fill_opacity=0.65,
            tooltip=f"ZIP {r.zcta} ({r.metro})<br>Station {r.optimized_site}<br>{r.optimized_miles:.0f} miles",
        ).add_to(g_zip)
    g_zip.add_to(m)

    g_un = folium.FeatureGroup(name="Unserved ZIPs", show=True)
    for r in z[z["optimized_site"] == "UNSERVED"].itertuples(index=False):
        folium.CircleMarker([r.lat, r.lon], radius=2.5, color="#777777", weight=0.5, fill=True,
                            fill_color="#bbbbbb", fill_opacity=0.8,
                            tooltip=f"ZIP {r.zcta} ({r.metro})<br>Unserved: no open station within {radius} miles"
                            ).add_to(g_un)
    g_un.add_to(m)

    cap = BASE["capacity_share"] * float(z["demand"].sum())
    load = served.groupby("optimized_site")["demand"].agg(["count", "sum"])
    later = {}
    for r in sched_long.itertuples(index=False):
        later.setdefault(r.site_id, []).append(f"{r.scenario}: Year {r.year_opened}")

    g_open = folium.FeatureGroup(name="Open stations (Week 2)", show=True)
    g_closed = folium.FeatureGroup(name="Candidate sites, closed", show=True)
    for r in sites.itertuples(index=False):
        if r.opened_optimized:
            cnt, dem = (load.loc[r.site_id, "count"], load.loc[r.site_id, "sum"]) if r.site_id in load.index else (0, 0)
            folium.CircleMarker(
                [r.lat, r.lon], radius=9, color="black", weight=1.5, fill=True, fill_color="#1565c0",
                fill_opacity=0.95,
                tooltip=f"{r.site_id} ({r.metro})<br>{int(cnt)} ZIPs, use {100 * dem / cap:.0f}%",
            ).add_to(g_open)
        else:
            extra = "<br>Opens later: " + "; ".join(later[r.site_id]) if r.site_id in later else ""
            folium.CircleMarker(
                [r.lat, r.lon], radius=7, color="#666666", weight=1.5, fill=False,
                tooltip=f"{r.site_id} ({r.metro})<br>Closed in the Week 2 layout{extra}",
            ).add_to(g_closed)
    g_open.add_to(m)
    g_closed.add_to(m)

    info = sites.set_index("site_id")
    colors = ["#ef6c00", "#8e24aa", "#00838f", "#6d4c41", "#c2185b"]
    for si, nm in enumerate(names):
        g = folium.FeatureGroup(name=f"New stations: {nm}", show=(si == 0))
        sub = sched_long[sched_long["scenario"] == nm]
        for r in sub.itertuples(index=False):
            folium.CircleMarker(
                [info.loc[r.site_id, "lat"], info.loc[r.site_id, "lon"]], radius=11,
                color=colors[si % len(colors)], weight=3, fill=True,
                fill_color=colors[si % len(colors)], fill_opacity=0.5,
                tooltip=f"{r.site_id} ({info.loc[r.site_id, 'metro']})<br>{nm}: opens in Year {r.year_opened}",
            ).add_to(g)
        g.add_to(m)

    cmap.add_to(m)
    folium.LayerControl(collapsed=False).add_to(m)
    OUT.mkdir(exist_ok=True)
    m.save(str(MAP))


# ------------------------------------------------------------------
def main():
    z, sites, scen, sched, comp = load()
    names = list(dict.fromkeys(scen["scenario"]))
    sched_long = parse_schedule(sched, names)

    print("1. SQL database and queries ...")
    results = make_database(z, sites, scen, sched_long)
    print(f"   Saved {DB} and {len(QUERIES)} queries in {SQLDIR}/")
    print(f"   Query results saved in {OUT / 'sql_results'}/")
    print("\n   Metro summary (from sql/01_metro_summary.sql):")
    print("   " + results["01_metro_summary"].to_string(index=False).replace("\n", "\n   "))

    try:
        print("\n2. Excel workbook ...")
        build_workbook(z, sites, scen, sched, sched_long, comp, names)
        print(f"   Saved {XLSX}")
    except ImportError:
        print("   Skipped: run  pip install openpyxl  and try again.")

    try:
        print("\n3. Interactive map ...")
        build_map(z, sites, sched_long, names)
        print(f"   Saved {MAP}  (double click it to open in your browser)")
    except ImportError:
        print("   Skipped: run  pip install folium  and try again.")


if __name__ == "__main__":
    main()
