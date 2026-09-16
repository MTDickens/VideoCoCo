# 🎬 VideoCoCo: Code as CoT for Physics-Faithful Video Generation

Official repository for **VideoCoCo**, a physics-faithful video generation
pipeline that uses **code as a chain-of-thought** to draft physics before
committing to pixels.

[[💻 Original project](https://github.com/micky-li-hd/VideoCoCo)]

<p align="center"><img src="figs/cot-paradigm.png" width="90%"></p>

## 💥 News
- **[2026.07.29]** Original release of the Agent Skills and toy dataset.

## 🪄 Draft Before Generation

We propose **VideoCoCo**, an interleaved reasoning paradigm that carries a
physical prior through an explicit visual draft before committing to pixels.

Our method 🎨 **first has a code agent write simulation code and render it in a
sandbox as a neutral white/clay _proxy_ video** that carries the correct motion,
causality, and physics — meaning is expressed by shape, transparency,
deformation, and coverage, never by color.

Then we 🔎 **verify the proxy against the physical plan** (a caused state must
stay hidden until its causing transition), and 🖼️ **restyle the proxy into a
photorealistic video** driven by a per-case edit instruction.

<p align="center"><img src="figs/pipeline.png" width="100%"></p>

## 📦 What's in this repo

- **`skill/`** — the three released Agent Skills: `physical-state-planner`
  → `physical-video-blender-implementer` → `blender-mcp-video`.
  The originally named `seedance-edit-prompt` and `seedance-distill` skills
  are not included in this checkout.
- **`scripts/generate_video.py`** — prompt → Codex or Pi/Blender physics draft → fal.ai
  H3-Max (default), H3 or Seedance 2.0 → saved MP4; also supports existing proxies
  and direct Seedance text-to-video.
- **`data/toy_cases/`** — 8 hand-checked video-to-video (v2v) triplets.
- **`inference/`** — setup, usage and clay-prompt research notes.

## 🎬 Toy dataset

`data/toy_cases/` — 8 v2v triplets, one directory per case:

```
data/toy_cases/
├── manifest.jsonl                 # one JSON line per case (index)
├── 0000_buoyancy/
│   ├── video.mp4                  # source: neutral white/clay physics proxy
│   ├── seedance.mp4               # target: photoreal restyle
│   └── edit_prompt.txt            # instruction used to restyle proxy -> photoreal
└── ...
```

Each `manifest.jsonl` line:

```json
{"case_id": "0000_buoyancy", "source": "0000_buoyancy/video.mp4", "target": "0000_buoyancy/seedance.mp4", "instruction": "...", "category": "buoyancy"}
```

- **source** (`video.mp4`) — a grayscale/white-material render. Physical meaning
  is carried by shape, motion, transparency, deformation, and coverage, not color.
- **target** (`seedance.mp4`) — the photorealistic result.
- **instruction** (`edit_prompt.txt`) — the English restyle prompt mapping source
  motion to the photoreal target.

The 8 cases cover buoyancy, stress/deformation, melting (×2), surface tension,
sublimation, elasticity, and boiling — a *toy* sample for format inspection, not
a training-scale corpus.

## ⚙️ Inference

For **fal.ai H3-Max, H3 or Seedance 2.0**, use the
[prompt-to-video runner](inference/seedance.md):

Keep your inputs together in a folder: `prompt.txt` plus optional
`reference.png` (also `.jpg`, `.jpeg`, `.webp`). The example below uses the
included `examples/ballistic_pendulum_cardboard/prompt.txt`. Add `--image-to-agent` to guide the
physics draft, `--image-to-ref2va` to send the image to the final video model,
or both. Both switches default off; final-only routing warns but is allowed.

```bash
uv sync --locked
cp -n .env.example .env  # Once; then fill in FAL_KEY in .env.
uv run --env-file .env scripts/generate_video.py --login  # One-time isolated Codex login.
uv run --env-file .env scripts/generate_video.py \
  --input-dir examples/ballistic_pendulum_cardboard \
  --output outputs/ballistic_pendulum_cardboard.mp4
```

For Pi with your ChatGPT subscription instead:

```bash
uv run --env-file .env scripts/generate_video.py --agent pi --login
# In Pi: /login openai-codex, then /quit after signing in.
uv run --env-file .env scripts/generate_video.py --agent pi \
  --input-dir examples/ballistic_pendulum_cardboard \
  --output outputs/ballistic_pendulum_cardboard-pi.mp4
```

Both agents use `gpt-6-astra`, fast service, xhigh reasoning, and isolated
configuration/login stores. Codex remains the default. Pi provides the same
draft/audit workflow with normal local permissions; it has no built-in sandbox.

H3-Max is the default video model. Add `--video-model h3` or
`--video-model seedance` to switch. Both H3 variants use the same experimental
clay-reference guidance; see [sources and limitations](inference/h3-clay-research.md).

The physics pipeline also needs the chosen agent CLI, Blender, and FFmpeg. Add
`--direct` to use only Seedance text-to-video, requiring the prompt folder and fal
credentials. See the guide for setup, agent isolation, existing proxies, and recovery.

## Development

The video runner uses `uv` throughout. Its tooling is selectively adapted from
[research-code-python-starter-template](https://github.com/MTDickens/research-code-python-starter-template):
Ruff for formatting, import sorting, and linting; `ty` for static types; and pytest
for the existing offline tests. Versions are pinned in `uv.lock`.

```bash
uv sync --locked
bash run_autoformat.sh  # Safe lint fixes and formatting.
bash run_ci_checks.sh   # Formatting, linting, types, and tests.
```

Checks cover `scripts/` and `tests/`, targeting Python 3.10+.
GitHub Actions runs the same checks on Python 3.10 and 3.14, without API credentials,
Blender, or paid model calls. Use `uv sync --locked --no-dev` for runtime dependencies
only; development tools live in the `dev` dependency group.

## 🗺️ Roadmap

- [x] Agent Skills (`skill/` — prompt → physical plan → Blender proxy → photoreal edit prompt)
- [x] Toy dataset (8 v2v triplets)
- [x] Seedance 2.0 runner (physics drafts, direct generation, proxy restyling, and recovery)
- [x] Codex and Pi backends with isolated configuration and shared artifact checks
- [x] uv-managed environment, Ruff, ty, pytest, and CI

## 🧠 Our Related Work

Explore our additional research on **Text-to-Image / Video Generation** and **CoT Reasoning**:

- **[CoCo]** [CoCo: Code as CoT for Text-to-Image Preview and Rare Concept Generation](https://arxiv.org/abs/2603.08652) · [model](https://huggingface.co/mickyhimself/CoCo)
- **[DraCo]** [DraCo: Draft as CoT for Text-to-Image Preview and Rare Concept Generation](https://arxiv.org/abs/2512.05112) · [code](https://github.com/CaraJ7/DraCo)
- **[UniCorn]** [UniCorn: Towards Self-Improving Unified Multimodal Models through Self-Generated Supervision](https://arxiv.org/abs/2601.03193) · [code](https://github.com/Hungryyan1/UniCorn)
- **[SCOPE]** [SCOPE: Structured Decomposition and Conditional Skill Orchestration for Complex Image Generation](https://arxiv.org/abs/2605.08043) · [code](https://github.com/nopnor/SCOPE)
- **[T2I-R1]** [T2I-R1: Reinforcing Image Generation with Collaborative Semantic-level and Token-level CoT](https://arxiv.org/abs/2505.00703) · [code](https://github.com/CaraJ7/T2I-R1)
- **[Image Generation CoT]** [Can We Generate Images with CoT? Let's Verify and Reinforce Image Generation Step by Step](https://arxiv.org/abs/2501.13926) · [code](https://github.com/ZiyuGuo99/Image-Generation-CoT)
- **[NextStep-1]** [NextStep-1: Toward Autoregressive Image Generation with Continuous Tokens at Scale](https://arxiv.org/abs/2508.10711) · [code](https://github.com/stepfun-ai/NextStep-1)
- **[LongCat-Next]** [LongCat-Next](https://github.com/meituan-longcat/LongCat-Next) · [model](https://huggingface.co/meituan-longcat/LongCat-Next)

## 📄 License

Dataset released for research use.
