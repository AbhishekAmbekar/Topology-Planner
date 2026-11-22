-- Worst year for each scenario
SELECT scenario,
       MAX(demand_index)           AS demand_index_year5,
       MAX(sites_open)             AS stations_year5,
       MAX(busiest_pct_of_target)  AS busiest_station_peak,
       MAX(demand_over_target_pct) AS worst_demand_over_target_pct
FROM scenario_summary
GROUP BY scenario
ORDER BY demand_index_year5, scenario;
