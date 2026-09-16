# Prompt to video with Seedance 2.0

`scripts/generate_video.py` runs the released VideoCoCo skills with Codex or Pi to
produce a physics proxy, then uses **fal.ai Seedance 2.0** to generate and download
the photorealistic MP4.

## What inputs are needed?

| Mode | Creative inputs | Requirements |
| --- | --- | --- |
| Physics pipeline (`--agent codex` or `--agent pi`) | Your scene prompt | Python 3.10+, uv dependencies, fal key/credits, the chosen agent CLI and separate authentication, Blender, FFmpeg/ffprobe |
| `--direct` | Your scene prompt | Python 3.10+, `fal-client`, fal key/credits |
| `--proxy video.mp4` | Existing proxy video + scene/edit prompt | Python 3.10+, `fal-client`, fal key/credits, ffprobe |

In the default pipeline, the physical plan, simulation code, proxy, visual audit,
and edit prompt are created automatically. You do not need a dataset, reference
image, manual plan, local model weights, or a CUDA GPU. Rendering still takes local
compute. Physics/evaluation hints can be included in your scene prompt.

This checkout provides three skills and the Seedance runner.
The originally named `seedance-edit-prompt` and `seedance-distill` skills are absent.
This runner supplies the restyle instruction and fal integration directly.

## Setup

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then from
the repository root:

```bash
uv sync --locked
cp -n .env.example .env  # Once; preserve any existing .env.
```

Put your key in the repo-root `.env` file:

```dotenv
FAL_KEY="your-fal-api-key"
```

The commands below use `uv run --env-file .env` to load it explicitly. `.env` is
gitignored; `.env.example` keeps blank placeholders. An already exported `FAL_KEY`
takes precedence, so run `unset FAL_KEY` once if you want to switch to the file.
The runner itself reads environment variables and does not search for other `.env`
files. Both agent backends exclude `FAL_KEY` from their child environment.
Generation is billed by fal. The physics stage also consumes model usage.

Dependencies are declared in `pyproject.toml` and pinned in `uv.lock`. `uv` manages
the project's `.venv`; no manual activation is needed. Use `uv run` for all commands
below and `uv add` when changing dependencies.

