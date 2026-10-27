# Combined custom build — 1.6.3-beta

This build combines `fix/bridge-underpass-overpass` and
`port/road-infrastructure-1.6.3` on `integration/bridges-road-infrastructure`.
Both original branches remain separate for their individual pull requests.

## Combined v2 — marking corrections and completeness audit

- Fixed white sections in the yellow/orange driver-left boundary at left-side
  ramp merges. The outside edge now keeps its color through the taper; lane
  separators and the shared inner boundary of right-side ramps remain white.
- Restored yellow left edges on one-way ramps classified as primary, secondary,
  or tertiary roads, and on mapped divided carriageways of those classes.
- Preserved yellow edge paint around continuous highway corners and used the
  same color rule for lane transitions, bridges, and tunnels.
- Audited all **133 changed files** from both source branches: **123 match a
  branch exactly**, and **10 contain reviewed integration/marking changes**.
  No feature files or modified Python functions were omitted. Autosave, tree
  and grass density, signs, road infrastructure, and bridge fixes are retained.
- Added regression cases for road classifications, both travel directions,
  entrance/exit ramps, reversed map geometry, bridge/tunnel output, and corners.

## Included changes

- Bridge junction continuity, extended approach decks, collision surfaces, and
  clearance checks across the full width of stacked bridges.
- Road and bridge widths, lane transitions, ramp merges, roundabouts, intersection
  pavement, regional markings, highway signs, and mile markers.
- BeamMP per-player autosave and resume, including account and guest identity,
  saved position, heading, road height, and supported vehicle configuration.
- Tree-density presets from very low through maximum, plus grass-density settings.
- Road-loading optimizations, CPU worker budgets, improved approach terrain detail,
  HTTPS packaging fixes, and invalidation of outdated generated geometry.

## Integration fixes

- Promoted bridge approaches retain lane counts and road widths as well as their
  deck and collision mesh.
- The final bridge continuity pass preserves flush short overpasses, avoiding
  reintroducing small crests removed by the road-infrastructure changes.
- The app and BeamMP server ZIP are built from the same combined source tree.

## Updating BeamMP

Use `BeamNG.Earth-1.6.3-beta-combined-v2.exe` with
`BeamNG.Earth-BeamMP-Server-1.6.3-beta-combined-v2.zip` from this build.

1. Stop the BeamMP server and replace its plugin and client ZIP using the server
   archive. Reapply any customized plugin settings.
2. Keep `ServerConfig.toml`, both `data/bnge_player_positions*.json` files, and
   clients' existing guest-token settings. The archive contains no player saves.
3. Restart the server, fully close and reopen BeamNG using the combined app, then
   reconnect. Drive, allow the default ten-second save interval to pass, and
   disconnect/rejoin to check restoration.

The clean bridge-only app did not include this custom multiplayer resume client.
See [BeamMP setup and persistence details](beammp/README.md) for configuration,
older-save migration, and diagnostic messages. Damage, fuel, and attached trailers
are not part of the existing saved vehicle configuration.

## Validation

- 679 Python tests passed, with 2 platform/tool-dependent skips, across 49 modules.
- 5,476 Lua assertions passed across 66 test files, including server checkpoint
  persistence/restart, client restoration, guest identity, settings, and trees.
  The separate scoping check requires Unix `find` and a standalone LuaJIT binary
  and could not run in this Windows test environment.
- The previous integration's six cached Seattle road/elevation replays completed with no height mismatch at
  shared bridge endpoints. The reported stacked crossing at
  47.57282, -122.31967 retained 6.15 m of modeled usable clearance after merging.
- Some short or inconsistent mapped approaches still produce steep grades or
  insufficient headroom elsewhere in those networks. These are reported by the
  solver; this build does not guarantee truck clearance at every crossing.
- Live multiplayer reconnection and in-game driving still need confirmation.
