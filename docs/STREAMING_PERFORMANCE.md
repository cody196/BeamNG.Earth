# 1.6.0 streaming performance build

Based on the current `improvement-highways` source, including the latest lane, ramp, bridge-lane and rural-intersection corrections. The test executable is a separate build in the workspace's `builds` directory.

The subsequent [loading and cache-access fix](STREAMING_LOADING_FIX.md) corrects the reported pose exception and startup delays. Its executable is `BeamNG.Earth-1.6.0-beta-streaming-fix.exe`; the results below describe the earlier streaming-cache build.

## Changes

- Generated road tiles now have a persistent disk cache. The bundle includes their prepared meshes, decks, tunnels, sidewalks, nearby buildings, collision bounds and roadside placement data when enabled. A hit restores the files into the current game session and rewrites their session paths without repeating mesh generation. Concurrent requests for the same tile share one build.
- Completed graded terrain blocks are also cached: heightmaps, terrain files and material masks. These are saved before imagery-dependent lawn/snow adjustments, so the current photo can still update those materials. A repeat landing can use the graded block directly rather than displaying and then replacing provisional ground.
- Road generation extends **30 seconds ahead, capped at 4 km**, compared with 14 seconds / 2 km. A background planner follows cached source centrelines, one-way directions and shared junction connectors. At an exit it prefers the through road and updates as the car turns. With no usable mapped path, the existing velocity-based corridor remains available. This is a loading prediction, not a GPS route.
- Raw elevation and map-data preparation extends to **6 km**. All road cells on the predicted path are requested before building layers. Terrain-related water, infrastructure and land cover also precede optional scenery. Grading plans and imagery warming use the curved path too.
- The road queue refills on completion, using the latest pose. It no longer leaves workers idle until the next vehicle-position message. The number of road jobs in flight stays bounded.
- Initial level entry and teleports prepare the small landing area's source data concurrently with the quick initial terrain. Nearby terrain and roads take priority over new tree, distant-building and traffic jobs. Far-terrain generation reduces its concurrency while critical work is pending.
- Teleports stop refilling the old road queue. Queued road/terrain jobs check cancellation before starting; running jobs check it between stages. Rapid consecutive teleports also supersede an uncommitted landing. Work still needed by another connection's active anchor is retained.
- A requested terrain block can borrow the idle prefetch terrain process if the request process is occupied. Ordinary speculative prefetch never borrows the request process.
- In the game, nearby pavement imports can use the existing bounded urgent-import mechanism at driving speed. Bridge and tunnel collision retain precedence, and terrain swaps retain their isolated heavy frame.

## Cache validity and limits

Bundles live in `<cache>/generated/v1/` and participate in the existing cache size limit and Clear cache operation. Settings now describe the broader world-data cache. Writes are atomic and entries have checksums; unreadable or incomplete bundles are misses and regenerate normally. No pickle is used.

The cache key includes generator/native version, source releases, airport snapshot, generation options, exact geographic origin, height quantum, zoom and tile/block coordinates. New anchor IDs and game-session paths do not invalidate an otherwise matching entry. A different ENU origin, such as a rebase, requires new geometry to preserve terrain alignment. This is not a universal mesh cache that can reuse a tile under any origin.

Optional source misses are recorded. A cached fallback expires when the missing data arrives, and urban-dependent in-memory road plans are invalidated before regenerating it. Temporary DEM fallback after a failed download is treated conservatively: that process continues streaming and reading existing valid entries, but does not write new generated entries for the rest of the run.

The first visit to a new area still needs source downloads and geometry generation. Nearby building work is still part of a full road-tile build. Game-side mesh imports, collision rebuilds, hardware and network throughput can still limit very fast driving. The longer corridor and scheduling changes provide more preparation time; they cannot guarantee an arbitrary driving speed.

## Verification

Focused checks cover cache rebinding across sessions, identical physics data, changed origins/settings/height quantums, corruption, concurrent requests, cache-cap accounting, source arrival, DEM fallbacks, one-way carriageways, curved highways, unconnected overpasses, exit continuations, queue refill/cancellation, terrain-worker priority, and existing road/grading/surface/bridge/tunnel regressions.

Build-specific results and the local highway replay are recorded under `build/streaming-performance/`. The replay reads existing map fixtures without altering them, uses a flat 300 m test DEM and writes its outputs inside the workspace. Its generation timings are not in-game frame rates or a cold-network benchmark. Real-DEM integration drives need source tiles that are not available in this environment; synthetic fast-driving simulations provide the offline terrain-follow checks. In-game driving remains a necessary final check.

Final validation on 2026-10-23:

- Selected Python regression run: **349 passed**. A subsequent cache-only run passes **15 tests**, adding real road-mesh reuse through both the local and worker build paths. These runs overlap.
- Server and streaming checks: **17 passed**, including synthetic terrain following at 134, 200 and 250 m/s, deliberately delayed heightmaps, and 3/5 second anchor rebases. These simulations do not establish real-world driving performance at those speeds.
- Lua road checks through LuaJIT/Lupa: **85 passed**. The test supplies a deterministic advancing clock to avoid Windows `os.clock` resolution affecting synthetic frames.
- The 51 MB executable passes `--server --help`. Twenty embedded server modules and the changed mod assets match the working source. Source ID: `5f024c42b020cdfc`.
- The initial local highway replay confirmed byte-identical meshes and physics on cache hits. Its older real-world fixture files were no longer present at the final rerun, so those initial timings are retained separately and are not presented as measurements of the final executable. Current cache validation includes generated synthetic road meshes and terrain through the actual builders.

Test build: `../../builds/BeamNG.Earth-1.6.0-beta-streaming-cache.exe`. Close the old companion, run this executable, and reload the level to use its bundled mod changes.
