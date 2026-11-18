-- Demand, service and open stations by metro group (optimized layout)
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
