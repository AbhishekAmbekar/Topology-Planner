# Assumptions and Limits

Project: Delivery station topology planner for Tennessee and South Carolina

This project uses public data and my own assumptions. It does not use any company's delivery data. Candidate sites are statistical centers, not real locations. Every number marked "placeholder" is a stand in that I test in the sensitivity runs.

## 1. Scope

| Item | Choice |
|---|---|
| Region | Tennessee and South Carolina |
| Unit of demand | ZIP code (Census ZCTA) |
| Planning question | Where should stations go, which ZIPs does each serve, and in what order should sites open |

## 2. Data sources

| Data | Source |
|---|---|
| Households, population, median income | Census ACS 5 year estimates, 2023 release (covers 2019 to 2023), tables B01003, B11001, B19013 |
| ZIP to county and state | Census ZCTA to county relationship file (2020). A ZIP that crosses counties is assigned to the county with the most land. |
| ZIP center point and land area | Census Gazetteer ZCTA file, 2023 |
| County population growth | Census county population estimates, Vintage 2025 (April 2020 to July 2025) |

## 3. Assumptions

| Assumption | Value | Why | How I test it |
|---|---|---|---|
| Minimum ZIP size | 500 households | Removes tiny rural ZIPs with little demand | Rerun at 250 and 1,000 |
| Income index | ZIP income divided by state median ZIP income, capped 0.6 to 1.6 | Higher income areas tend to order more online. This is an assumption, not measured. | Rerun with no income index |
| Density factor | 0.8 under 100 households per sq mi, 1.0 from 100 to 500, 1.15 from 500 to 1,500, 1.3 above 1,500 | Dense areas are cheaper to serve and often order more. Placeholder values. | Change each factor by 20 percent |
| Demand proxy | Households x income index x density factor | No public delivery volume by ZIP exists | See the two rows above |
| Candidate sites | 28 total (16 Tennessee, 12 South Carolina), from demand weighted k means, snapped to the nearest ZIP | Reproducible and easy to explain | Rerun with 20 and 36 sites |
| Road distance | Straight line distance x 1.3 | Simple stand in for road networks | Tested at 1.2 and 1.4 |
| Station capacity | 10 percent of total two state demand per site (placeholder) | No public figure. Means at least 10 sites are needed. | Tested at plus and minus 20 percent |
| Cost to open a site | Equal to moving one full station's demand 10 miles (placeholder) | No public figure | Tested at plus and minus 20 percent, and at 5 miles |
| Maximum drive radius | 45 road miles (placeholder) | Keeps service times realistic | Tested at 35 and 60 miles |
| Minimum coverage | 95 percent of demand served within the radius (placeholder) | Real networks do not serve every rural ZIP from a station | Tested at 90 and 98 percent |
| Cost of leaving a ZIP unserved | 50 miles of driving per unit of demand (placeholder) | Kept low so the model does not open sites for tiny pockets | Not tested |
| Baseline | Naive layout: the 14 busiest sites, each ZIP to its nearest open site, no capacity checks | A simple point of comparison. It is not a real network. | Rerun with 22 baseline sites |
| Lead time for new sites | New sites can open from Year 1 (Base and High growth) or from Year 3 (Delayed scenarios) (placeholder) | Sites take time to approve and build | Delayed scenarios |
| Safety buffer | A station counts as full at 90 percent of its Week 2 capacity (placeholder) | Real planners do not run stations at 100 percent | Not tested |
| Launch limit | At most 2 new sites open per year (placeholder) | Stands in for a budget limit | Not tested |
| Cost of demand above the buffer | 150 miles of driving per unit of demand (placeholder) | Sets how long the plan tolerates a busy station before it opens a site | Test at 500 |
| Demand growth | County population growth from Census estimates (2020 to 2025), capped at minus 1 to plus 5 percent a year. Base: county growth plus 2 percent a year for the online shopping trend. High: 1.5 times county growth plus 4 percent a year (placeholders for the multiplier and the trend) | County growth is sourced. The online shopping trend is an assumption. | Base and High growth scenarios |

## 4. Data results from the first run

| Item | Result |
|---|---|
| ZIPs in Tennessee and South Carolina | 1,062 |
| ZIPs dropped for missing data | 0 |
| ZIPs dropped for under 500 households | 227 |
| Share of households dropped by that threshold | 0.89 percent |
| ZIPs kept | 835 (502 Tennessee, 333 South Carolina) |
| Candidate sites | 28 |

## 5. Week 2 results (base case)

| Measure | Baseline | Optimized |
|---|---|---|
| Sites open | 14 | 22 |
| Average miles to station (model output: all ZIPs for baseline, served ZIPs for optimized) | 24.7 | 15.5 |
| Average miles to station, same served ZIPs | 22.5 | 15.5 |
| Longest trip, miles | 135.8 | 45.0 |
| Demand served within 45 miles | 81.3 percent | 95.1 percent |
| Overloaded sites | 5 | 0 |
| Highest station use | 115 percent | 99 percent |
| Network cost (placeholder units, sites plus driving) | 209.4 | 198.7 |

Notes:
- The baseline breaks the capacity and radius rules. The optimized layout follows them.
- The cost units are placeholders. They show relative size, not dollars.
- The busiest optimized site is in central Nashville at 99 percent use. Nine small rural sites run at 13 to 25 percent use. They exist because of the coverage rule.

