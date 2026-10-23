# Highway improvements

Ports the road improvements from the modified 1.5.5 build into 1.6.0, using the current road renderer and OSM data pipeline.

- Smoother road curves and continuous joins between generated tiles.
- Improved lane counts, highway widths, and inside/outside shoulders using available OSM data.
- Fixed OSM lane lookup when a route relation appears before the physical road way, including lane changes within a combined map segment.
- Smooth transitions when lane counts change, including multi-lane interchange ramps.
- Longer entrance/exit tapers, continuous white merge guidance, and delayed ramp edge markings to avoid crossing the through lanes.
- Solid white approach dividers and lane-centred turn arrows at ramp/city-road junctions.
- Yellow/orange inside edge markings on US divided highways.
- Revised travel, ramp, and solid marking dimensions for Michigan, Minnesota, Wisconsin, and California, with a fallback for every other US state. Minnesota omits ramp dashes.
- Actual painted dash lengths and blank gaps, with consistent spacing across tile cuts. Bridge paint uses the same regional dimensions.
- Terrain pavement, road materials, markings, and navigation follow the same fitted road geometry.
- Ramp lanes and merge markings can continue across a shared highway bridge at its existing deck height. Ground approaches follow the highway grade, with no barrier between adjacent lanes.
- Rural intersections use roadside land cover and mapped sidewalk tags: no invented city sidewalks, crosswalks, or concrete islands across fields. Town sidewalks and roundabout islands remain supported.
- Faster scenery loading: long highways no longer require downloading their entire corridor, concurrent ramp requests share one calculation, and terrain painting processes nearby junctions only.

The newer bridge height/clearance solver, tunnel implementation, Layercake OSM source, and terrain-based road renderer are retained. Bridge lane widths and connected ramp deck extensions use the shared road layout. This branch does not include the separate highway-sign and mile-marker feature.

Validation includes automated curve, ramp, marking, terrain, grading, navigation, OSM, bridge-approach, and tunnel checks, plus offline road-mesh builds from cached I-69 data. In-game visual testing is still needed.

Offline replays confirm two highway lanes and one lane per ramp at I-69 Exit 3, and remove the generated sidewalks/crosswalks at E Pearl Road and Grass Lake Road. The port notes record automated test results and the remaining in-game drive checks.

See [the dimension table and port notes](docs/HIGHWAY_IMPROVEMENTS.md) for details.
