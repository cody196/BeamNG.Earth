# Autodrive bridge/exit matching — 2026-10-23

Build: `../../builds/BeamNG.Earth-1.6.0-beta-autodrive-interchange-fix.exe`

The previous build derived the driving path from ground-marker point-to-point routes. Intermediate points selected nearby road heights using XY distance alone. At an interchange, that could target the crossing bridge and route the car up an exit. BeamNG's `Route done` message means its finite local AI path ended; it does not establish arrival at the remote GPS destination. The installed GPS source was verified to match the preceding build.

## Changes

- Match the driving path directly to the server's route on the local directed road graph. Start on the road under the car, retain known-road continuity near parallel ramps, and follow connected edges in route order. Penalize deviations from the route and reject shortcuts that skip a connecting ramp or cross a corner. Ground-marker snapping no longer controls Autodrive.
- Keep the current highway through a streamed graph rebuild even when an adjacent ramp centreline is slightly closer. Match the car's heading and deck height, and respect one-way edges.
- Preserve legitimate exits: when the server route turns onto the exit and bridge, the matched path follows them.
- Treat a finite non-final path as a loading boundary. The vehicle holds before stock AI finishes it, retains the GPS destination, and resumes when at least 120 m of usable continuation is available. A wait does not start the same tiny path repeatedly. Actual final routes can be shorter.
- Only report GPS arrival when both physical proximity and remaining distance along the planned route satisfy the arrival threshold. Passing beneath a nearby destination is insufficient when its connecting route remains long.

Prior waypoint-pausing, forward-target, terrain-loading and tree-density changes remain included. Old builds are preserved.

## Verification

- The new integration scenarios fail against the previous packaged GPS/vehicle modules: wrong bridge/exit snapping, passing the interchange, temporary endpoint holding, avoiding repeated short-path starts, resuming with new road, and arrival across an interchange.
- Seven LuaJIT suites pass with **480 assertions**. Coverage includes an unrelated exit leading onto a crossing bridge, a planned exit onto that same bridge, parallel stacked roads, single-sided graph edges, one-way travel, missing mainline road, corner shortcuts, source geometry offsets, mainline preservation across graph changes, endpoint waits and automatic continuation.
- **34 Python tests** pass for routing, navgraph, traffic geometry and the recording tool.
- **156 cached-road replays** pass using the user's latest graph snapshot (422 nodes/422 edges), a 2.6 km mainline, moving 780 m road clips, and route offsets of 0/4/12 m. The reference route for these replays comes from the cached mainline geometry, not a captured OSRM response. These exercise actual road topology but do not simulate vehicle steering or tyres.
- Package verification checks all embedded server sources and mod assets, including the new matcher, and runs `--server --help`.

A live highway drive has not been verified. If the required mainline road has not loaded, Autodrive can still wait instead of leaving the planned route. Logs and packaging evidence are under `build/autodrive-interchange-fix/`.

Close BeamNG and the previous companion, run the new executable, then load the level and set the GPS destination. Keep the existing download cache.
