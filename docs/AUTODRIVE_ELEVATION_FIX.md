# Autodrive graph elevation correction — 2026-10-23

## Recorded failure

The new log identifies a deterministic height mismatch, not a failed recovery
request. At 542.529 seconds, GPS held the car with `match=no_forward_edge`.
Graph refreshes and fresh routes completed, but the same edge remained rejected.

The cached `20261023-205710-5320/navgraph_2_25.json` reproduces the rejection:

| Position (local metres) | Lateral distance | Old car minus graph height | Corrected height difference |
| --- | ---: | ---: | ---: |
| 97.2, 8111.8, 298.1 | 3.04 m | -5.02 m | +0.15 m |
| 90.7, 8169.9, 298.0 | 3.08 m | -5.12 m | +0.13 m |

The road direction agrees with the car. Both the GPS acquisition code and the
vehicle bridge deliberately reject roads on another deck by requiring a height
difference no greater than 5 m.

## Cause and correction

`server/navgraph.py` stored ground-node Z as the geographic elevation returned
by the DEM/grading sampler. The terrain and road meshes instead convert this
elevation into the anchor's local east/north/up (ENU) frame. Earth curvature
makes these values diverge with distance from the anchor: approximately five
metres at eight kilometres. The graph therefore floated above its own highway
until the deck guard rejected it. Rerouting rebuilt the same wrong heights.

Convert sampled ground elevations to ENU before assigning node Z. Bridge
profiles already provide ENU heights and must retain those values without a
second conversion. The lateral, direction, connectivity and 5 m deck guards
remain unchanged.

Diagnostics now report `roadReason`, `roadHeightError`, and `roadLateral` in
the existing Autodrive heartbeat, and retain the candidate edge details in GPS
status. This distinguishes a height rejection from missing road data.

## Validation

- 498 Lua assertions, including the recorded coordinates, bridge/deck rejection,
  route following, streaming, stationary recovery and diagnostic fields.
- 42 Python tests, including ground-height alignment at 8.17 km and 20 km,
  elevated anchors, and preservation of bridge profiles far from the origin.
- The new ground-height tests fail against the previous recovery-fix executable.
- Replay of the captured highway graph rejects both recorded positions before
  conversion and accepts them afterward in both GPS and vehicle forward-target
  selection. Only that highway's ground heights are converted in the replay;
  bridge profiles elsewhere in the captured graph are untouched.
- Packaging checks compare every embedded mod asset and server module with the
  workspace, verify the source ID, and run `--server --help`.

This is a captured-state replay and automated testing, not a live in-game drive.
Build artifacts and replay results are in ignored `build/autodrive-road-acquisition-fix/`.
Use `../builds/BeamNG.Earth-1.6.0-beta-autodrive-elevation-fix.exe`, closing the
previous companion server and BeamNG first so both server and mod are updated.
