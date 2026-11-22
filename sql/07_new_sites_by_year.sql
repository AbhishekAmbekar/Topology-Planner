-- Which stations open in which year, by scenario
SELECT scenario, year_opened, COUNT(*) AS new_stations, GROUP_CONCAT(site_id, ', ') AS stations
FROM build_schedule
GROUP BY scenario, year_opened
ORDER BY scenario, year_opened;
