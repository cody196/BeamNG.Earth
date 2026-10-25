# Tree density and highway signs on 1.6.2 beta

Selective migration from `BeamNG.Earth-1.6.1-modified`, retaining the 1.6.2-beta base.

## Settings

Under Mods → BeamNG.Earth → World:

- **Tree density:** Very Low, Low, Medium, High, Very High, Max. High preserves the beta's original density. Changes reuse ranked tree positions and apply gradually within the existing frame budget. Rocks, shrubs, traffic signs and other props retain their original density. The higher presets remain limited by available canopy data.
- **Highway Signs:** controls highway exit/advance panels, overhead destination panels, Interstate mile markers and merge warnings. Requires Roads. Toggling it reuses held sign meshes and does not rebuild physics.

The saved keys are `treeDensity` and `highwaySigns`. The older individual sign keys remain readable for compatibility. Their live Lua setters are retained; the settings page uses the single Highway Signs switch.

## Data and placement

Exit and destination labels use mapped OpenStreetMap sign data. Regional extracts download and index in the background, separately from the beta's road-tag provider. A completed index refreshes sign tiles without replacing roads. Offline mode uses existing indexes and bundled mile references.

Mile numbering uses the bundled Michigan/Kentucky Interstate references and mapped milestones; coverage is not universal. Merge warnings are derived from entrance-ramp connections and placed in clear ground between the ramp and highway. Font/data attribution is in `CREDITS.md`, with the lettering license alongside the textures.

Sign pavement outlines use the 1.6.2 road renderer's existing widths and centre lines. The earlier custom lane tapers, road curves, markings, ramp geometry, grading, terrain options, building-density controls and loading controls were not migrated.

## Integration

`signstream.py` schedules at most two sign jobs after the corresponding road tile is ready. Normal process-based operation uses a dedicated sign pool; the thread fallback uses the same sign builder. Signs use separate `s` tile keys and pooled render-only shapes. They do not satisfy road readiness or retire road ghosts during a rebase. Stale results from departed tiles, old anchors and closed connections are discarded.

The road geometry, terrain, vegetation generation and native kernels remain those of 1.6.2 beta. The tree setting changes client-side thinning only. Build packaging includes sign glyph metadata, mile references, state boundaries, materials and textures. Source installs also need the added `osmium` requirement.

## Validation

Focused sign tests cover mesh layout, source indexing, placement clearance, tile ownership, worker/fallback equivalence, packaging, optional-source failures, refresh, bounded scheduling and anchor changes. Lua tests cover density, settings persistence, toggles, shape-slot ownership, collision isolation and rebase handling.

The original beta's `test_roads.lua` has two collision-reload timing failures under the available LuaJIT test harness; both reproduce with its untouched `roads.lua`. No in-game drive or visual verification was performed as part of this source migration.
