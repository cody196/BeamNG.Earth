# Researched state welcome artwork

`sources.json` is the editable provenance catalog. `tools/welcome_art.py`
contains the original per-state drawing commands; `tools/build_welcome_signs.py`
rasterizes them using Pillow and bundled fonts. Rebuilding needs no internet.

The `components` directory holds three public-domain emblem SVGs and their
Commons-rendered PNGs. Their sources, authors and terms are documented in
`mod/beamng_earth/levels/beamng_earth/art/shapes/beamngEarth/welcome_signs/NOTICE.md`.
No roadside photographs are build inputs or distributed assets.

The output includes 49 texture maps, material definitions, physical dimensions,
triangulated Maryland/Wisconsin plate contours, a generated Markdown reference
catalog and a local HTML gallery at `build/welcome-signs/index.html`.
