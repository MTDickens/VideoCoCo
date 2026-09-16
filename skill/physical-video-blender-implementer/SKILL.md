---
name: physical-video-blender-implementer
description: Convert physical-state-planner outputs into standalone Blender Python preview videos. Use when Codex needs to implement semantic keyframes and transitions as Blender scene objects, materials, animations, visibility timing, preview rendering, and preview-sheet extraction while preserving physical causality and avoiding listed anti-patterns.
---

# Physical Video Blender Implementer

## Purpose

Use this skill after a physical state plan exists. Convert the plan's scene,
semantic keyframes, transitions, causal constraints, `must_show`, and
`must_avoid` into a runnable Blender Python script and a low-cost preview.

Do not reinterpret the original prompt or replace the planner's physical
sequence. If the plan is physically incomplete, mark the missing premise rather
than inventing a new story.

Default renders are white/clay physical-prior videos: use grayscale or white
materials only, with no semantic colors, unless the user explicitly requests a
colored diagnostic render.

## Inputs

Accept these fields when available:

- `physical_state_plan`: required; should contain `scene`,
  `semantic_keyframes`, `transitions`, `causal_constraints`, `must_show`, and
  `must_avoid`.
- `case_id`: optional; use for stable file names.
- `output_root`: optional; default to the current repo's `outputs/` tree.
- `preview_profile`: optional; default to 720p, 16:9, 5 seconds, 24 fps.
- `blender_path`: use the executable supplied by the task, otherwise resolve
  `blender` on PATH.
- `ffmpeg_path` and `ffprobe_path`: use supplied executables, otherwise resolve
  `ffmpeg` and `ffprobe` on PATH.

## Workflow

1. Read the plan and preserve its structure:
   - Map each semantic keyframe to an approximate video time.
   - Map each adjacent transition to continuous animation between those times.
   - Treat `must_not_show`, `causal_constraints`, and `must_avoid` as hard
     implementation checks.

2. Design the Blender scene:
   - Create only the objects needed to express the plan.
   - Prefer simple, readable geometry, motion, deformation, opacity, roughness,
     and lighting changes for preview.
   - Render in white/clay style: avoid red, blue, purple, yellow, flame colors,
     or other semantic color coding. Use grayscale contrast, shape, position,
     transparency, and motion to distinguish objects or regions.
   - Choose visual primitives that match the material process; avoid rigid
     symbolic shapes for soft, spreading, melting, flowing, or mixing processes.
   - Keep scene scale, camera, lighting, and object placement stable enough for
     audit frames.

3. Implement causal visibility:
   - Objects or visual states caused by a transition must be hidden before that
     transition begins.
   - New result material must originate from the transition's stated origin
     such as contact boundary, heat source, impact point, liquid source,
     reaction interface, or force application point.
   - Result area, volume, color, damage, phase, or deformation should change
     smoothly unless the plan explicitly calls for a sudden event.

4. Write a standalone Blender Python script:
   - Put the script under `outputs/scripts/<case_id>.blender.py` unless the user
     requests another location.
   - Include deterministic seeds when using randomness.
   - Use direct MP4 output when Blender supports FFmpeg.
   - Save the `.blend` next to the preview when useful for debugging.

5. Render and audit a preview:
   - Render a 720p, 16:9, 5-second, 24-fps preview by default.
   - Extract a preview sheet at semantic-keyframe-aligned times.
   - Check the rendered frames against every keyframe and transition.
   - If preview fails because the implementation violates the plan, repair the
     script. If preview fails because the plan lacks a needed physical state,
     report that the planner should revise the plan.

6. Return concrete artifacts:
   - Script path.
   - Preview video path.
   - Preview sheet path.
   - Keyframe-to-frame mapping.
   - Known limitations or failed checks.

## Output Contract

Use the task's requested output schema. For a standalone implementation task
without a specified schema, this artifact summary is suitable:

```json
{
  "script_path": "",
  "preview_path": "",
  "preview_sheet_path": "",
  "keyframe_frame_map": {},
  "implementation_notes": [],
  "known_limitations": []
}
```

## Required References

- Read `references/blender-script-guidelines.md` before writing Blender code.
- Read `references/preview-rendering.md` before rendering or extracting sheets.
- Use `references/implementation-output-schema.json` for a standalone artifact
  report when the task does not supply its own schema.

## Implementation Rules

- Every visible result must trace back to a keyframe transition.
- Every new object or state must appear no earlier than the transition that
  causes it.
- Every semantic keyframe should be auditable in the preview sheet.
- Do not satisfy a final frame by hiding the missing process.
- Do not add compatibility branches unless the user asks for them.
- Keep the first implementation small; improve after preview evidence.
