Offline geographic replay for I-80 over Otto Road, Wyoming

Location: 41.10022, -105.06194; primary map cell 14/3410/6136.
Captured 2026-10-26 from the local server's existing download cache, with
generated road/revisit and grading-plan caches bypassed.

`otto_wyoming.npz` contains 13 real road cells from Overture release
2026-09-23.1 (mapdata v2, roads.6), including the joined interchange ramps.
The two affected motorway feature IDs are
`a4ce4242-6c0c-4f09-af3f-4ef16198fae5` and
`c055323a-f109-486c-9a9d-ad07f216b366`. Span lengths are 34.549 m and
31.391 m. Road geometry attribution: Overture Maps Foundation; underlying
OpenStreetMap contributors (see the project's CREDITS.md).

The fixture also contains point samples returned by the project's Dem.sample
pipeline at zoom 16, using its cached geographic elevation tiles. These are
input elevations, before road grading, not expected/solved bridge profiles.
Sample keys are integer nanodegrees and zoom relative to sample_origin;
this keeps submillimetre coordinate precision without large tile images.
73 samples along Otto Road and the ramps were added on 2026-10-27 from the same pipeline (the
underpass depth now read from the ground along the road; the captured ones matched it within 0.03 mm).
The replay fails on a sample it has not captured instead of interpolating
invented terrain or fetching data. Source pipeline: Mapterhorn terrain,
with the project's normal fallback/filtering behavior (server/dem.py).

lower_xy and footprint_xy cover Otto Road at roughly 1 m spacing, including
both carriageway edges. approach*.xy/z preserve the original I-80 physical
approach samples, which the correction must leave unchanged. All grading,
bridge solving, chunk generation, surfaces, barriers, and collision geometry
are recalculated by test_otto_bridge.py.

Before correction, usable crossing-corridor headroom was 4.35 / 4.73 m;
the capped clearance floor produced 6% bridge grades and grade reversals
of 10.25 / 6.29 percentage points. This fixture exercises the short-span
and connected-underpass conditions absent from the synthetic long-span tests.

For the 1.7.2-beta customization migration (2026-10-30), 487,295 additional
captured input samples were restored from the existing 1.7.0-modified copy's
fixture. Samples shared by both archives agree exactly. Every original cell,
tag, input sample, approach reference, lower-road point and clearance footprint
is retained unchanged. Only sample_keys/sample_z were extended.

The replay prepares the same bounded road curves as MapData before planning.
Its nearest-recorded-sample fallback and distance limits remain unchanged;
spatial blocks accelerate the exact nearest lookup over the larger archive.
The endpoint comparison retains the custom 1.7.0 tolerance of 0.02 mm, allowing
micrometre arc-length interpolation differences. The original approach-height,
clearance, grade and junction-continuity limits are retained.
