# State welcome signs

State-entry boards now stream with the existing **Highway Signs** scenery.
There are 49 state faces (contiguous 48 plus Alaska), with an Indiana design
based on the supplied I-69 Michigan/Indiana reference. Enable Highway Signs
in the mod settings; the feature is on with the existing default.

The state-welcome-v3 build fixes vertically inverted faces. Both rectangular
boards and Maryland/Wisconsin cutouts now pass V-up texture coordinates to the
shape writer, which converts them once to BeamNG's V-down convention. The
regression check exports and reads the actual `.cdae` faces for all 49 states.
Textures and artwork remain unchanged.

The state-welcome-v4 build also prevents the signs disappearing after a stock
app update. The launcher log showed v3 downloading and starting the upstream
1.9.1-beta executable, which contains neither the welcome generator nor its
artwork. V4 embeds a `BUILD_VARIANT` marker: it ignores staged stock updates,
does not offer incompatible upstream downloads, and explains that custom
updates must be installed manually. The marker is inside the executable, so
renaming it does not remove this protection. Stock releases retain their normal
updater; previously downloaded executables and update notes are left intact.

The **1.9.1-beta-combined-signs** build carries these fixes forward onto 1.9.1,
alongside the Interstate/US Highway shields and sampled exit-sign heights.
Close the game and run its executable to install the matching mod. For BeamMP,
install its matching server package and update every player's executable.
The generator runs in each player's local world server, so replacing only the
server's client-mod ZIP is insufficient.
Restart the app and BeamNG/BeamMP after updating so visible shapes are regenerated.

Boards are generated where a motorway, trunk, primary, secondary or tertiary
road enters a state. A divided highway receives a sign on each entering
carriageway, facing its own traffic. Two-way roads can receive opposite states'
boards on their respective right shoulders. Ramps and service roads are excluded.
International road entries also qualify, including Alaska from Canada.

The server intersects complete source road geometry with bundled Census
boundaries. It follows connected road segments and looks for clear ground at
least 25 metres into the receiving state. At bridge/tunnel crossings it searches
up to 1.6 km along the receiving road for a usable ground shoulder. If none is
available, that approach is skipped. It does not plant poles on a bridge or in
a tunnel. Placement checks pavement clearance, ground slope, entering state
and half-open tile ownership. Meshes have no collision and do not affect road
readiness, traffic rules or AI.

Limitations:

- Locations are inferred from generalized Census boundaries and mapped roads;
  they are not surveyed sign locations. Very long bridges, ambiguous road forks,
  minor roads and incomplete map data may have no board.
- The faces are **reference-based state-specific recreations**. The revised set
  corrects layouts, colors, lettering styles, symbols and proportions using
  individual roadside photos and official agency drawings. Custom typography
  and illustrated scenes remain approximations. See the
  [49-state reference catalog](STATE_WELCOME_SIGN_REFERENCES.md) for the selected
  edition and sources. One representative face is used per state, including
  regional/historic designs; this is not an inventory of today's exact signs
  at every crossing. Indiana retains its historical lower panel.
- Maryland has an arched plate and Wisconsin a separate projecting state plate.
  Their meshes follow the silhouettes and supports stop behind the plate edge.
- Board/support dimensions are estimated except documented Michigan, Texas and
  Oklahoma major-entry dimensions. Building footprints and surveyed sign offsets are not yet
  part of this placement model.
- Offline tests validate geometry, streaming and packaging. An in-game visual
  drive is still needed to validate appearance in BeamNG lighting and scenery.

Implementation:

- `server/welcomesigns.py`: boundary index, directed crossing/placement, mesh.
- `server/data/welcome_states.geojson.gz`: public-domain Census boundaries.
- `server/data/welcome_signs.json`: state catalog and face dimensions.
- `tools/build_welcome_signs.py`: reproducible offline artwork/catalog builder.
- `tools/welcome_art.py`: state-specific vector drawing commands, Pillow and bundled fonts.
- `tools/sign_art/welcome/sources.json`: individual references, editions and fidelity notes.
- `mod/.../welcome_signs/`: textures, materials and attribution.
- `server/signstream.py` and client `roads.lua`: optional `welcomes` mesh lifecycle.

Rebuild the textures with `python tools/build_welcome_signs.py`.
The contact sheet is written to `build/welcome-signs-preview.jpg`.
The larger undistorted faces and a reference-linked HTML gallery are written
to `build/welcome-signs/index.html`. No reference photographs are packaged.
Both the source package and frozen executable collect the new server data and
client assets through their existing directory packaging rules. Existing
executables do not change until rebuilt.

Build custom distributions with `--build-variant combined-signs-1.9.1` on both
`tools/build_app.py` and `tools/package.py`. This embeds the update protection
in the executable and source package without changing the base protocol version.
Future official releases must be merged into the custom source and rebuilt to
retain these features; the stock update channel does not contain them.

Focused checks:

```
python tools/run_tests.py test_welcome_signs test_highway_signs test_sign_packaging test_exit_sign_sizing test_portrait_exit_signs
python tools/run_lua_tests.py test_highway_signs test_roads test_dirsigns
```