For the physics pipeline, install Blender, FFmpeg (including ffprobe),
and either Codex CLI or [Pi](https://pi.dev/). The isolation options were checked
with Codex CLI **0.154.0** and Pi **0.85.1**; older versions may need an update.
Use `--blender /path/to/blender`, `--ffmpeg`, `--ffprobe`, `--codex`, or `--pi`
when the executable is not on PATH. Pi is a separate CLI; Python dependencies
remain managed with uv. On macOS the runner
also recognizes `/Applications/Blender.app/Contents/MacOS/Blender`.

Authenticate once for your chosen backend. Codex is the default:

```bash
uv run --env-file .env scripts/generate_video.py --login
```

Alternatively, supply `CODEX_API_KEY` in the runner's environment. The runner
does not copy your personal Codex credentials. Your account must have access to
`gpt-6-astra` and fast service; it never substitutes another model.

For **Pi with your ChatGPT subscription**, run:

```bash
uv run --env-file .env scripts/generate_video.py --agent pi --login
```

In the Pi interface, enter `/login openai-codex`, finish the ChatGPT sign-in,
then `/quit`. Credentials are stored separately in `.videococo/pi-agent/auth.json`.
No OpenAI API key is needed, and personal Pi/Codex credentials are not copied.
The name `openai-codex` identifies Pi's ChatGPT provider; it does **not** launch
the Codex CLI. Pi uses `gpt-6-astra`, xhigh reasoning, and priority (fast) service.
Your subscription must support the model and service tier. There is no automatic
model or provider fallback.

## Run the physics pipeline

```bash
uv run --env-file .env scripts/generate_video.py \
  --prompt "An ice cube on a warm ceramic plate slowly melts into a connected pool of water, with the cube shrinking as the pool grows." \
  --output outputs/melting.mp4
```

To use Pi for the identical workflow, add `--agent pi`:

```bash
uv run --env-file .env scripts/generate_video.py --agent pi \
  --prompt "An ice cube on a warm plate shrinks into a growing pool of water." \
  --output outputs/melting-pi.mp4
```

Use `--agent codex` explicitly or omit the flag to select Codex. Both backends
use the same three repo skills, render profile, audit schema, artifact validation,
and fal request/download code. Their generated plans and videos can differ.

Default settings: 5 seconds, 720p final output, 16:9, audio enabled. For example,
add `--duration 8 --resolution 1080p --aspect-ratio 9:16 --no-audio`.
Duration is 4–15 seconds. The physics reference remains within fal's reference
resolution limits even when requesting higher resolution final output.

The sequence is:

1. The chosen agent reads the three repo skills and writes a physical state plan.
2. It writes/runs a standalone Blender script and renders a clay proxy.
3. It inspects semantic keyframes and transitions, repairing at most twice.
   A failed or uncertain audit stops the run before any fal submission.
4. The runner uploads the proxy and sends its edit prompt with `@Video1` to
   `bytedance/seedance-2.0/reference-to-video`.
5. It polls the fal queue and downloads the video to your output path.

Artifacts are kept beside the output in `outputs/melting.run/`: `input.json`,
`physical_plan.json`, `scene.blender.py`, `proxy.mp4`, `preview.png`, `audit.json`,
`edit_prompt.txt`, the agent's prompt/command/log, `fal_input.json`, and `fal_request.json`.
Pi also saves `pi.events.jsonl` with its tool and message trace. The runner takes
Pi's final JSON response as the audit and verifies an image read of `preview.png`.
Both backends' audits are validated against the same JSON Schema before upload.
`fal_request.json` includes the returned result and remote video URL. Existing outputs
and artifact directories are never overwritten; choose a new output name.

The draft may approximate physics. The agent's visual audit is not a numerical proof.
Seedance reference conditioning does not guarantee frame-for-frame preservation;
inspect the final video for your use case.

## Direct Seedance: no agent or Blender

```bash
uv run --env-file .env scripts/generate_video.py --direct \
  --prompt "A cinematic close-up of an ice cube melting on a warm ceramic plate." \
  --output outputs/direct.mp4
```

This uses `bytedance/seedance-2.0/text-to-video`. The prompt is the only creative
input. It skips VideoCoCo's physics stages. Neither this mode nor `--proxy` starts
an agent or reads agent configuration, regardless of the `--agent` selection.

## Use an existing proxy

The included toy cases can go straight to Seedance:

```bash
uv run --env-file .env scripts/generate_video.py \
  --proxy data/toy_cases/0000_buoyancy/video.mp4 \
  --prompt-file data/toy_cases/0000_buoyancy/edit_prompt.txt \
  --output outputs/buoyancy-seedance.mp4
```

The runner adds an explicit `@Video1` restyle instruction and validates the video
before uploading. fal requires an MP4/MOV under 50 MB, 2–15 seconds long, with a
reference resolution in its documented pixel-area bounds (approximately 480p–720p).
This runner uses one reference video.

## Dry runs and recovery

Inspect settings without dependencies, keys, writes, or API calls:

```bash
uv run --env-file .env scripts/generate_video.py --prompt "A ball bounces on a table." --dry-run
uv run --env-file .env scripts/generate_video.py --agent pi --prompt "A ball bounces on a table." --dry-run
uv run --env-file .env scripts/generate_video.py --direct --prompt "A ball bounces on a table." --dry-run
```

Render and audit only (uses the chosen agent's authentication but does not need a fal key):

```bash
uv run --env-file .env scripts/generate_video.py --prepare-only \
  --prompt "A ball bounces on a table, losing height with each bounce." \
  --output outputs/bounce.mp4
```

Add `--agent pi` to use Pi here as well.

After reviewing the draft, use `--proxy outputs/bounce.run/proxy.mp4` with
`--prompt-file outputs/bounce.run/edit_prompt.txt` and a new output path.
If a later fal step fails, likewise reuse the saved proxy rather than rebuilding.

If a submitted fal job times out or the download fails:

```bash
uv run --env-file .env scripts/generate_video.py --resume outputs/melting.run/fal_request.json
```

This retrieves the same job without submitting another generation. A completed
result is saved before download. `--timeout 3600` increases the queue wait limit.
Interrupting or timing out does not cancel the remote job. If submission fails
before returning a request ID, check the fal dashboard before retrying; acceptance
may be ambiguous.

## Codex isolation

Login credentials live in `.videococo/codex-home/`. Each generation receives a
fresh temporary `CODEX_HOME`, seeded only with that dedicated login; refreshed
credentials are saved back afterwards. Your shell environment and personal config
are unchanged. The runner copies the three repo skill folders into an isolated
temporary workspace. It sets:

- `model="gpt-6-astra"`, `model_reasoning_effort="xhigh"`, `service_tier="fast"`.
- `--ignore-user-config`, `--ignore-rules`, `--ephemeral`, and no session resume.
- Memory use/generation and external memory import disabled.
- Automatically discovered skills, skill search, plugins, apps, hooks, multi-agent tools,
  web search, shell snapshots, and login shells disabled.
- No inherited provider overrides or parent Codex session environment; no fal key
  passed to Codex. Repo skills are explicitly referenced in the task prompt.
- Workspace-write sandbox with shell network access disabled. Blender runs through
  the CLI, so no personal Blender MCP configuration is needed.

Setting `CODEX_HOME` alone would not exclude `~/.agents/skills`. The runner enumerates
skill entry-point paths and disables them with `skills.config`, including bundled
skills. It uses the local `codex debug prompt-input` command to verify that no
automatic skill catalog remains **before any model call**; this check fails closed.
The initial inspection is neither persisted nor sent to a model. Machine-managed
Codex policies still apply.
This isolates configuration and memory, not all filesystem reads; the normal
Codex sandbox and permissions remain in effect. Authentication is retained only
in the dedicated store; runtime files are gitignored.

The runner needs `codex debug prompt-input` (checked in 0.154.0).
`--strict-config` rejects unsupported configuration on the generation command.

## Pi isolation and permissions

Each Pi run gets a fresh temporary `PI_CODING_AGENT_DIR`, seeded only with the
dedicated repo-local ChatGPT login. Refreshed credentials are saved back afterwards;
settings, model catalogs, sessions, and extensions are not copied from your personal
Pi directory. The run uses a temporary workspace outside the repo ancestry and:

- `--no-session`, with no session resume or external memory.
- `--no-context-files`, `--no-skills`, `--no-prompt-templates`, `--no-themes`,
  `--no-extensions`, and `--no-approve` to disable automatic context and extension
  discovery. Repo skills are explicit files in the task prompt.
- Only the built-in `read`, `bash`, `edit`, and `write` tools. `read` sends preview
  images to the model for the visual audit.
- A clean child environment, without fal/API keys, inherited Pi/Codex session
  settings, Node startup hooks, or shell startup overrides. `HOME` is unchanged.
- Disabled startup network checks/telemetry and a non-login Bash shell.
  `PI_OFFLINE=1` disables startup network activity, not model requests.
- One explicitly loaded repo extension, `scripts/pi_video.ts`, which sets
  `service_tier="priority"`, reasoning `xhigh`, and `store=false` on model requests.
  It adds no tools or memory. Automatic extensions remain disabled.

**Pi does not provide Codex's workspace sandbox.** Its tools and generated Blender
code run with your normal local filesystem and network permissions. This setup
isolates configuration and sessions; it is not OS-level containment. Use Codex's
backend or run Pi inside an external container if you need that restriction.

Pi's JSON event mode can return exit code zero after a provider failure. The runner
checks the final assistant stop reason, model/provider, preview inspection, JSON
schema, and the shared audit checks before any fal upload or submission. Partial
artifacts and logs survive failures for inspection.

## Offline tests and official references

```bash
uv run pytest
bash run_ci_checks.sh  # Also checks Ruff formatting/lint and ty types.
```

Use `bash run_autoformat.sh` to apply safe Ruff fixes and formatting. The existing
unittest-style cases run under pytest without requiring a framework rewrite.
All development tools are in the uv-managed `dev` dependency group and pinned in
`uv.lock`. Checks cover `scripts/` and `tests/`; no GPU or credentials are needed.
When Pi is installed, two additional offline integration checks verify its actual
context isolation and priority/xhigh request serialization. They use synthetic
credentials and stop before any model request. These checks skip when Pi is absent.
Live ChatGPT generation, Blender drafting, and fal billing are not exercised by tests.

- [Seedance text-to-video schema](https://fal.ai/models/bytedance/seedance-2.0/text-to-video/api)
- [Seedance reference-to-video schema](https://fal.ai/models/bytedance/seedance-2.0/reference-to-video/api)
- [fal Python client](https://fal.ai/docs/api-reference/client-libraries/python/fal_client)
- [Codex configuration](https://developers.openai.com/codex/config-reference/)
- [Codex non-interactive mode](https://developers.openai.com/codex/noninteractive/)
- [Codex skill discovery](https://developers.openai.com/codex/skills/)
- [Pi CLI and isolation flags](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/README.md)
- [Pi authentication providers](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/providers.md)
- [Pi request extensions](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/extensions.md)
