# 1.6.0 loading and cache-access fix — 2026-10-23

Build: `../../builds/BeamNG.Earth-1.6.0-beta-streaming-fix.exe`

This follows the streaming-cache build and retains its generated-road/terrain caches, road-aware lookahead and the current highway/intersection corrections.

## Reported failures and fixes

- **Repeated `bad 'pose' message: ValueError: The truth value of an array ... is ambiguous`.** The road predictor supplies a NumPy array to imagery warming. `Imagery.warm` tested that entire array as a Boolean, interrupting the position update before road and tree scheduling. It now checks the number of points. Road/scenery scheduling also precedes imagery warming. A regression test reproduces the original exception through the actual connection pose handler, server imagery-warming method and lazy-imagery implementation, and verifies subsequent road/tree updates.
- **WorldCover `.npz` cache access warnings.** Map-data reads now retry temporary sharing/access failures for a bounded interval before giving up. A sustained permission error propagates as an access failure instead of treating a valid file as corrupt and rebuilding it. Cache misses are coordinated across worker processes, with the cache checked again after acquiring the lock. Windows uses an OS-owned named mutex; a stopped/crashed worker cannot leave a stale lock. Generated geometry cache reads and replacement writes also retry transient contention. Actual file ACL changes are not part of this fix.
- **Slow provisional ground on level entry or teleport.** The provisional block previously ran full road/ramp material fitting whenever its raw road data was cached. It now prepares elevation and cached land-cover materials; the graded refresh adds the complete road and lot materials. A valid generated terrain cache hit still loads the fully graded block directly.
- **Repeated road calculations.** Road and bridge callers share cached width/lane calculations. Cross-section calculations for ordinary road samples are batched; junction handling retains its existing rules. Road neighbourhoods keep more entries within the existing byte limit.
- **Unrelated land-cover reads/downloads.** Sparse points from long roads previously queried every cell inside their bounding rectangle before checking whether any requested point belonged to the cell. The test now precedes cache access, avoiding irrelevant reads and background downloads.
- **Worker terrain priority.** Terrain built in a worker now uses the same urgent elevation lane as terrain built in the main server. That worker pauses new speculative road-planning jobs during an active terrain build, with the gate released even on failure.

The Windows mutex follows [CreateMutexW](https://learn.microsoft.com/en-us/windows/win32/api/synchapi/nf-synchapi-createmutexw) and [WaitForSingleObject](https://learn.microsoft.com/en-us/windows/win32/api/synchapi/nf-synchapi-waitforsingleobject), including abandoned-owner handling. Non-Windows builds use bounded advisory lock files outside the evictable cache directories.

## Local comparison

The comparison replays cached map data at the reported destination, **41.738444807716, -84.99995587094**, using the actual road/terrain builders. The old source snapshot and new code run in separate fresh processes, without profiler overhead. The source cache is read-only; generated outputs stay under `build/streaming-fix/`.

It uses a **flat 300 m test DEM**, imagery disabled, buildings disabled and building-derived road widths disabled. It measures generation and cache reuse, not cold downloads, game imports or driving frame rates.

| Operation | Before | After |
| --- | ---: | ---: |
| Provisional initial ground | 13.262 s | 0.163 s |
| Full graded terrain block | 26.862 s | 19.100 s |
| First road tile | 43.217 s | 22.455 s |
| Same-origin terrain cache hit, new anchor ID | 0.044 s | 0.043 s |
| Same-origin road cache hit, new anchor ID | 0.032 s | 0.033 s |

Full terrain generation read 83 source files instead of 297; the road tile read 87 instead of 301. The completed terrain file, heightmap, material masks and road mesh matched the baseline byte for byte. Provisional materials intentionally differ until the graded refresh arrives.

The exact-origin requirement of the generated geometry cache remains: a different geographic origin or changed generation code/settings requires a fresh generated entry. Existing downloaded map/imagery/elevation data remains reusable. First visits still depend on data availability and network speed; these measurements do not guarantee arbitrary driving speeds.

## Validation and use

- 375 selected regression tests passed, covering road/ramp/bridge geometry, terrain materials, generated caching, map data, imagery, priority and cancellation.
- Six focused loading regressions passed after the final provisional-ground change. These overlap the broader run.
- 19 server/streaming tests passed, including level/teleport behaviour, prefetch prediction, and synthetic terrain following at 134, 200 and 250 m/s with delayed heightmaps and 3/5-second anchor rebases. These are simulations, not measured BeamNG driving performance.
- Real spawned Windows worker tests verify one cache build for concurrent requests, timeout handling, unrelated-key progress, and recovery after a worker is terminated.
- The packaged executable passes `--server --help`. Its 23 checked server modules and four checked mod/data assets match the source.
- Source ID: `1d219d47872c99e8`. Executable size: 51,063,675 bytes. SHA-256: `71da8b48241990ce05cb44335c490490734e3b4a2a282278fa0bea61d9cc939d`.

The logs, comparison hashes and packaging verification are in `build/streaming-fix/`. In-game validation has not been performed.

Close the old companion and game, run the new executable, then load BeamNG.Earth. Keep the existing download cache; clearing it would require downloading the source data again.
