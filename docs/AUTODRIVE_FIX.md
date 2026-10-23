# Highway Autodrive repair — 2026-10-23

Build: `../../builds/BeamNG.Earth-1.6.0-beta-autodrive-fix.exe`

Autodrive could repeatedly brake and accelerate as streamed road graphs replaced its driving plan. When a route broke, its recovery could switch the player's vehicle to ordinary traffic AI, losing the destination and allowing loops. The path-start call also lost one of Lua's two return values, so it failed to attach the plan to the forward edge beneath the car.

## Changes

- Capture both road-edge node IDs, trim passed nodes, check one-way direction, and distinguish stacked roads using height. An unreachable starting edge causes a hold and retry rather than a backwards target.
- A vehicle extension coordinates the new map with the GPS path. After the stock AI clears its route for a new map, `ai.setPath` restores the remaining route without resetting its speed and gearbox controls. Later route additions use the same API's suffix-extension behavior. A genuine changed turn or final destination can still replace the route.
- Validate all path edges against the vehicle's actual graph. The former four-second timeout no longer sends a path on an assumed graph.
- Keep a longer valid route when a temporary arrows result is empty or shorter. Refresh the road clip on each 128 m ground movement while Autodrive is active and request route extensions before the speed-dependent braking distance to a temporary endpoint.
- Hold and retry when no usable route remains; never switch the player's car to traffic mode. A missing portion of the planned route no longer selects an unrelated road nearest the distant destination.
- Recover when a moving car travels at least 60 m without advancing 10 m along its route for 20 seconds. Allow 45 seconds for stationary traffic before recovery. Request a new route from the current location and heading, with a controlled hold while it is planned. After three unsuccessful recoveries, return control with an explanation instead of restarting indefinitely. Paused time does not count.
- A slow terrain request alone no longer commands a full stop on road already loaded. Disconnects and resyncs still brake, the AI still stops at the end of a finite loaded route, and the existing ground-edge guard continues to protect the world boundary.
- Turning Autodrive off releases its controls and cancels the vehicle bridge. Level changes clear active Autodrive ownership.

## Validation

Six LuaJIT regression suites pass with **447 assertions**, including two new Autodrive suites. They exercise the real GPS module and vehicle extension against a model of the installed engine's map-reset and path-extension semantics. Scenarios include multiple path requests before a vehicle frame, ordinary extension, final destinations, missing or reversed edges, overpasses, loading holds and resumption, server disconnects, short traffic stops, paused time, moving in circles, and bounded failed recovery. Existing core robustness tests also verify that late terrain still leaves the ground-edge guard active.

**34 Python tests** pass across navgraph generation, European traffic geometry, routing, and the Autodrive recording tool. All 104 mod/test Lua files compile under LuaJIT. The packaged executable is checked against every current server source module and every bundled mod asset, including the new vehicle extension, and its `--server --help` command is tested.

An in-game highway drive has not been performed: the game's MCP endpoint was unavailable. These checks establish route-management behavior, not measured driving smoothness or collision-free operation in every vehicle and interchange. Loading beyond the available ground can still require a pause.

Test logs, source backups, and packaging verification are under `build/autodrive-fix/`. Existing highway, streaming, and caching changes are included in the new build.

## Use

Close the old companion and BeamNG.drive, run the new executable, and load BeamNG.Earth. The launcher installs the bundled mod, including its vehicle extension. Keep the existing download cache. The new executable is separate from the earlier builds, which remain available.
