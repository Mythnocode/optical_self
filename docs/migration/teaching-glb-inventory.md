# Teaching GLB inventory

Captured: 2026-09-28
Source: `D:\AAAWorkspace\optical_self\frontend_pyside\features\teaching_v2\assets`
Assets: 25

AABBs include the default glTF scene's node transforms and primitive POSITION accessor bounds. Values use the source mesh coordinate frame; verify units and axis anchors before assigning a renderer manifest entry.

| Asset | Size | Meshes | Textures | AABB min | AABB max | Dimensions |
|---|---:|---:|---:|---|---|---|
| `aperture.glb` | 16.8 KiB | 1 | 0 | (-0.25, -2.5, -2.5) | (0.25, 2.5, 2.5) | (0.5, 5, 5) |
| `beam_expander.glb` | 84.3 KiB | 1 | 0 | (-22.5, -12.5, -12.5) | (22.5, 12.5, 12.5) | (45, 25, 25) |
| `beam_sampler.glb` | 14.7 KiB | 1 | 0 | (-1, -6.35, -6.35) | (0, 6.35, 6.35) | (1, 12.7, 12.7) |
| `breadboard.glb` | 81.4 KiB | 1 | 1 (image/png) | (-225, -150, -12.7) | (225, 150, 0) | (450, 300, 12.7) |
| `ccd.glb` | 52.9 KiB | 1 | 0 | (0, -15, -15) | (21.8, 15, 15) | (21.8, 30, 30) |
| `cylindrical_lens.glb` | 30.4 KiB | 1 | 0 | (-1, -6.35, -6.35) | (1, 6.35, 6.35) | (2, 12.7, 12.7) |
| `fiber_stage.glb` | 18.2 KiB | 1 | 0 | (-18, -22, -40) | (18, 22, 0) | (36, 44, 40) |
| `fiber.glb` | 306.8 KiB | 1 | 0 | (0, -5.5, -5.5) | (18, 5.5, 5.5) | (18, 11, 11) |
| `grating.glb` | 36.6 KiB | 1 | 0 | (-6, -6.35, -6.35) | (0, 6.35, 6.35) | (6, 12.7, 12.7) |
| `isolator.glb` | 109.9 KiB | 1 | 0 | (-18, -12.5, -12.5) | (18, 12.5, 12.5) | (36, 25, 25) |
| `laser.glb` | 307.8 KiB | 1 | 0 | (-40, -5.5, -5.5) | (0, 5.5, 5.5) | (40, 11, 11) |
| `lens.glb` | 11.2 KiB | 1 | 0 | (-1, -6.35, -6.35) | (1, 6.35, 6.35) | (2, 12.7, 12.7) |
| `mirror.glb` | 14.7 KiB | 1 | 0 | (-6, -6.35, -6.35) | (0, 6.35, 6.35) | (6, 12.7, 12.7) |
| `mount_clamp.glb` | 7.9 KiB | 1 | 0 | (-28, -9, -13) | (-12, 9, -5.5) | (16, 18, 7.5) |
| `mount_km.glb` | 9.6 KiB | 1 | 0 | (-14, -13, -13) | (-6, 13, 13) | (8, 26, 26) |
| `mount_plate.glb` | 1.9 KiB | 1 | 0 | (0, -17, -21) | (22, 17, -15) | (22, 34, 6) |
| `mount_post_base.glb` | 23.1 KiB | 1 | 0 | (-12.5, -12.5, 0) | (12.5, 12.5, 10) | (25, 25, 10) |
| `mount_ring.glb` | 45.8 KiB | 1 | 0 | (-5, -10, -10) | (5, 10, 10) | (10, 20, 20) |
| `oscilloscope.glb` | 25.2 KiB | 1 | 0 | (-60, -40, 0) | (60, 40, 50) | (120, 80, 50) |
| `pbs.glb` | 16.8 KiB | 1 | 0 | (-6.35, -6.35, -6.35) | (6.35, 6.35, 6.35) | (12.7, 12.7, 12.7) |
| `post_stem.glb` | 6.2 KiB | 1 | 0 | (-6.35, -6.35, -1) | (6.35, 6.35, 0) | (12.7, 12.7, 1) |
| `power_meter.glb` | 60.8 KiB | 1 | 0 | (0, -15, -15) | (22, 15, 15) | (22, 30, 30) |
| `splitter.glb` | 14.7 KiB | 1 | 0 | (-3, -6.35, -6.35) | (0, 6.35, 6.35) | (3, 12.7, 12.7) |
| `wavefront_sensor.glb` | 16.0 KiB | 1 | 0 | (0, -20, -20) | (32, 20, 20) | (32, 40, 40) |
| `waveplate.glb` | 14.7 KiB | 1 | 0 | (-3, -6.35, -6.35) | (3, 6.35, 6.35) | (6, 12.7, 12.7) |

The first Three.js slice copies only breadboard, laser, lens, and fiber. The remaining GLBs stay in the legacy asset directory until their kind, mount anchor, and optical axis are validated in the next asset-migration phase.
