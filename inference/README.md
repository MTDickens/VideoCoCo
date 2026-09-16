# VideoCoCo inference with fal.ai

Use [`scripts/generate_video.py`](../scripts/generate_video.py) for prompt-to-video
generation through fal.ai H3-Max (default), H3 or Seedance 2.0.

Put `prompt.txt` and an optional `reference.png` (or `.jpg`, `.jpeg`, `.webp`)
in one folder and pass it with `--input-dir`. The included example is ready to use.
`--image-to-agent` and `--image-to-ref2va` independently route the image; both
default off. Final-model-only routing emits a warning but is allowed.

```bash
uv sync --locked
cp -n .env.example .env  # Once; then fill in FAL_KEY in .env.
uv run --env-file .env scripts/generate_video.py --login  # One-time isolated Codex login.
uv run --env-file .env scripts/generate_video.py \
  --input-dir examples/ballistic_pendulum_cardboard \
  --output outputs/ballistic_pendulum_cardboard.mp4
```

The default mode creates and audits a Blender physics proxy before restyling it
with H3-Max. Use `--video-model h3` or `--video-model seedance` to change the
video backend. Use `--agent pi` to select Pi instead of Codex for this same stage.
Authenticate once with `uv run scripts/generate_video.py --agent pi --login`,
then enter `/login openai-codex` in Pi and `/quit` after ChatGPT sign-in. Both agents
use isolated credentials/configuration, `gpt-6-astra`, fast service, and xhigh reasoning.
Pi runs generated code with normal local permissions and has no built-in sandbox.

Add `--direct` for Seedance text-to-video, or `--proxy video.mp4` to restyle an
existing proxy. These two modes do not require either agent or its login.

See [`seedance.md`](seedance.md) for prerequisites, isolation settings, output
artifacts, and interrupted-job recovery.
See [clay-prompt research](h3-clay-research.md) for the shared experimental H3
guidance, original X demos, and the limits of the available evidence.
