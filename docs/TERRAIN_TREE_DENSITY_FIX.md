# 1.6.0 terrain loading and tree density fix

The reported `STAC buildings/building_part: 1 items but 0 file boxes` error was rejecting a valid collection. The October 21 dataset has one building-parts file and one aggregate bounding box. The loader discarded the aggregate, assumed every collection supplied additional boxes for its files, and failed every road tile with buildings enabled. Nearby roads never becoming ready also kept scenery waiting and restricted terrain streaming.

## Loading changes

- Accept single-file and aggregate-only STAC collections. Use each item's bounding box to filter files when the collection supplies no per-file index. Preserve the fast per-file path for the larger collections, support relative item links and 3D bounding boxes, and still reject malformed metadata.
- Pin the valid `2026-10-21.0` release already used in the reported session/cache. The source previously contained the invalid identifier `2026-9-23.1`.
- Treat building footprints, parts, infrastructure and water used for building placement as optional within road/building tile assembly. Source I/O failures leave those layers unavailable while roads continue. Required road-source failures still propagate.
- Back off optional source failures for 30 seconds per layer/worker and limit warnings. Mark partial geometry as failed-source output so it cannot become a permanent generated-cache entry. Retry after the cooldown; cache hits remain usable during it.
- Retain the previous pose, cache read/write retry, road geometry cache and terrain-priority fixes. Existing download caches can be reused without clearing them.

The collection behavior follows the [STAC collection specification](https://github.com/radiantearth/stac-spec/blob/master/collection-spec/collection-spec.md#spatial-extent-object): the first box is the overall extent; additional boxes are optional spatial detail, not a required file count.

## World → Tree density

| Preset | Tree retention and per-tile cap relative to High |
| --- | ---: |
| Low | 0.25× |
| Medium | 0.5× |
| High (default) | 1×, previous behavior |
| Very High | 1.5× |
| Max | 2× |

The setting persists in the normal BeamNG.Earth settings file and applies to both current and incoming tiles without reloading. Fixed ranks keep lower settings as stable subsets of the same tree positions. Existing frame budgets pace additions/removals; removing solid trees requests a collision rebuild. Grass, shrubs, rocks and road furniture retain their own behavior.

Retention is capped at 100% of available positions. The server supplies at most 6,000 vegetation rows per tile; the closest ring already retains all available rows at High. Very High and Max primarily fill out more distant woods and can reduce frame rate. Changing density reuses existing data and does not require new downloads.

## Validation

- 460 Python regression tests passed, including real road-worker output with buildings enabled during a building-parts outage, optional-source cooldown/recovery, cache access, generated-cache safety, terrain landing and road geometry tests.
- 690 Lua assertions passed across trees, settings, roads, collision foci, core and navigation. Covered all five presets, persistence/reset, incoming tiles, stable thinning, unchanged decoration and collision updates.
- Live query of the exact public `2026-10-21.0` building-parts file at the logged teleport (41.73939, -84.99974): index accepted, query complete in 1.17 seconds, cached repeat under 1 ms. About 2.2 MB of range/cache data in an isolated workspace cache, rather than the full 617 MB source file. This cell correctly contains zero building parts; the collection was still read and queried, not suppressed as an empty layer.
- Replayed the logged location with real cached map features, buildings enabled, flat elevation and no imagery. Produced a 115,524-byte road mesh (10 chunks) and a 786,575-byte terrain block with complete surface data. Restored the generated road bundle in 0.032 seconds; the terrain build took 14.89 seconds. These isolate source/geometry loading and are not in-game performance measurements.
- Verified every bundled server module and all 98 mod assets against the working source, plus successful packaged `--server --help` startup.
- The user's existing cache was read only. Game driving and visual/FPS behavior require an in-game check; source-query timing is not a total level-loading benchmark.

Build: `builds/BeamNG.Earth-1.6.0-beta-terrain-trees-fix.exe` in the outer workspace. Close the game and old companion before launching this executable. The launcher installs its bundled mod. Prior executables remain available.

Build and test evidence is under `build/terrain-trees-fix/` (ignored local artifacts).