## 6. Sensitivity results (optimized layout)

| Scenario | Sites open | Avg miles | Highest use | Demand covered |
|---|---|---|---|---|
| Base case | 22 | 15.5 | 99% | 95.1% |
| Capacity minus 20% | 25 | 14.7 | 100% | 95.0% |
| Capacity plus 20% | 22 | 15.5 | 88% | 95.1% |
| Site cost minus 20% | 22 | 15.5 | 97% | 95.1% |
| Site cost plus 20% | 21 | 16.7 | 98% | 95.0% |
| Coverage 90% | 18 | 15.0 | 99% | 90.1% |
| Coverage 98% (97.4% was the most reachable) | 27 | 15.0 | 89% | 97.4% |
| Radius 35 miles (all 28 sites open) | 28 | 13.2 | 86% | 94.1% |
| Radius 60 miles | 16 | 18.4 | 100% | 95.0% |
| Circuity 1.2 | 20 | 14.7 | 100% | 95.0% |
| Circuity 1.4 | 24 | 16.1 | 99% | 95.2% |

What the tests show:
1. The number of sites moves most with the radius (16 to 28 sites) and the coverage target (18 to 27 sites).
2. Capacity matters less (22 to 25 sites). Site cost matters least (21 to 22 sites).
3. Network cost is not compared across scenarios, because some tests change the cost units themselves.

## 7. Week 3 build plan results

The Week 2 optimized network (22 sites) is treated as the network in place at Year 0. Each year the model keeps all open sites, may open up to 2 new sites from the 6 closed candidates, and re assigns ZIPs. Station use is measured against the 90 percent target, so 100 means a station is at the target.

Year 5 summary:

| Scenario | Demand (Year 0 = 100) | Sites open | New sites | Busiest station (% of target) | Demand above target |
|---|---|---|---|---|---|
| Base | 118 | 24 | 2 | 101 | 0.2% |
| High growth | 135 | 27 | 5 | 113 | 1.2% |
| Delayed launches (Base growth) | 118 | 24 | 2 | 101 | 0.2% |
| High growth, delayed | 135 | 27 | 5 | 113 | 1.1% |

Year each new site opens:

| Site | Metro | Base | High growth | Delayed launches | High growth, delayed |
|---|---|---|---|---|---|
| SC-04 | Other | Year 3 | Year 2 | Year 3 | Year 3 |
| TN-13 | Knoxville | Year 4 | Year 3 | Year 4 | Year 3 |
| TN-15 | Nashville | | Year 3 | | Year 4 |
| SC-02 | Greenville-Spartanburg | | Year 4 | | Year 4 |
| TN-01 | Other | | Year 4 | | Year 5 |

Demand above the 90 percent target, High growth against High growth with delayed launches:

| Year | High growth | High growth, delayed |
|---|---|---|
| 1 | 0.3% | 0.2% |
| 2 | 0.2% | 0.9% |
| 3 | 0.5% | 0.5% |
| 4 | 0.4% | 1.0% |
| 5 | 1.2% | 1.1% |

What the results show:
1. SC-04 and TN-13 open in every scenario. They are the safe bets.
2. Under Base growth, the network has room for about three years. Delaying launches to Year 3 changes nothing.
3. TN-15 (Murfreesboro area) opens only under high growth.
4. Delayed launches under high growth cause the most stress in Year 2 (0.9 percent of demand above target against 0.2 percent) and Year 4.
5. Under high growth, the plan runs short of useful candidate sites by Year 5. The busiest station reaches 113 of target, about 102 percent of its true capacity.

## 8. Known limits

1. **Border demand is missing.** Data stops at the state line. Fort Mill and Rock Hill in South Carolina belong to the Charlotte market. Chattanooga touches Georgia. Memphis touches Mississippi and Arkansas.
2. **The demand proxy is not real delivery volume.** It is built from households, income, and density.
3. **Candidate sites are statistical centers.** They are not real or available locations.
4. **Distances are estimates.** They are not drive times.
5. **Metro tags are rough.** Each ZIP is tagged to the nearest of ten anchor cities if it is within 40 miles. Some real markets, such as Clarksville, are tagged "Other".
6. **The two states are separate networks.** They do not touch, so results are read by metro.
7. **All sites have the same size and cost.** Real networks use smaller facilities in rural areas.
8. **The model has no delivery speed rule.** A dense ZIP can be served from far away if that is cheaper. Example: Murfreesboro ZIP 37128 is sent to a site about 32 miles away under the base settings.
9. **The candidate list limits some tests.** With a 35 mile radius all 28 sites open. A 98 percent coverage target cannot be reached, only 97.4 percent. More rural candidate sites would be needed.
10. **Each year is planned on its own with a perfect forecast of that year's demand.** Existing sites cannot be expanded or closed.
11. **Only 6 candidate sites are available to open.** Under high growth the plan runs out of useful options by Year 5.
12. **Growth comes from county population, not order volume.** The online shopping trend is a placeholder. County growth is capped at 5 percent a year (Jasper County, South Carolina, was cut from 5.7 percent).
13. **The plan tolerates small overloads.** Because the cost of demand above the buffer is a placeholder, the model sometimes accepts a station slightly over target instead of opening a site early.
