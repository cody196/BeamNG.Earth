# Welcome-sign state boundaries

`welcome_states.geojson.gz` contains the US Census Bureau TIGERweb Generalized
ACS 2024 **States 500K** layer for the 50 states and DC. Source data are public
domain, a work of the US government. The full query and source attribution are
retained inside the GeoJSON. This is the unsimplified source of the repository's
`sign_states.geojson`, retrieved 2026-11-09; no further geometry simplification
is applied here. Gzip is deterministic (mtime 0).

The underlying 1:500,000 layer is itself generalized. These are estimated border
crossings, not surveyed welcome-sign positions. This file is kept separate from
the much smaller 300-metre-simplified style lookup used by other signs.

The artwork/placement catalog `welcome_signs.json` contains 49 states: the
contiguous 48 plus Alaska. Hawaii and DC remain in the boundary lookup so their
territories are recognized, but receive no state welcome boards.

Re-fetch: request `source_url` from the GeoJSON (the same query is also recorded
in `server/sign_states.geojson`), verify 51 features and STUSAB/NAME properties,
preserve the source/license metadata, serialize compact JSON and gzip with
`mtime=0`. No runtime download is needed for these boundaries.
