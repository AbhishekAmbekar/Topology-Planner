-- ZIPs the optimized layout leaves unserved
SELECT z.metro, COUNT(*) AS unserved_zips, ROUND(SUM(z.demand)) AS unserved_demand,
       ROUND(100.0 * SUM(z.demand) / (SELECT SUM(demand) FROM zips), 2) AS pct_of_all_demand
FROM zips z
WHERE z.optimized_site = 'UNSERVED'
GROUP BY z.metro
ORDER BY unserved_demand DESC;
