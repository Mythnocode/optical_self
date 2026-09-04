# Optical Bench Unity Prototype

A self-contained Unity prototype to test whether a GPU-rendered optical bench is responsive enough to replace the current Qt painter-based 3D preview. It does not call Python or replace `optical_core`; all routing is intentionally visual-only.

## Requirements

- Unity `2022.3 LTS` or newer.
- Built-in renderer. No external packages, models, or assets are required.

## Open

1. In Unity Hub, use **Add** and select this `OpticalBenchPrototype` folder.
2. Open the project and press Play. The runtime bootstrap creates the scene automatically, so there is no scene asset to open.

## Controls

- Right mouse drag: orbit camera
- Middle mouse drag: pan camera
- Mouse wheel: zoom
- Left mouse drag: select and move component
- `R`: toggle component rotation mode
- `B`: cycle beam load `1x`, `25x`, `100x`

The stress mode scales visual beam ribbons only. It does not claim to reproduce physical ray-tracing cost.

## Expected Result

Camera movement should remain smooth because beam meshes are rebuilt only when a component changes or the load mode changes. Orbit, pan, and zoom only update the camera transform.

## Next Integration Step

Once the interaction quality is acceptable, add a localhost WebSocket bridge. Python should publish immutable node/beam snapshots and Unity should return node transform events. Keep the physics engine in Python; Unity remains the GPU renderer and interaction surface.
