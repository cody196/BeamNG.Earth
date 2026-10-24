# Waypoint planning and forward Autodrive targets — 2026-10-23

Build: `../../builds/BeamNG.Earth-1.6.0-beta-autodrive-route-fix.exe`

The supplied game log contains repeated ground-marker route recalculations without a vehicle Lua crash. The companion log confirms that a 110.9 km route was returned, followed by requests from almost the same location. The installed GPS module matches the earlier repair. Inspection of the installed BeamNG AI exposed a mistake that the earlier tests did not model: its manual path is a sequence of targets, starting at `path[1]`, rather than an edge with a rear support node that it automatically skips.

## Corrections

- Route requests and responses continue while physics is paused. Selecting a waypoint in the map can publish the full route before Autodrive is enabled. Driving, arrival detection and stuck timers remain suspended while paused. Changing the destination clears stale arrows.
- Keep the road edge under the car in the GE route for connectivity validation, but pass only forward targets to vehicle AI on activation, rerouting and streamed-map restoration. Recheck position, heading and deck height when the vehicle consumes the request, so a delayed command also drops passed nodes. Preserve the junction immediately ahead when the route turns.
- The bridge owns its route history separately from the arrays that stock AI retains and mutates during path pruning and extension.
- Remove closed detours caused by overlapping waypoint legs at a shared node. The vehicle rejects remaining repeated-node paths before driving.
- Autodrive holds while its route is pending or unavailable instead of starting a nearest-destination fallback on an unrelated road. Failed initial route requests retry, and the map explains the waiting state. Route request/receipt and vehicle rejection diagnostics are logged.

The new build also includes the existing terrain-loading and tree-density changes already present in the workspace. Older executables are preserved.

## Verification

The new regressions first failed against the previous implementation: paused waypoint planning and backward first targets on activation, map restoration and recovery. After the correction, all six targeted LuaJIT suites pass, with **462 assertions**. The tests now model stock AI retaining its input arrays and explicitly check the first target ahead of the vehicle, delayed commands, junctions, overpasses, a changed destination while paused, route failure/retry, and streamed route extension. **34 Python tests** also pass for routing, navgraph, traffic geometry and the Autodrive recording tool.

The stock engine source used to verify path semantics is `lua/vehicle/ai.lua`: `newManualPath`, `planAhead`, and `buildNextRoute`. These checks do not simulate steering/tyre physics. The game's local MCP endpoint refused the connection, so a live highway drive has not been verified.

Packaging verification checks the executable's embedded server modules and all mod assets against the current sources and runs `--server --help`. Local build/test reports are under `build/autodrive-route-fix/`.

Close BeamNG and the previous companion, run the new executable, then load the level and set a waypoint. The launcher installs the updated mod. Keep the existing download cache.
