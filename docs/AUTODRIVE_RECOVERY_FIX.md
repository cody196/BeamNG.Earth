# Autodrive stationary recovery and diagnostics — 2026-10-23

The supplied log contains `Path rejected: waiting for more road on the GPS route`
at 513.551 seconds. The full local game log also records a route retry around
561 seconds and another endpoint rejection around 699 seconds. It does not
contain enough route/vehicle state to identify every later stop. No live game
drive was performed for this change; the game's MCP endpoint was unavailable.

## Changes

- Bound the route matcher's preference penalty below forward progress on an
  otherwise valid forward edge. Previously a changing lateral offset inside the
  allowed 25 m corridor could make stopping score better than continuing along
  a connected highway. Keep corridor, direction, deck, and connectivity checks.
- Allow short junction joins (at most 20 m, with at most 5 m backwards projected
  progress). Dataset alignment at a connector must not break an otherwise
  continuous route. Costs remain nonnegative, so the search does not introduce
  repeated-node loops.
- Replace the fixed 120 m restart gate with 60 m or the vehicle's speed-based
  endpoint guard plus 20 m, whichever is larger. A short valid extension can
  restart a stationary car without repeatedly accepting its exhausted path.
- Preserve the known carriageway while holding. After an eight-second route
  hold, request fresh road data even without movement. The server normally
  rebuilds after 400 m; a stationary car could otherwise keep an incomplete
  graph indefinitely. Server-side refresh requests are limited to one per
  20 seconds, coalesce, and survive a request arriving during an existing build.
- Retry the full route during persistent holds, with the existing bounded
  recovery count and rate limit. Toggling a blocked drive now requests a route
  from the current position and refreshes road data rather than simply reusing
  the blocked state. Real destination arrival still requires both proximity
  and remaining route distance.

## Diagnostics

Enabled by default under the `beamngEarthAutodrive` log tag in BeamNG's
`beamng.log`. State events cover enable/disable, destination, route request,
reply/failure/timeout, hold/resume, graph refresh, recovery and vehicle rejection.
Vehicle events distinguish initial start, route replacement, map restoration,
extension and hold. Rejections include the command ID and reason on both sides.

Ten-second heartbeats include position, heading, speed, route version, graph/map
serials, command ID, remaining distance, off-route distance, wait duration,
pending request, recovery count, matched start/end nodes, path length, and
counts of edges rejected by corridor, direction and lookahead checks. Repeated
graphics frames do not spam the log. `gps.DEBUG` and vehicle bridge `DEBUG`
can disable routine diagnostics; `gps.TRACE` remains the optional verbose path
trace. The server log records stationary refresh requests.

## Validation

- 495 Lua assertions across route matching, GPS, vehicle bridge, integration,
  graph handling and core readiness/robustness.
- 39 Python tests covering graph generation/refresh, routing, road rules and the
  Autodrive diagnostic tool, including the real server protocol dispatch.
- The new regression tests fail against the previous interchange-fix executable.
- Simulated 20 km highway drive through 100 streamed map replacements, without
  false endpoints, repeated AI starts or unexpected rerouting.
- 84 matcher replays against a cached 2,648-node graph and a road-derived 2.1 km
  highway reference, with 0/4/12 m offsets. This exercises real road geometry,
  not a captured OSRM response or live steering physics.
- `git diff --check` passes. Packaging verification compares embedded server
  modules and mod assets to the workspace and smoke-tests `--server --help`.

Build scripts and detailed results are under ignored `build/autodrive-recovery-fix/`.
The separate executable is `../builds/BeamNG.Earth-1.6.0-beta-autodrive-recovery-fix.exe`.
