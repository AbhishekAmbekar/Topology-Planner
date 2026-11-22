-- Counties with the fastest yearly population growth (capped in Week 3)
SELECT z.state, z.county_name, COUNT(*) AS zips, ROUND(SUM(z.demand)) AS demand,
       ROUND(100.0 * MAX(z.cagr), 1) AS yearly_growth_pct
FROM zips z
GROUP BY z.state, z.county_name
ORDER BY yearly_growth_pct DESC, demand DESC
LIMIT 10;
