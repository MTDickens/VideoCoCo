# VideoCoCo inference with Seedance 2.0

Use [`scripts/generate_video.py`](../scripts/generate_video.py) for prompt-to-video
generation through fal.ai Seedance 2.0.

```bash
uv sync --locked
cp -n .env.example .env  # Once; then fill in FAL_KEY in .env.
uv run --env-file .env scripts/generate_video.py --login  # One-time isolated Codex login.
uv run --env-file .env scripts/generate_video.py \
  --prompt "An ice cube melts on a warm plate, shrinking into a growing pool of water." \
  --output outputs/melting.mp4
```

The default mode creates and audits a Blender physics proxy before restyling it
with Seedance. Use `--agent pi` to select Pi instead of Codex for this same stage.
Authenticate once with `uv run scripts/generate_video.py --agent pi --login`,
then enter `/login openai-codex` in Pi and `/quit` after ChatGPT sign-in. Both agents
use isolated credentials/configuration, `gpt-6-astra`, fast service, and xhigh reasoning.
Pi runs generated code with normal local permissions and has no built-in sandbox.

Add `--direct` for Seedance text-to-video, or `--proxy video.mp4` to restyle an
existing proxy. These two modes do not require either agent or its login.

See [`seedance.md`](seedance.md) for prerequisites, isolation settings, output
artifacts, and interrupted-job recovery.
