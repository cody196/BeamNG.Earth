# Highway road port to 1.6.0

Branch: `improvement-highways`. Source: the road work in the local modified 1.5.5 build. Marking dimensions: the user's `ROAD_IMPROVEMENT_NOTES.md`, reviewed on 2026-10-23. These are the requested appearance profiles, not a claim about official standards in every location.

## Marking dimensions

All values are metres. **Gap means the blank distance between painted dashes**, not the complete repeat.

| Location | Travel dash length | Travel width | Travel gap | Ramp dash length | Ramp width | Ramp gap | Solid width |
|---|---:|---:|---:|---:|---:|---:|---:|
| Other US states / DC | 3.0 | 0.35 | 8.0 | 1.2 | 0.35 | 2.8 | 0.35 |
| Michigan | 4.5 | 0.40 | 11.5 | 1.5 | 0.35 | 6.0 | 0.40 |
| Minnesota | 3.1 | 0.30 | 12.25 | Omitted | Omitted | Omitted | 0.45 |
| Wisconsin | 5.15 | 0.31 | 10.25 | 1.25 | 0.30 | 2.9 | 0.32 |
| California | 4.6 | 0.35 | 10.5 | 2.3 | 0.25 | 4.9 | 0.25 |

Idaho now uses the US fallback. Minnesota keeps solid edges and terminal approach dividers, but omits both ramp guidance dots and dashed dividers between ramp lanes. Stop bars, pedestrian crossings, and arrow dimensions are independent of the solid-line width.

`server/highway_markings.py` selects the profile geographically and cuts paint where a state boundary crosses a road. Dashes are individual white mesh strokes so length and blank gap can vary independently. Their phase survives tile cuts. Double yellow stripes keep a visible gap after widening. Existing markings outside the US keep their upstream dimensions.

