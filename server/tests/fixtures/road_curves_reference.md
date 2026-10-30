# Road curve reference fixture

`road_curves_reference.npz` holds synthetic input points, pinned source stations,
and the three outputs of the pre-optimization `roadcurves.rounded` implementation
captured on 2026-10-30. Cases cover dense 2D and 3D curves, straight geometry,
duplicate vertices, and pinned rule boundaries. All inputs are included in the
archive; no downloads are needed. The dense samples used NumPy generator seed
472.

The preserved reference source is
`build/road-streaming/roadcurves_before.py`, SHA-256
`ac13f5f5dcb576e940f6d62f7e7cb93397c42b3f7853c1fe3d87ae21ede4bede`.
Each case has `<name>_points`, `<name>_pins`, and `<name>_out0` through
`<name>_out2`. The outputs are points, old stations and new stations. The streaming
regression test compares against these fixed results to protect geometry and
rule pinning when optimizing the implementation.
