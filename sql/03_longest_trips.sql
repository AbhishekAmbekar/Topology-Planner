-- The 15 ZIPs that add the most demand times miles
SELECT z.zcta, z.metro, z.optimized_site AS station,
       ROUND(z.demand) AS demand, ROUND(z.optimized_miles, 1) AS miles,
       ROUND(z.demand * z.optimized_miles) AS demand_x_miles
FROM zips z
WHERE z.optimized_site <> 'UNSERVED'
ORDER BY demand_x_miles DESC
LIMIT 15;
