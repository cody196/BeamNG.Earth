# Road streaming optimization, 2026-10-30

Built as `BeamNG.Earth-1.7.2-custom-1.0.1.exe` in the parent workspace's
`builds` folder. The existing game/server session was left running; these changes
take effect when that session is closed and the new launcher is started.

## Session evidence

The current custom 1.0.0 server reported road geotiles still building after
75 seconds. One worker was preparing road curves while placing power lines;
another was waiting for shared grading plans. This places the delay upstream of
the game's mesh import. Recent terrain commits in the game were around 8–13 ms,
while terrain generation and readiness waits were measured in seconds.

The i7-12700KF server and its workers were pinned to logical CPUs 17, 18 and 19,
all efficiency cores. A 30-second sample used about 2.6 cores of CPU across the
server processes. Memory was not exhausted (about 26 GB available). The precise
cause of the reported car slowdown was not captured; terrain/road readiness
pressure is consistent with the logs but does not establish whether a guard,
autodrive or a frame slowdown intervened.

## Changes

- Vectorized curve classification and batched quintic sampling, with cached
  sample weights. Curve resolution, pinning and deviation limits are retained.
- A per-cell decode lock makes simultaneous requests in one worker share a
  fully prepared road table. Downloaded arrays and existing download caches
  are retained. Failures release the lock for retry.
- Power-line placement reuses neighbouring road cells and segment vectors.
- Road ribbons use one native batch, retaining their source-chunk association
  when degenerate chunks are omitted. Bridge construction reuses context
  ribbons, and each face strip calculates normals from its own vertices rather
  than repeatedly concatenating all earlier bridge vertices.
- Highway lookahead increases from 14 to 30 seconds, still capped at 2 km and
  confined to the existing narrow forward corridor. At 75 mph that is about
  1,006 m of lead instead of a lead contained inside the surrounding 640 m disc.
- Windows hybrid CPU allocation now shares core types proportionally while
  keeping physical cores and their hyperthreads together. On this machine the
  server receives CPUs 12–15 and 19 (two P cores and one E core); the game keeps
  six P cores and three E cores. Unknown or uniform topology keeps the previous
  allocation policy, and the existing server-core setting remains supported.
- Completed road geotiles taking at least five seconds log their elapsed/CPU
  time and five slowest stages, to make the next driving session diagnosable.
- Packaging accepts a custom version label without editing the source VERSION.

Road content still uses the existing tile delivery protocol: this update does
not independently stream roads ahead of all scenery within the same tile.

## Measurements

Medians of nine alternating before/after runs after one warmup, using preserved
pre-change sources. Other applications remained running. These measure individual
generation stages, not total tile latency or game FPS.

| Workload | Before | After | Speedup |
|---|---:|---:|---:|
| Cached road cell 14/4340/5856, 27 features | 53.62 ms | 19.02 ms | 2.82× |
| Cached road cell 14/4340/5857, 22 features | 45.43 ms | 14.60 ms | 3.11× |
| Cached road cell 14/4348/5937, 14 features | 14.92 ms | 7.21 ms | 2.07× |
| Synthetic 500 straight road/marking ribbons | 8.79 ms | 3.35 ms | 2.62× |
| Synthetic 24 bridge chunks plus 24 context chunks | 474.44 ms | 378.39 ms | 1.25× |

The comparisons checked curve coordinates, output counts and rule stations,
ribbon geometry, and bridge mesh positions, triangles, UVs and materials.
Benchmark inputs and raw samples: `build/road-streaming/benchmark_results.json`.
Reproducer and preserved sources: `build/road-streaming/benchmark.py`,
`roadcurves_before.py` and `roadmesh_before.py` in the same folder.

## Validation and delivery

- Broad infrastructure/road regression: 730 passed, 8 existing skips, no failures
  (738 tests, 181.8 seconds). Log: `build/road-streaming/regression.log`.
- Additional streaming, CPU allocation, power-line and worker tests:
  33 passed and one Linux-only test skipped. Worker output is compared byte for
  byte. Two Windows fixture-cleanup errors were resolved by closing only those
  fixtures' revisit sidecar handles before deleting their temporary folders.
- Combined distinct tests: **763 passed, 9 skipped**. The broad suite's existing
  missing offline inputs and platform/baseline exclusions are documented in
  `INFRASTRUCTURE_MIGRATION_1.7.2.md` and its verification runner.
- The packaged archive's VERSION, CODE_ID, changed modules, Windows HTTPS
  dependency and native library were inspected. The native library matches the
  checked source binary; the source fingerprint is `c42be7f1f465aacf`.
- Executable SHA-256:
  `336c1f67c22c40836333118a37cdcdea341c188e90a851efc1d62e567f05a2d1`.

There has not yet been a driving-session measurement with the new executable.
The new source fingerprint causes derived geometry caches to rebuild on first
use; downloaded map/elevation data remains reusable. Network misses and shared
grading work can still cause delays, so the stage speedups above are not a claim
that all 75-second stalls are eliminated.
