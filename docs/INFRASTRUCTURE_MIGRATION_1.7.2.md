# Infrastructure migration onto 1.7.2-beta

Base: `8375d517`. Sources: the customized 1.7.1 tree (`f95bb53a`, including
`564f918e`, `e33cf4f3` and lane correction `74ebb346`) and the customized 1.7.0
curve and route-shield implementations. Dimensions come from the confirmed
[ROAD_IMPROVEMENT_NOTES.md](../ROAD_IMPROVEMENT_NOTES.md), copied unchanged.

## Signs and mile markers

- Restored the Michigan/Kentucky mile-reference inventory, calibrated Kentucky
  and southern Indiana fractional stations, deduplication, and blue fractional
  panels. Fractional panels use existing concrete Jersey medians. Where there is
  no suitable concrete wall, whole-mile shoulder markers remain and fractional
  panels are omitted. The beta's barrier generation and collision are unchanged.
- Restored compact exit-panel sizing, guide lettering, route labels, support
  counts, combined destination gantries, duplicate suppression, conflict spacing
  and ownership after repositioning. The beta's pavement/deck clearance checks
  are retained; shifted panels also keep their height above the road.
- Restored standalone Interstate/US shields and direction plaques. The weekly
  shard builder now emits shields over connected route chains, including
  relation-only US highways; spacing does not restart at tile boundaries.
- Existing `*.signs.v3.sqlite` shield inventories are read without modification.
  A local probe found 8,819 shield records across the five existing indexes.
  Newly generated weekly records take precedence over matching cached IDs.
- Bundled mile markers work when the optional weekly sign source is unavailable.
  New inventory assets are included by the executable packaging script.

Shield coverage in a place requires either a previous cached shield inventory or
shards rebuilt with the updated `tools/build_sign_tags.py`. To use a local extract,
build it with `python tools/build_sign_tags.py extract.osm.pbf out/signs` and set
`BNE_SIGNS_DIR` to that output directory before starting the server. No remote
dataset was published or regional extract downloaded by this migration.

## Marking dimensions

US profiles, in metres. Columns show paint length / gap length / paint width.
State selection is shared by ground roads, bridges and tunnels. Native dash
cutting, lane restrictions and direction colours remain in place. Explicit
non-US country styles retain their beta dimensions.

| Profile | Travel dashes | Ramp dashes | Solid width |
|---|---|---|---|
| Default | 3 / 8 / 0.35 | 1.2 / 2.8 / 0.35 | 0.35 |
| Michigan | 4.5 / 11.5 / 0.4 | 1.5 / 6 / 0.35 | 0.4 |
| Minnesota | 3.1 / 12.25 / 0.3 | None | 0.45 |
| Wisconsin | 5.15 / 10.25 / 0.31 | 1.25 / 2.9 / 0.3 | 0.32 |
| California | 4.6 / 10.5 / 0.35 | 2.3 / 4.9 / 0.25 | 0.25 |
| Kentucky | 3.5 / 8.2 / 0.3 | None | 0.3 |

Missing ramp dashes are omitted, not converted into solid separators. Solid
lane restrictions use the solid-width column independently of dashed widths.
Tecna's corner geometry is retained; its paint uses the applicable state width.

## Lanes

- Untagged motorway/trunk carriageways default to two lanes, including urban
  highways. Untagged ramps default to one lane when one-way, two when two-way.
- Valid OSM counts override defaults for widths, lane paint, bridge/tunnel specs
  and navigation. Fractional/list/conditional counts are rejected.
- Highway matching uses the source way first, then an unambiguous nearby current
  way with matching geometry, class, ramp status and traffic direction. A nearby
  road's matching name cannot supply a highway's lane count.
- Directional/shared-turn-lane counts and agreeing connected highway approaches
  supply additional evidence. Enrichment invalidates derived geometry/sign specs.
- The earlier I-65 Exit 76 ramp correction remains restricted to its source way
  and geographic bounds. Raw OSM tags are preserved.
- The decoded road-data version advances from 7 to 8 so old lane enrichment is
  refreshed. Derived caches also follow the normal source-code fingerprint.

## Curves and retained beta behavior

The 1.7.0 bounded quintic curves are prepared once when road cells are decoded.
They use approximately 1 m curve samples and a maximum 1.5 m deviation. Original
endpoints, connectors and linear-rule boundaries remain pinned; rule fractions
are remapped to the new arc lengths. Downloaded source arrays remain unchanged.
Prepared geometry is shared by road rendering, grading, navigation and signs.
Road simplification uses 5 mm tolerance and a maximum 4 m node spacing; ribbon
construction retains fine curve knots.

The beta's 4 m terrain-profile cadence, 100 m banking stencil/runoff/fade and
connected-road context remain unchanged. Importing the old unconditional 2 m
banked-profile cadence increased a grade transition at the recorded Otto Road
ramp junction from below its 0.035 limit to 0.03838. Retaining the beta cadence
with the restored curves passes that original limit. No old corner generator,
bridge solver or median-barrier generator replaces the beta implementations.

## Verification

Focused tests cover measured rendered dash lengths/gaps/widths for every profile,
OSM lane evidence, adjacent-tile sign ownership, shield indexing/shard decoding/
mesh generation, real median mounting, and smooth curves through ribbon creation.
The real Otto Road bridge replay passes all four checks with its original height,
grade, clearance and junction-continuity limits; see its
[fixture provenance](../server/tests/fixtures/otto_wyoming.md).

Final broad run: **730 passed, 8 skipped, no failures** (738 tests, 202 seconds).
`git diff --check` also passes. The regression log is
`build/migration-172/verification-complete.log`; the local runner is
`build/migration-172/verify.py`. One skip is the existing missing-LuaJIT check.
Seven checks are explicitly excluded from that run:

- Atlas regeneration differs with the installed font renderer.
- Two revisit tests leave file handles open, blocking Windows temporary-directory cleanup.
- One road-height test hardcodes an unwritable `/tmp` path on Windows.
- An existing protocol test's Lua regex no longer matches its source.
- Two Baltimore geographic replays need Overture data absent from the local cache.

The five failures in the first four categories were reproduced on untouched 1.7.2-beta; the latter two
are missing offline inputs. Their production code and tests were not changed to
hide these failures. The migrated source has not been packaged into a new
executable or visually tested inside BeamNG during this migration.
