# Phase 6 probabilistic multi-hypothesis map matching

## Scope and runtime boundary

Phase 6 constrains a completed Phase 5 local ENU prior to a locally cached road graph. It performs no route planning, accepts no destination or route polyline, and does not implement GNSS reacquisition. Its runtime inputs are only the Phase 5 fields `elapsed_s`, local east/north, speed, yaw, horizontal position sigma, and the static road cache. The matcher rejects phone-GNSS, VBOX, or reference-labelled columns. `EvaluationReference` is accepted only by `evaluate_map_match` after all road hypotheses and matched positions are complete.

Phone GNSS strictly before blackout supplies the same local-frame origin already used by Phase 5 and initializes the first road hypothesis. No phone GNSS at or after blackout start is used. VBOX never selects a road, transition, prior, or fallback.

## Static map cache

The cache is `data/map_cache/io_vnbd_s1/road_graph.json.gz`, accompanied by `metadata.json`. It was downloaded once from OpenStreetMap through Overpass and covers the fixed WGS84-like envelope 52.3944–52.4239 N, -1.6074–-1.5013 E. That envelope is the full S1 smartphone-GNSS extent plus a fixed buffer. It is not selected per blackout and does not depend on VBOX or a future route. Runtime evaluation is offline.

The compact cache contains 23,103 nodes and 43,488 directed segment edges in 1,044,506 bytes. Configured motor-vehicle classes are motorway/link, trunk/link, primary/link, secondary/link, tertiary/link, residential, unclassified, service, and living street. The actual region contains primary, residential, secondary/link, service, tertiary/link, trunk/link, unclassified, and living-street edges. Footways, cycleways, pedestrian paths, steps, and access/private motor-vehicle ways are excluded. Names, class, maxspeed text, and one-way metadata are retained when OSM supplies them; missing values are not invented.

The JSON cache stores OSM latitude/longitude. At scenario initialization every edge is converted with the project's existing short-range spherical tangent approximation using the strictly pre-blackout phone origin: +X East, +Y North, metres. Because IO-VNBD does not specify a datum/EPSG, this is documented as a local approximation rather than a surveyed CRS. Round-trip, sign, finite-coordinate, projection, bearing, and distance-preservation tests guard against axis or unit mistakes.

## Candidate generation and geometry

A 75 m uniform-grid spatial index maps edge bounding boxes to cells. A radius query inspects only intersecting cells and then performs exact point-to-polyline projection. Degenerate/non-finite edges are skipped. The local tangent bearing is computed on the polyline segment containing the closest projection, clockwise from North; a long curved way is never assigned one global bearing.

The frozen radius is:

`r = clamp(20 m + 2 * horizontal_position_sigma, 15 m, 220 m)`

At most 10 candidates survive per sample. Each contains edge ID, projected point, along-edge distance/fraction, distance, local bearing, road class/name, one-way flag, score components, and displayed probability.

## Scores and hypotheses

All probabilities are accumulated as finite log scores. The distance emission is

`-0.5 * (road_distance / clamp(0.5 * position_sigma, 5 m, 60 m))^2`.

The heading emission uses circular difference:

`-0.5 * (wrap(yaw - local_road_bearing) / 45 deg)^2`.

Both directions are represented for a bidirectional road. A legal one-way has only its permitted directed edge, and an opposing heading adds a -10 log penalty. A cautious -1 to -1.5 log term discourages very high predicted speeds on residential/service/living-street edges without inventing missing speed limits.

Expected step travel is the mean of Phase 5 displacement and `speed * dt`. Directed network travel between candidate projection states is the same-edge forward distance, or remaining previous-edge length + limited Dijkstra distance between endpoint nodes + current along-edge length. Dijkstra is used only between candidate states, never to a destination. The transition distance score is

`-0.5 * ((network_distance - expected_distance) / 12 m)^2`.

Road-bearing change is compared with estimator yaw change using a 35-degree circular Gaussian. Edge changes cost 0.25 log units; disconnected or over-limit transitions cost 22 log units. Stationary samples use a tighter 2 m distance scale. A Viterbi-style beam retains the best predecessor for each current candidate and then the best 10 current hypotheses. This is causal: no future sample is revisited.

Displayed hypothesis probabilities use stable log-sum normalization. A sample is ambiguous when top-minus-second probability is below 0.10 or normalized entropy exceeds 0.72. Status is `CONFIDENT`, `AMBIGUOUS`, `DEGRADED`, or `NO_CANDIDATE`.

## Safeguards and naive baseline

No candidate returns the unconstrained Phase 5 point and restarts candidate search on the next sample. A top probability below 0.12 or correction above 120 m also returns the unconstrained point as `DEGRADED`; the tracker is not allowed to teleport farther. Search radius is capped at 220 m, candidate count and beam width at 10, and malformed map geometry cannot crash the estimator.

`nearest_road_match` is the intentionally naive baseline. It independently projects every sample to the closest road within the same uncertainty radius, ignoring heading, legal direction, connectivity, and history. It demonstrates how reference error can occasionally look good by accident while branch identity and temporal consistency remain uncontrolled.

## Freeze protocol and results

Three 60-second Phase 6 development intervals—1120, 2020, and 4000 session seconds—sit wholly inside the Phase 5 validation blocks and outside every held-out quarantine. Three small profiles compared radius, top K/beam, distance/heading/transition scales, and ambiguity threshold for EKF and Hybrid priors. `WIDE_CONTINUITY + H1_HYBRID_EKF_ML` had the lowest development mean drift; profiles tied on Hybrid final drift, so lower mean RMSE selected the wide profile. The configuration was frozen before the six held-out scenarios ran and was never changed from benchmark truth.

Held-out final Hybrid probabilistic-map drift was 16.533%, 21.995%, 27.387%, 38.034%, 53.798%, and 3.887% for 10, 30, 60, 120, judge-45, and surprise-75 seconds. It improved the best Phase 5 estimator in two of six scenarios and regressed four; median best-Phase-5 drift was 22.895% versus 24.691% for fixed Phase 6. This is not a universal accuracy win. The strongest remaining failures are wrong connected branches, parallel-road ambiguity, distance/speed error that a road graph cannot repair, OSM/data-date mismatch, and growing uncalibrated Phase 5 uncertainty.

The frozen production path measured 43.37 candidate-generation samples/s, 41.68 probabilistic-map samples/s, and 34.53 complete Phase5+Phase6 samples/s on CPU, above the approximately 10 Hz input. Complexity is bounded by local grid hits, top K, beam width, and limited candidate-to-candidate graph searches; the full road network is not scanned per sample.

## Reproduction

```powershell
.venv\Scripts\python.exe tools\build_map_cache.py --config configs\phase6\io_vnbd_s1_map.json
.venv\Scripts\python.exe tools\inspect_map_cache.py
.venv\Scripts\python.exe tools\run_phase6_validation.py
.venv\Scripts\python.exe tools\run_phase6_benchmarks.py
.venv\Scripts\python.exe tools\run_map_matching.py --scenario S1_60_STOP_GO
.venv\Scripts\python.exe tools\run_map_matching.py --session S1 --start 4850 --duration 45 --scenario-id S1_45_JUDGE
.venv\Scripts\python.exe tools\run_map_matching.py --scenario S1_PHASE5_SURPRISE
```

Phase 7 may add GNSS-active/IDR/reacquisition state handling and measured smooth reconvergence. It must preserve this runtime/reference boundary and must not reinterpret Phase 6 as route following.
