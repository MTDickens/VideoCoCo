# Preview Rendering

## Executables and Paths

Use the executable paths and artifact paths supplied by the task, otherwise use
commands from PATH and the implementer's default output tree. Examples below use
the VideoCoCo runner's filenames in the current workspace.

## Render Command

From the repo root or selected workspace:

```bash
blender --background --factory-startup --python-exit-code 1 --python scene.blender.py
```

Successful Blender logs should show frame appends through the final frame.

## Validate MP4

```bash
ffprobe -v error -select_streams v:0 -show_entries stream=width,height,r_frame_rate,nb_frames:format=duration -of json proxy.mp4
```

Compare against the requested profile. With the standalone default profile, expect:

- width=1280
- height=720
- r_frame_rate=24/1
- duration=5.000000
- nb_frames=120

## Extract Preview Sheet

Choose frames aligned to the actual semantic-keyframe mapping. FFmpeg's `n` is
zero-based: Blender frame 1 corresponds to `n=0`. For an example mapping of
Blender frames 1, 30, 60, 90 and 120:

```bash
ffmpeg -y -v error -i proxy.mp4 -vf "select='eq(n,0)+eq(n,29)+eq(n,59)+eq(n,89)+eq(n,119)',scale=240:-1,tile=5x1" -frames:v 1 preview.png
```

Use one tile per semantic keyframe and replace the example indices with the
audited mapping, including the first and last frames.

## Preview Audit

Before final response, inspect the sheet and any suspicious key frames:

- each semantic keyframe is visible at its mapped frame
- caused objects do not appear early
- transition origin, direction, and material continuity are visible
- final state is reached without hiding the middle process
- no `must_avoid` item is obvious in the preview
- output uses white/clay grayscale materials with no semantic colors unless a
  colored diagnostic render was explicitly requested

If the sheet is ambiguous, extract individual frames around the failing
transition.