The bundled `server/highway_marking_states.geojson` contains the 50 states and DC from the [Census TIGERweb Generalized ACS 2024 state layer (500K)](https://tigerweb.geo.census.gov/arcgis/rest/services/Generalized_ACS2024/State_County/MapServer/7). The exact query is recorded in its `source_url`. This generalized boundary data avoids network lookups while driving; it is not a survey of individual signs or pavement. The file is included in frozen builds and in the compute-sharing fingerprint.

## Port boundaries

- `roads.py`, `roadlanes.py`, and `roadcontext.py`: shared fitted curves, stable source-end neighbourhoods, lane-count transitions, shoulders, ramp tapers, and paint clipping. Long highway interiors use their full source geometry and connector pins without loading every cell along their route. Short roads and ramps retain full context. The context cache is bounded and incomplete reads are retried rather than saved as a different road shape.
- `roadterminals.py`: solid approach dividers and arrows aligned with the local lane geometry. Existing turn-lane tags are supported; otherwise turns are inferred from connected roads. Inferred arrows are not verified real-world lane restrictions.
- `surface.py`, `grading.py`, and `navgraph.py`: the same geometry reaches the current terrain-road photo, detail mask, physics materials, grading, and navigation. Curved pavement returns are painted into the ground. The nonblocking surface path queues missing context cells in the background.
- `roadmesh.py`: preserves fitted samples and shared cross-sections and renders the physical dash/gap dimensions. The current mesh draping and collision/deck pipeline is retained.
- OSM ingestion stays in 1.6's `osmtags.py` / Layercake path. The old regional PBF lane importer was not copied. The numeric `Spec.lanes` interface is preserved; directional layout is stored separately. Where mapped counts are missing, conservative defaults and unique connected-road continuations are used. Layercake currently supplies total lane counts, not directional or turn-lane columns.
- The 1.6 bridge height/clearance solver, structural profiles and tunnel implementation remain in place. Tagged lane widths and paint also apply to bridge decks. Connected auxiliary ramp lanes are partitioned at bridge abutments and get deck extensions at the solved bridge height. Earlier custom bridge elevation changes, Jersey barriers, autosave, terrain appearance, minimap, and signs are outside this road port.
- Rural sidewalk inference now checks evenly spaced land-cover samples beside the road rather than its paved centreline. This also prevents guessed urban parking bays at rural junctions. Explicit OSM `sidewalk=no/none/separate` suppresses generated sidewalks; positive sidewalk tags retain mapped walks. Curved rural corner fills stay flat, and small rural road triangles do not automatically become concrete islands. Existing roundabout islands remain supported.

The current terrain-based road rendering remains the default. `BNGE_ROADS_IN_GROUND=0` still selects mesh pavement. No game installation or cached map data needs to be replaced manually; restart the companion and reload the level to build the new road geometry.

## Validation and drive checklist

Automated coverage includes physical paint dimensions, state selection and border changes, tile-cut dash phase, reversed OSM directions, curve continuity, lane-count tapers, ramp terminals, auxiliary lanes, ground pavement, navigation connectors, grading, OSM data, and current bridge/tunnel regressions. A cached I-69 fixture near 41.848362, -84.997775 also builds road meshes and terrain photos without network reads, using a flat test elevation. This does not replace checking real terrain in game.

Initial port validation on 2026-10-23 (follow-up results below):

- Road-focused Python suite: **164 passed** (including loading regressions).
- Broader integration suite: **281 passed, 1 skipped** (a test requires the standalone LuaJIT executable). These suites overlap and should not be added together.
- Lua road tests through Lupa/LuaJIT: **79 passed, 2 failed**. Both failures (`then the pending rebuild runs` and `dropped tile: mesh deleted, collision reloaded`) reproduce identically against the untouched branch baseline in this Windows harness.
- Frozen EXE: server `--help` smoke test passed. Embedded road modules, state polygons, arrow material, and source fingerprint match the working tree.

- [ ] Drive a curved divided highway across several generated tile boundaries.
- [ ] Check the inside yellow/orange edge, outside white edge, and asymmetric shoulders.
- [ ] Check both entrance and exit tapers, including multi-lane interstate connectors.
- [ ] Check white solid dividers and arrow positions at city-road ramp terminals.
- [ ] Check a 2-to-3-lane transition and a transition back to fewer lanes.
- [ ] Compare Michigan, Minnesota, Wisconsin, California, and a fallback state such as Idaho or Kentucky against the table above.
- [ ] Check a bridge approach and tunnel entrance for regressions to 1.6 geometry.
- [ ] Check I-69 Exit 3 northbound near Coldwater: two through lanes, one lane on each ramp, and clear merging paths.
- [ ] Check an auxiliary ramp lane that crosses a highway bridge: pavement, paint, collision height and parapets across both abutments.
- [ ] Check E Pearl Road / Grass Lake Road: flat rural corner returns, no invented sidewalks or crosswalks; also compare a town intersection and a rural roundabout.
- [ ] Confirm no road-build errors appear in the companion console.

EXE test builds belong in the user's `builds` folder outside the repository. The stock EXE and the separate highway-sign build should remain available for comparison.

## Scenery loading correction

The first road-port build delayed the I-69 anchor at 41.73746, -85.00012: the server log recorded 168.5 seconds before its first graded terrain block. A source highway crossing this area spans about 29 km; fitting it pulled in the entire corridor. Context reads also held a global lock during downloads, while concurrent grading/painting workers could repeat ramp calculations. That delayed the ground needed by the rest of the scenery.

Long roads now request neighbouring topology at their source ends. Their complete source shape and mapped interior connectors still determine the curve. Context downloads run outside the cache lock, requests for the same context/layout share one calculation, and ramp distance searches exclude segments that cannot be nearest. Local terrain paint restricts junction work and rasterization to the block's surroundings without refitting its roads.

Read-only replays from the user's existing map cache, with a flat 300 m test elevation and a 512 m terrain block:

| Location / operation | Previous EXE | Loading fix |
|---|---:|---:|
| I-69 road grading | 17.92 s | 4.23 s |
| I-69 distinct map-cell reads | 41 | 17 |
| I-69 material painting | 1.07 s | 0.30 s |
| I-69 road photo | 0.73 s | 0.12 s |
| California start material painting | 0.26 s | 0.08 s |
| California start road photo | 0.09 s | 0.02 s |

At both logged locations, the output height arrays, material indices and road photos match the previous build exactly in this replay. These timings isolate generation with cached data; they do not predict a cold network download or actual in-game frame times. New tests cover long dense highways, independent contexts during a blocked download, concurrent ramp generation, exact nearest-road projection, and local/full-source corner-paint equivalence.

## Lane lookup, shared ramp bridges and rural junctions

At Exit 3 on I-69, the first Overture source was route relation `r15229259`, not the physical highway way `w156641080`. The previous join missed its mapped two-lane count. The query now retains all OSM geometry sources and their scoped distance ranges. Lane counts are joined by exact way ID; route/name attribution is not used as road geometry. Different known lane ranges survive merging duplicate map-cell records. Supplemental IDs are read only from the Layercake row groups already selected for the cell, without downloading the entire highway corridor. Deferred prefetch reads are retried instead of being saved as permanently untagged roads. The roads cache version changes to 5; existing raw data remains reusable.

Ramp paint and pavement use the same urban/width inputs as the through road. Auxiliary lanes can follow connected mainline bridges instead of stopping at their abutments. Ground painting and grading exclude the elevated auxiliary section. The deck and markings sample the current solved bridge profile, adjacent decks suppress the internal parapet, and ground auxiliary grading follows the connected highway approach before easing back to the departing ramp. An unrelated crossing bridge cannot become the ramp's height source.

Read-only replays using existing cached source data:

- I-69 Exit 3: both carriageways resolve to **two lanes**, all four interchange ramps to **one lane**. Four road-tile meshes build without errors or nonfinite vertices. This replay uses flat test elevation; the real-terrain bridge drive check remains necessary.
- E Pearl Road / Grass Lake Road (41.825781, -85.039045): the same cached land cover previously produced **18 sidewalk/corner pieces and five crosswalks** in the test tile. Sampling beside the roads produces **zero sidewalk pieces and zero crosswalks**, retaining the rural road markings and flat pavement returns.
- Additional automated cases cover relation-first attribution, scoped 2-to-3 lane changes, partial tag availability, shared bridge lane collision/parapet coverage, hillside approach grades, unrelated overpasses, paved rural pixels, dense junction vertices, explicit sidewalk tags, city crossings and rural roundabouts.

The final road-focused suite passes **180 tests**. The broader integration run passes **281 tests with one skip**. A targeted run covering OSM, ramp bridges, grading, approaches and rural junctions passes **61 tests**. Test suites overlap and their totals should not be added together.

Test build: `../builds/BeamNG.Earth-1.6.0-beta-roads-intersections-fix.exe`, source ID `b25df7136ba47976`. Its embedded modules/assets and source fingerprint were checked against the working tree, and its `--server --help` startup check passed. In-game testing has not been performed for this build.
