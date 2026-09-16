---
name: blender-mcp-video
description: Render and debug scripted Blender videos through the CLI, including direct MP4 output and Blender 5.x media_type settings. Also supports previewing scenes through Blender MCP when those tools are available in the task.
---

# Blender MCP Video

## Core Rule

Separate the two Blender access paths:

- **Blender MCP**: controls an already-running GUI Blender instance. Use it for interactive previews when the task supplies a connection and tools.
- **Blender CLI**: starts Blender from an executable path. Use it for reliable batch rendering and final videos.

## Executables and Outputs

Use the Blender, FFmpeg and ffprobe paths supplied by the task. Otherwise resolve
their command names on PATH. Run from the current workspace and use its requested
script/output paths and render profile. The commands below use the VideoCoCo
runner's filenames as examples; substitute the supplied executable paths.

Blender runs scene scripts with its bundled Python. Use `uv run` for separate
Python utilities outside Blender.

## Direct MP4 In Blender 5.x

For direct Blender MP4 output, set `media_type` before `file_format`.
This order is required in Blender 5.x because the dynamic `file_format` enum
only exposes movie formats after the media type is switched to video.

```python
scene = bpy.context.scene
scene.render.filepath = str(output_mp4_path)
scene.render.image_settings.media_type = "VIDEO"
scene.render.image_settings.file_format = "FFMPEG"
scene.render.ffmpeg.format = "MPEG4"
scene.render.ffmpeg.codec = "H264"
scene.render.ffmpeg.constant_rate_factor = "MEDIUM"
scene.render.ffmpeg.ffmpeg_preset = "GOOD"
```

If Blender raises an error like:

```text
enum "FFMPEG" not found in ('AVIF', 'JPEG', 'OPEN_EXR', 'PNG', ...)
```

first check whether `media_type` was left as `"IMAGE"`. Do not immediately
switch to external ffmpeg or PNG frame sequences.

## MCP Workflow

When MCP tools are available:

1. Call `get_scene_info` once to confirm the GUI Blender connection.
2. Use `execute_blender_code` for small chunks; avoid sending large unverified scripts all at once.
3. For generated scripts, first run only setup code or a still-frame render.
4. Use `get_viewport_screenshot` only as a quick view; if it returns black, render a still camera frame to disk and inspect that image.

Use MCP for preview/debug. Prefer CLI for final video unless the user specifically wants to render inside the live GUI session.

## CLI Workflow

Render the generated standalone script:

```bash
blender --background --factory-startup --python-exit-code 1 --python scene.blender.py
```

Expected successful Blender log contains lines like:

```text
Video append frame 1
...
Video append frame 120
```

Validate the output with ffprobe when available:

```bash
ffprobe -v error -select_streams v:0 -show_entries stream=width,height,r_frame_rate,nb_frames:format=duration -of json proxy.mp4
```

Compare metadata with the requested render profile. At 24 fps, a five-second
video has 120 frames; use the task's duration and dimensions for other profiles.

## Fallback Policy

Do not default to external ffmpeg frame-sequence encoding. Use it only when:

- direct Blender MP4 fails after confirming `media_type="VIDEO"`,
- Blender is built without FFmpeg support,
- the user explicitly wants frame-level debugging,
- or reproducibility requires preserved frames.

If frame sequences are used, put them under a temporary or ignored `outputs/frames/...` directory and clean them after successful MP4 encoding unless the user asks to keep them.

## Minimal Diagnostics

Avoid rechecking everything every time. If video output fails, run the smallest relevant check:

```bash
blender --background --factory-startup --python-exit-code 1 --python-expr "import bpy; s=bpy.context.scene; print(s.render.image_settings.media_type, s.render.image_settings.file_format); s.render.image_settings.media_type='VIDEO'; s.render.image_settings.file_format='FFMPEG'; print(s.render.image_settings.media_type, s.render.image_settings.file_format, bpy.app.version_string)"
```

If this succeeds, the bug is in the script settings, not the Blender install.
