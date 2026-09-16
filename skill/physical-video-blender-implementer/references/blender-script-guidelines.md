# Blender Script Guidelines

## Script Shape

Create standalone `.blender.py` scripts. Use the executable and artifact paths
supplied by the task; the runner's default script can be invoked as:

```bash
blender --background --factory-startup --python-exit-code 1 --python scene.blender.py
```

Prefer this structure:

1. constants: paths, frame count, FPS, resolution
2. helpers: materials, visibility, key transforms, camera look-at
3. scene setup: reset, lights, camera, render settings
4. object construction
5. keyframe animation from semantic keyframes and transitions
6. save `.blend` and render animation

## Preview Defaults

Use these default render settings unless the user specifies otherwise:

- 1280x720
- 16:9 aspect ratio
- 24 fps
- 120 frames
- 5 seconds
- deterministic random seed
- simple lighting and one stable camera

The default output is a white/clay physical-prior video. Use grayscale or white
materials only. Do not use semantic colors such as red, blue, purple, yellow, or
orange to encode substances, temperature, fire, reaction products, or mixing
results unless the user explicitly requests a colored diagnostic render.

Use shape, geometry, motion, transparency, roughness, thickness, local
deformation, surface coverage, and shadows to convey the physical process.

## Keyframe Mapping

Map semantic keyframes to approximate frames:

- `K0` -> first frame
- `K1` -> early visible onset
- `K2` -> middle process
- `K3` -> late process when present
- `K4` or final keyframe -> last frame

Use the plan's `time_hint` percentages when present.

## Causal Visibility

For each caused object or state:

- keep it hidden at frame 1
- keep it hidden immediately before its causing transition
- show or grow it only at or after the causing transition

For material processes:

- make new area, color, phase, damage, or deformation originate at the plan's
  stated origin
- preserve visible connection to the source, boundary, impact point, heat
  contact, or force point
- keep coverage, volume, or deformation monotonic when the plan implies
  accumulation, melting, spreading, staining, cracking, or mixing

## Primitive Choice

Use primitives that match the physical meaning:

- droplets, patches, thin films, or irregular meshes for spreading liquids
- softened edges and growing puddles for melting
- boundary-origin color regions for mixing
- local nucleation bubbles for boiling
- contact-origin cracks, dents, or deformation for impact
- attached, vertical, tapered, semi-transparent wisps for flames or ignition
- for white/clay ignition, omit a pre-contact flame marker if it cannot be
  clearly attached to the heat source; show ignition at the contact point
  instead

For color-related prompts in white/clay mode, preserve the physical mixing or
spreading process through visible regions and boundaries, but keep all materials
grayscale. Do not add text labels as a substitute for color.

Avoid:

- long rigid cylinders for soft liquid streams unless the plan explicitly calls
  for a stable jet
- sudden perfect disks for accumulated liquid or mixed regions
- whole-object color fades when the plan requires boundary-origin propagation
- result objects replacing process objects without overlap or continuity
- isolated spheres or ellipsoids as flame, ignition, or burning-tip proxies
- detached pre-contact flame markers that read as separate objects

## Render Settings

For Blender 5.x direct MP4 output, set `media_type` before `file_format`:

```python
scene.render.image_settings.media_type = "VIDEO"
scene.render.image_settings.file_format = "FFMPEG"
scene.render.ffmpeg.format = "MPEG4"
scene.render.ffmpeg.codec = "H264"
```
