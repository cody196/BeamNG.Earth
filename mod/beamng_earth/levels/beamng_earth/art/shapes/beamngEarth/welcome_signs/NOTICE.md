# State welcome board artwork — revision 2

49 state-specific faces, researched and visually reviewed on 9 November 2026.
Each selected edition and its individual photo or agency reference are recorded
in the adjacent `sources.json` and `docs/STATE_WELCOME_SIGN_REFERENCES.md`.
The editable original drawing commands are in `tools/welcome_art.py`; run
`python tools/build_welcome_signs.py` to regenerate the textures, catalog,
shaped-board profiles and local reference gallery.

These are reference-based game recreations, not official fabrication artwork.
Custom lettering, logos, flowers, animals and illustrated scenery are redrawn
approximations. No pixels from roadside reference photographs are redistributed.
The three public-domain emblem components listed below are incorporated into
the relevant faces. The other geometry and drawing code follows the repository's
MIT license; that license does not assign ownership of state marks or font designs.

Representative editions vary: Montana uses the 2026 design, Ohio the 2023 design,
Oklahoma the 2020 design and Pennsylvania the 2024 design. Connecticut uses its
traditional general welcome rather than assigning a regional 2024 slogan to
every road. Alaska's Klondike gateway is a regional example. Nevada's prospector,
Wyoming's Devils Tower and Tennessee's conventional-road TN-50b are explicitly
older editions. Minnesota uses its Type III metal sign instead of a stone
interstate monument. One face per state is used, not a surveyed crossing-by-
crossing inventory. Governor-name plaques are omitted. Indiana retains the
historical lower panel shown in the user's I-69 photograph.

Board aspect ratios follow the selected references. Michigan (228 × 78 inches),
Texas (18 × 11 feet) and Oklahoma (20 × 10 feet) use documented major-entry
dimensions; other sizes are estimates. Maryland and Wisconsin use shaped
mesh plates. Textures are square maps; the mesh restores the face proportions.

Public-domain emblem components, retrieved 9 November 2026:

- Maryland flag, Open Clip Art / Commons contributors including Colohisto:
  <https://commons.wikimedia.org/wiki/File:Flag_of_Maryland.svg>, CC0 1.0 /
  public domain. SVG and Commons-rendered PNG are retained in
  `tools/sign_art/welcome/components/md.*`.
- New York coat of arms, Fenn-O-maniC / HapHaxion:
  <https://commons.wikimedia.org/wiki/File:Coat_of_arms_of_New_York_State.svg>,
  public domain in the United States, as recorded on the source page.
  SVG and Commons-rendered PNG: `components/ny.*`.
- West Virginia seal, original Joseph H. Diss Debar (1863), Xrmap collection,
  Militaryace / Svgalbertian:
  <https://commons.wikimedia.org/wiki/File:Seal_of_West_Virginia.svg>, public
  domain, including Xrmap's worldwide public-domain dedication.
  SVG and Commons-rendered PNG: `components/wv.*`.

Bundled fonts (complete license texts accompany these textures):

- Roadgeek 2014 Series E Modified: `Roadgeek-LICENSE.txt`.
- DejaVu Sans and Sans Bold: `DejaVu-LICENSE.txt`.
- Yellowtail, copyright 2011 Brian J. Bonislawsky DBA Astigmatic (AOETI),
  Apache 2.0: `Yellowtail-LICENSE.txt`.
  <https://github.com/google/fonts/tree/main/apache/yellowtail>.
- Lora regular/bold and italic variable fonts, copyright 2011 The Lora Project
  Authors, SIL Open Font License 1.1: `Lora-LICENSE.txt`.
  <https://github.com/google/fonts/tree/main/ofl/lora>.

State names, tourism phrases and emblems identify their respective states;
no state-agency affiliation or endorsement is implied.
