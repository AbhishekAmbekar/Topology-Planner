-- How full each station is, and how far its ZIPs have to travel
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
