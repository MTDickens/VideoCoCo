# H3 / H3-Max clay-reference evidence

Checked 2026-09-17. The shared prompt in this repo is **experimental community-derived
guidance**, not an official clay mode or a claim of identical model behavior.

## Sources

| Model | Primary source | What it establishes |
| --- | --- | --- |
| H3 | [Mickmumpitz's X demo, August 12](https://x.com/mickmumpitz/status/2087477139247419726) and [creator's published guide/template](https://mickmumpitz.ai/posts/new-video-free-166463119?l=en-GB) | A clay-video-to-finished-render workflow, with a published prompt and explicit instructions for disabling the optional acceleration LoRA. This is local ComfyUI evidence, not a benchmark of fal's hosted endpoint. |
| H3-Max | [İlker's X demo, September 8](https://x.com/ailker/status/2097363834042233040) | The creator explicitly names H3-Max. The attached comparison shows a simple colored Blender building animation and a realistic rendering following the same camera views. It is not an entirely gray clay input, and the post does not publish its exact prompt or API payload. |
| H3-Max | [Gokay's Blender demo repository](https://github.com/gokayfem/H3-Max-Blender) | Public prompts separate gray geometry from desired appearance. The inspected implementation submits `reference_image_urls`, so it does not establish preservation of an animated clay-video reference. |

Grok's CLI was asked to search public X material using its web-search tools.
It returned useful leads but crashed before completing its report. Original X
post text/media were checked using X's public syndication data; the H3-Max
comparison video was inspected. No native X-search capability was available in
that CLI. No inference requests were submitted during this research.

## Shared approach used by this repo

The H3 creator separates animation/layout from final appearance and recommends
a timeline extending to the clip's end. Appearance images are optional in that
workflow. We adapt those ideas to our existing prompt-plus-proxy pipeline:

1. Identify `Video 1` as an untextured clay animation used for geometry and motion.
2. Preserve the audited objects, camera, trajectories, contacts and causal events.
3. Describe realistic materials, surface detail and light for the entire shot.
4. Have the agent derive a full-duration timeline from the actual audited plan.
5. Include sound directions consistent with the visible events.

The exact shared contract lives in `H3_CLAY_CONTRACT` in
[`scripts/generate_video.py`](../scripts/generate_video.py); both agents receive
it through `edit_prompt_guidance()`. Existing-proxy runs use `reference_prompt()`.
This is our own adaptation, not an exact prompt claimed to come from the H3-Max demo.

## API evidence and unresolved limits

The official [H3 API](https://fal.ai/models/minimax/h3/reference-to-video/api) and
[H3-Max API](https://fal.ai/models/minimax/h3-max/reference-to-video/api) document
`Video 1` references, `reference_video_urls`, integer durations and prompt-expansion
controls. The runner disables expansion for both and sends one reference video.
With `--image-to-ref2va`, it also sends `reference_image_urls` and assigns
appearance to `Image 1`, while preserving geometry and motion from `Video 1`.
This mixed-reference schema is shared by both endpoints; it does not make the
image a guaranteed first frame or establish clay-specific fidelity.
Neither schema provides a clay-specific switch. No LoRA or custom weights are used.

We did **not** find official clay-specific instructions confirmed unchanged for
both models, or an exact published H3-Max video-reference prompt in the inspected
posts. Shared guidance is therefore a hypothesis for research, not proof of equal
geometry/timing fidelity. A paired generation from the same proxy followed by a
frame-by-frame comparison is still needed to establish practical reliability.
