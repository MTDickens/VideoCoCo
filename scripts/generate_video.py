#!/usr/bin/env python3
"""Input folder -> optional Codex or Pi/Blender physics draft -> fal video model -> MP4.

See inference/seedance.md. Only the fal stage needs the fal-client package.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse
from urllib.request import urlopen

if TYPE_CHECKING:
    from fal_client import SyncClient


REPO = Path(__file__).resolve().parents[1]
CODEX_STATE = REPO / ".videococo" / "codex-home"
PI_STATE = REPO / ".videococo" / "pi-agent"
PI_PROVIDER = "openai-codex"
PI_ISOLATION_FLAGS = [
    "--no-session",
    "--no-extensions",
    "--no-skills",
    "--no-prompt-templates",
    "--no-themes",
    "--no-context-files",
    "--no-approve",
]
MODEL = "gpt-6-astra"
TEXT_ENDPOINT = "bytedance/seedance-2.0/text-to-video"
REFERENCE_ENDPOINT = "bytedance/seedance-2.0/reference-to-video"


@dataclass(frozen=True)
class VideoModel:
    label: str
    endpoint: str
    resolutions: tuple[str, ...]
    default_resolution: str
    minimum_duration: int
    reference_token: str


VIDEO_MODELS = {
    "h3-max": VideoModel("H3-Max", "minimax/h3-max/reference-to-video", ("480p", "768p", "1080p"), "768p", 5, "Video 1"),
    "h3": VideoModel("H3", "minimax/h3/reference-to-video", ("480p", "768p", "2k", "4k"), "768p", 5, "Video 1"),
    "seedance": VideoModel("Seedance 2.0", REFERENCE_ENDPOINT, ("480p", "720p", "1080p"), "720p", 4, "@Video1"),
}
# Shared experimental guidance, adapted from community examples rather than an
# official clay mode. Provenance and limitations: inference/h3-clay-research.md.
H3_CLAY_CONTRACT = (
    "Video 1 is a neutral, untextured clay animation supplied as a geometry and motion reference. "
    "Create a photorealistic version of the same shot. At corresponding timestamps, retain the same "
    "objects, silhouettes, relative sizes, spatial arrangement, trajectories, contact sequence, "
    "deformations, phase changes and cause-and-effect order. Match the reference camera and framing "
    "throughout a single uninterrupted shot. Replace the proxy's gray surfaces with the described "
    "real-world materials, colors, fine surface detail and illumination from the first frame onward. "
    "Keep the established geometry and animation; add no objects, actions, cuts or transitions."
)
PROXY_SIZES = {
    "16:9": (1280, 720),
    "9:16": (720, 1280),
    "1:1": (720, 720),
    "4:3": (960, 720),
    "3:4": (720, 960),
    "21:9": (1120, 480),
}
SKILLS = ("physical-state-planner", "physical-video-blender-implementer", "blender-mcp-video")
# These overrides apply only to the child CLI, never to the user's configuration.
CODEX_OVERRIDES = [
    f'model="{MODEL}"',
    'model_reasoning_effort="xhigh"',
    'service_tier="fast"',
    'cli_auth_credentials_store="file"',
    'approval_policy="never"',
    'sandbox_mode="workspace-write"',
    "sandbox_workspace_write.network_access=false",
    "project_doc_max_bytes=0",
    'project_root_markers=[".videococo-root"]',
    "allow_login_shell=false",
    'web_search="disabled"',
    "features.memories=false",
    "memories.use_memories=false",
    "memories.generate_memories=false",
    "features.skill_search=false",
    "features.plugins=false",
    "features.remote_plugin=false",
    "features.apps=false",
    "features.hooks=false",
    "features.shell_snapshot=false",
    "features.multi_agent=false",
    "features.external_agent_memory_import=false",
    'shell_environment_policy.inherit="core"',
    'shell_environment_policy.exclude=["FAL_*", "OPENAI_*", "CODEX_API_KEY"]',
]


def object_schema(properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


STRING = {"type": "string"}
AUDIT_SCHEMA = object_schema(
    {
        "status": {"type": "string", "enum": ["passed", "failed"]},
        "summary": STRING,
        "checks": {
            "type": "array",
            "items": object_schema(
                {
                    "check": STRING,
                    "status": {"type": "string", "enum": ["pass", "fail", "uncertain"]},
                    "evidence": STRING,
                }
            ),
        },
        "keyframe_frame_map": {
            "type": "array",
            "items": object_schema(
                {
                    "keyframe": STRING,
                    "frame": {"type": "integer"},
                }
            ),
        },
        "known_limitations": {"type": "array", "items": STRING},
    }
)


def write_json(path: Path, value: Any) -> None:
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def executable(name: str) -> str:
    found = shutil.which(str(name))
    if not found and name == "blender":
        candidate = Path("/Applications/Blender.app/Contents/MacOS/Blender")
        if candidate.is_file():
            found = str(candidate)
    if not found:
        raise RuntimeError(f"Cannot find executable {name!r}. Install it or pass its full path.")
    return str(Path(found).absolute())


def base_environment() -> dict[str, str]:
    # Do not inherit provider overrides, MCP sockets, proxy credentials, .env files,
    # or a parent Codex session. Keep HOME unchanged; skills are disabled separately.
    allowed = (
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "LANG",
        "LC_ALL",
        "TMPDIR",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "PATHEXT",
        "USERPROFILE",
        "TERM",
    )
    env = {key: os.environ[key] for key in allowed if key in os.environ}
    env["SHELL"] = "/bin/sh" if os.name != "nt" else os.environ.get("COMSPEC", "cmd.exe")
    return env


def codex_environment(state_dir: Path = CODEX_STATE) -> dict[str, str]:
    env = base_environment()
    env["CODEX_HOME"] = str(state_dir)
    if os.environ.get("CODEX_API_KEY", "").strip():
        env["CODEX_API_KEY"] = os.environ["CODEX_API_KEY"]
    return env


def pi_environment(state_dir: Path) -> dict[str, str]:
    env = base_environment()
    env.update(
        PI_CODING_AGENT_DIR=str(state_dir),
        PI_CODING_AGENT_SESSION_DIR=str(state_dir / "sessions"),
        PI_OFFLINE="1",
        PI_SKIP_VERSION_CHECK="1",
        PI_TELEMETRY="0",
    )
    return env


def pi_settings(runtime: Path) -> None:
    settings: dict[str, Any] = {
        "enableInstallTelemetry": False,
        "transport": "sse",
        "retry": {"enabled": False},
        "images": {"blockImages": False},
    }
    if os.name != "nt":
        settings["shellPath"] = "/bin/bash"
    write_json(runtime / "settings.json", settings)


def pi_command(pi: str, extension: Path | None = None, reference_image: Path | None = None) -> list[str]:
    command = [pi, *PI_ISOLATION_FLAGS, "--provider", PI_PROVIDER, "--model", MODEL, "--thinking", "xhigh"]
    if extension is not None:
        command.extend(["--extension", str(extension), "--tools", "read,bash,edit,write", "--mode", "json", "--print"])
    if reference_image is not None:
        command.append(f"@{reference_image}")
    return command


def check_pi(pi: str, *, require_auth: bool = True) -> None:
    with tempfile.TemporaryDirectory(prefix="videococo-pi-check-") as temporary:
        help_text = subprocess.check_output(
            [pi, "--help"], cwd=temporary, env=pi_environment(Path(temporary) / "agent"), text=True, timeout=30
        )
    for flag in (*PI_ISOLATION_FLAGS, "--extension", "--mode", "--thinking"):
        if flag not in help_text:
            raise RuntimeError(f"Update Pi: this runner requires {flag} (tested with 0.85.1).")
    if require_auth:
        auth_path = PI_STATE / "auth.json"
        auth = json.loads(auth_path.read_text(encoding="utf-8")) if auth_path.is_file() else {}
        credential = auth.get(PI_PROVIDER) if isinstance(auth, dict) else None
        if not isinstance(credential, dict) or credential.get("type") != "oauth":
            raise RuntimeError(
                "Pi needs a dedicated ChatGPT subscription login. Run: "
                "uv run scripts/generate_video.py --agent pi --login\n"
                "Personal Pi/Codex credentials are not copied; no OpenAI API key is needed."
            )


def pi_login(pi: str) -> None:
    check_pi(pi, require_auth=False)
    PI_STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Login itself also receives fresh settings. Persist only this dedicated auth.
    with tempfile.TemporaryDirectory(prefix="videococo-pi-login-") as temporary:
        workspace = Path(temporary) / "workspace"
        runtime = Path(temporary) / "runtime"
        workspace.mkdir()
        runtime.mkdir(mode=0o700)
        if (PI_STATE / "auth.json").is_file():
            shutil.copy2(PI_STATE / "auth.json", runtime / "auth.json")
        pi_settings(runtime)
        print("In Pi, enter /login openai-codex, complete ChatGPT sign-in, then /quit.", flush=True)
        try:
            subprocess.run(pi_command(pi), cwd=workspace, env=pi_environment(runtime), check=True)
        finally:
            if (runtime / "auth.json").is_file():
                shutil.copy2(runtime / "auth.json", PI_STATE / "auth.json")
                (PI_STATE / "auth.json").chmod(0o600)
    check_pi(pi)
    print(f"Dedicated Pi authentication saved under {PI_STATE}")


def pi_audit(events_path: Path, workspace: Path) -> None:
    """Extract Pi's final answer; JSON mode can exit zero on a provider error."""
    final: dict[str, Any] | None = None
    finished = False
    preview_calls: set[str] = set()
    inspected_preview = False
    with events_path.open(encoding="utf-8") as events:
        for line in events:
            if not line.strip():
                continue
            event = json.loads(line)
            kind = event.get("type")
            if kind == "message_end" and event.get("message", {}).get("role") == "assistant":
                final = event["message"]
                finished = False
            elif kind == "agent_end":
                finished = True
            elif kind == "tool_execution_start" and event.get("toolName") == "read":
                path = Path(event.get("args", {}).get("path", ""))
                if (workspace / path).resolve() == (workspace / "preview.png").resolve():
                    preview_calls.add(event["toolCallId"])
            elif kind == "tool_execution_end" and event.get("toolCallId") in preview_calls and not event.get("isError"):
                inspected_preview |= any(part.get("type") == "image" for part in event.get("result", {}).get("content", []))
    if not finished or final is None or final.get("stopReason") != "stop":
        raise RuntimeError("Pi did not finish successfully. Inspect pi.events.jsonl and pi.log; no fal job was submitted.")
    if (final.get("provider"), final.get("model")) != (PI_PROVIDER, MODEL):
        raise RuntimeError("Pi used an unexpected provider/model; no fal job was submitted.")
    if not inspected_preview:
        raise RuntimeError("Pi did not inspect preview.png with its image read tool; no fal job was submitted.")
    response = "".join(part["text"] for part in final.get("content", []) if part.get("type") == "text")
    # The final answer, not an earlier agent-written audit, is authoritative.
    try:
        audit = json.loads(response)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Pi's final answer must be one JSON audit object. Inspect pi.events.jsonl.") from exc
    write_json(workspace / "audit.json", audit)


def codex_command(
    codex: str, workspace: Path, audit_path: Path, skill_override: str, reference_image: Path | None = None
) -> list[str]:
    command = [
        codex,
        "exec",
        "--ignore-user-config",
        "--ignore-rules",
        "--strict-config",
        "--ephemeral",
        "--skip-git-repo-check",
        "--cd",
        str(workspace),
        "--color",
        "never",
        "--output-schema",
        str(workspace / "audit_schema.json"),
        "--output-last-message",
        str(audit_path),
    ]
    if reference_image is not None:
        command.extend(["--image", str(reference_image)])
    for override in [*CODEX_OVERRIDES, skill_override]:
        command.extend(["-c", override])
    return command + ["-"]


def skill_files(root: Path) -> Iterator[Path]:
    """Find skill entry points, including symlinks, without reading their content."""
    visited = set()
    for directory, children, files in os.walk(root, followlinks=True):
        resolved = Path(directory).resolve()
        if resolved in visited:
            children[:] = []
            continue
        visited.add(resolved)
        if "SKILL.md" in files:
            yield Path(directory) / "SKILL.md"


def isolate_skill_context(codex: str, workspace: Path, runtime: Path) -> str:
    # Bootstrap the bundled skill files, then disable every automatically loaded
    # skill. The task receives the repo skills as explicit files instead.
    command = [codex, "debug", "prompt-input"]
    for value in CODEX_OVERRIDES:
        command.extend(["-c", value])
    env = codex_environment(runtime)
    subprocess.run(command, cwd=workspace, env=env, check=True, capture_output=True, timeout=60)
    roots = [Path.home() / ".agents" / "skills", Path("/etc/codex/skills"), runtime / "skills"]
    paths = {str(path) for root in roots for path in skill_files(root)}
    # The CLI currently expects SKILL.md paths, not containing directories.
    paths |= {str(Path(path).resolve()) for path in paths}
    override = "skills.config=[" + ",".join("{path=" + json.dumps(path) + ",enabled=false}" for path in sorted(paths)) + "]"
    result = subprocess.run(
        command + ["-c", override], cwd=workspace, env=env, check=True, capture_output=True, text=True, timeout=60
    )
    # This is a local context renderer, not a model request. Never persist the
    # initial context containing personal skill descriptions or send it to a model.
    if "<skills_instructions>" in result.stdout:
        raise RuntimeError("Codex still discovers unrelated skills. Isolation check failed; no model was called.")
    return override


def check_codex(codex: str) -> None:
    # Fail before a paid call if the installed CLI cannot enforce the isolation.
    help_text = subprocess.check_output(
        [codex, "exec", "--help"], text=True, env=codex_environment(), stderr=subprocess.DEVNULL
    )
    for flag in ("--ignore-user-config", "--ignore-rules", "--ephemeral", "--strict-config"):
        if flag not in help_text:
            raise RuntimeError(f"Update Codex CLI: this runner requires {flag} (tested with 0.154.0).")
    if not os.environ.get("CODEX_API_KEY", "").strip() and not (CODEX_STATE / "auth.json").is_file():
        raise RuntimeError(
            "Codex needs its own login. Run: uv run scripts/generate_video.py --login\n"
            "Alternatively set CODEX_API_KEY for this invocation. Personal auth/config is not copied."
        )


def login(codex: str) -> None:
    CODEX_STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(prefix="videococo-login-") as temporary:
        command = [codex, "login", "--device-auth", "-c", 'cli_auth_credentials_store="file"']
        subprocess.run(command, cwd=temporary, env=codex_environment(), check=True)
    print(f"Dedicated Codex authentication saved under {CODEX_STATE}")


def image_reference_instruction(video_model: str) -> str:
    image_token = "@Image1" if video_model == "seedance" else "Image 1"
    video_token = VIDEO_MODELS[video_model].reference_token
    return (
        f"Use {image_token} as the appearance reference for corresponding subjects and surfaces in {video_token}, "
        f"including materials, colors, fine detail and lighting. Keep the geometry, camera, motion and event timing "
        f"from {video_token}."
    )


def edit_prompt_guidance(args: argparse.Namespace) -> str:
    video_token = VIDEO_MODELS[args.video_model].reference_token
    if args.image_to_ref2va:
        inputs = (
            f"The video model receives this text, the clay clip {video_token}, and one appearance image. "
            f"Include this image-reference instruction in edit_prompt.txt:\n   {image_reference_instruction(args.video_model)}"
        )
        if not args.image_to_agent:
            inputs += "\n   You have not been given the image; specify its role without inventing visual details."
    else:
        inputs = f"The video model receives only this text and the clay clip {video_token}; make the prompt self-contained."
        if args.image_to_agent:
            inputs += (
                "\n   Describe the attached image's relevant appearance explicitly in words; "
                "the video model will not receive the image."
            )
    if args.video_model == "seedance":
        return f"""a concise English instruction for Seedance 2.0 to restyle
   @Video1 (this proxy) into the requested photorealistic scene. Preserve the proxy's
   object count, geometry, timing, camera, shot structure, trajectories, contact order, phase changes,
   and causal sequence. Restore appropriate colors, materials, detail and lighting.
   Describe the intended scene and critical physical constraints explicitly.
   {inputs}
   Keep edit_prompt.txt as plain text containing only the video-generation instructions."""
    return f"""an English clay-to-photoreal instruction for {VIDEO_MODELS[args.video_model].label}.
   Begin edit_prompt.txt with this reference instruction:
   {H3_CLAY_CONTRACT}
   Then describe the requested appearance and the physical constraints from the plan.
   {inputs}
   Include a Timeline section spanning 0 through {args.duration} seconds, derived from
   the audited keyframes, without changing their events or timing. Include an Audio
   section: requested sound, or natural ambience and event-synchronized sounds.
   Keep edit_prompt.txt as plain text containing only the video-generation instructions."""


def draft_instructions(prompt: str, args: argparse.Namespace, blender: str, ffmpeg: str, ffprobe: str) -> str:
    width, height = PROXY_SIZES[args.aspect_ratio]
    image_tool = "read (open preview.png as an image attachment)" if args.agent == "pi" else "view_image"
    image_guidance = ""
    if args.image_to_agent:
        image_guidance = """
A reference image is attached. Inspect it before writing the physical plan.
Use it to establish the initial composition, visible objects, shapes and camera
framing; use the scene description to determine what happens over time. Record
assumptions about hidden geometry. Render the proxy in grayscale/clay materials
and preserve the image's appearance details in the edit prompt as appropriate.
Include an audit check comparing the proxy's initial state with the reference.
"""
    return f"""Create a physics draft for VideoCoCo in the current workspace.
Use only the three supplied repo skills under skill/ and their references. Read
skill/physical-state-planner/SKILL.md first, then the implementer and Blender skills.
Apply each skill to its corresponding workflow stage. Use the output paths,
render profile and final-response schema specified below.
Do not use personal configuration, other skills, memory, plugins, MCP, networking,
subagents, or files outside this workspace except the explicitly supplied executables.
Do not call a video-generation endpoint. Make reasonable assumptions without questions.
Use uv for any Python environment/dependency management, never pip or python -m venv.
Blender uses its own bundled Python; do not install packages into it.

The scene description is JSON-encoded data (not shell commands):
{json.dumps(prompt, ensure_ascii=False)}
{image_guidance}

Available executables (JSON strings):
Blender: {json.dumps(blender)}
FFmpeg: {json.dumps(ffmpeg)}
ffprobe: {json.dumps(ffprobe)}

Required workflow and exact output paths, relative to this workspace:
1. Write physical_plan.json using the planner's schema, including assumptions,
   4-6 semantic keyframes, transitions, causal constraints, must_show, must_avoid.
2. Implement scene.blender.py from that plan. It must be standalone, use paths
   relative to its own location, deterministic randomness, factory-startup Blender,
   grayscale/clay materials, a stable camera, and readable material transformations.
   The supplied profile overrides the skills' default paths/profile:
   {width}x{height}, 24 fps, {args.duration} seconds, frames 1 through {args.duration * 24}.
   Use the actual Blender version's API. Prefer Eevee and direct H.264 MP4 output.
   Run Blender with --background --factory-startup --python-exit-code 1 --python.
   Write proxy.mp4. Save scene.blend if useful. Do not install packages.
3. Render and verify the MP4 with ffprobe. Extract preview.png as a contact sheet
   aligned to every semantic keyframe. Visually inspect it using {image_tool} and
   inspect extra intermediate frames wherever temporal causality is ambiguous.
   Audit every keyframe, adjacent transition, causal constraint, and must_avoid.
   Repair and rerender at most twice if needed. Never claim an unrendered or
   uninspected preview passed. If checks still fail or are uncertain, report failed.
4. Write edit_prompt.txt: {edit_prompt_guidance(args)}
5. Read audit_schema.json. Your final response must be exactly one JSON object
   matching it, without Markdown fences or surrounding prose. Include checks with concrete
   visual evidence and a keyframe-to-Blender-frame mapping. status can be passed
   only when all checks pass. Be candid about simulation approximations.
"""


def validate_image_prompt(prompt: str, video_model: str, image_to_ref2va: bool) -> None:
    has_image_reference = re.search(r"@?\bImage\s*\d+\b", prompt, re.IGNORECASE) is not None
    if has_image_reference and not image_to_ref2va:
        raise RuntimeError("The edit prompt mentions an image reference, but --image-to-ref2va is off.")
    if image_to_ref2va:
        token = "@Image1" if video_model == "seedance" else "Image 1"
        if not re.search(re.escape(token) + r"\b", prompt) or (video_model != "seedance" and "@Image1" in prompt):
            raise RuntimeError(f"The edit prompt must reference the supplied image as {token}.")


def validate_draft(workspace: Path, frame_count: int, video_model: str = "seedance", image_to_ref2va: bool = False) -> str:
    from jsonschema import Draft202012Validator

    for name in ("physical_plan.json", "scene.blender.py", "proxy.mp4", "preview.png", "edit_prompt.txt", "audit.json"):
        path = workspace / name
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError(f"The agent did not produce a nonempty {name}; inspect its log.")
    audit = json.loads((workspace / "audit.json").read_text(encoding="utf-8"))
    if not Draft202012Validator(AUDIT_SCHEMA).is_valid(audit):
        raise RuntimeError("audit.json does not match audit_schema.json; no fal job was submitted.")
    checks = audit.get("checks", [])
    if audit.get("status") != "passed" or not checks or any(c.get("status") != "pass" for c in checks):
        raise RuntimeError("Physics draft did not pass its visual audit. See audit.json; no fal job was submitted.")
    plan = json.loads((workspace / "physical_plan.json").read_text(encoding="utf-8"))
    keyframes = plan.get("semantic_keyframes", [])
    mapping = audit.get("keyframe_frame_map", [])
    if not 4 <= len(keyframes) <= 6 or {k["id"] for k in keyframes} != {k["keyframe"] for k in mapping}:
        raise RuntimeError("Draft has an incomplete semantic-keyframe audit; no fal job was submitted.")
    frame_map = {entry["keyframe"]: entry["frame"] for entry in mapping}
    frames = [frame_map[keyframe["id"]] for keyframe in keyframes]
    if (
        len(mapping) != len(keyframes)
        or frames[0] != 1
        or frames[-1] != frame_count
        or any(type(frame) is not int for frame in frames)
        or any(a >= b for a, b in pairwise(frames))
    ):
        raise RuntimeError("Draft audit must cover ordered keyframes from the first through the final frame.")
    edit_prompt = (workspace / "edit_prompt.txt").read_text(encoding="utf-8").strip()
    token = VIDEO_MODELS[video_model].reference_token
    if not re.search(re.escape(token) + r"\b", edit_prompt):
        raise RuntimeError(f"edit_prompt.txt must explicitly reference {token}.")
    if video_model != "seedance" and ("@Video1" in edit_prompt or not re.search(r"\bclay\b", edit_prompt, re.IGNORECASE)):
        raise RuntimeError("edit_prompt.txt must identify the clay clip using the reference name 'Video 1'.")
    validate_image_prompt(edit_prompt, video_model, image_to_ref2va)
    return edit_prompt


def create_draft(
    prompt: str,
    args: argparse.Namespace,
    run_dir: Path,
    agent: str,
    blender: str,
    ffmpeg: str,
    ffprobe: str,
    reference_image: Path | None = None,
) -> tuple[Path, str]:
    state = PI_STATE if args.agent == "pi" else CODEX_STATE
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Work outside the repo ancestry so project/parent .codex configuration cannot
    # enter the run. Copy back artifacts even on failure, but not runtime state.
    with tempfile.TemporaryDirectory(prefix="videococo-draft-") as temporary:
        workspace = Path(temporary) / "workspace"
        workspace.mkdir()
        runtime = Path(temporary) / "runtime"
        runtime.mkdir(mode=0o700)
        if (state / "auth.json").is_file():
            shutil.copy2(state / "auth.json", runtime / "auth.json")
        (workspace / ".videococo-root").touch()
        for name in SKILLS:
            shutil.copytree(REPO / "skill" / name, workspace / "skill" / name)
        agent_image = None
        if args.image_to_agent:
            if reference_image is None:
                raise RuntimeError("--image-to-agent requires a reference image.")
            agent_image = workspace / reference_image.name
            shutil.copy2(reference_image, agent_image)
        write_json(workspace / "audit_schema.json", AUDIT_SCHEMA)
        instructions = draft_instructions(prompt, args, blender, ffmpeg, ffprobe)
        (workspace / f"{args.agent}_prompt.txt").write_text(instructions, encoding="utf-8")
        if args.agent == "pi":
            pi_settings(runtime)
            extension = runtime / "pi_video.ts"
            shutil.copy2(REPO / "scripts" / "pi_video.ts", extension)
            command = pi_command(agent, extension, agent_image)
            env = pi_environment(runtime)
        else:
            skill_override = isolate_skill_context(agent, workspace, runtime)
            command = codex_command(agent, workspace, workspace / "audit.json", skill_override, agent_image)
            env = codex_environment(runtime)
        write_json(run_dir / f"{args.agent}_command.json", command)
        print(f"Building and auditing physics draft with {args.agent}: {MODEL} (fast, xhigh).", flush=True)
        print(f"Agent log: {run_dir / (args.agent + '.log')}", flush=True)
        try:
            with (run_dir / f"{args.agent}.log").open("w", encoding="utf-8") as log:
                if args.agent == "pi":
                    events_path = run_dir / "pi.events.jsonl"
                    with events_path.open("w", encoding="utf-8") as events:
                        subprocess.run(
                            command,
                            input=instructions,
                            text=True,
                            stdout=events,
                            stderr=log,
                            env=env,
                            cwd=workspace,
                            check=True,
                        )
                    pi_audit(events_path, workspace)
                else:
                    subprocess.run(
                        command, input=instructions, text=True, stdout=log, stderr=log, env=env, cwd=workspace, check=True
                    )
            edit_prompt = validate_draft(workspace, args.duration * 24, args.video_model, args.image_to_ref2va)
        finally:
            if (runtime / "auth.json").is_file():
                # Retain refreshes of the dedicated login, never user configuration.
                shutil.copy2(runtime / "auth.json", state / "auth.json")
                (state / "auth.json").chmod(0o600)
            for item in workspace.iterdir():
                if item == agent_image:
                    # Preserve the original reference outside the agent workspace.
                    continue
                if item.name in ("skill", ".videococo-root", ".codex", ".agents", ".pi"):
                    continue
                if item.is_symlink():
                    continue
                if item.is_dir():
                    shutil.copytree(item, run_dir / item.name, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, run_dir / item.name)
    metadata = validate_proxy(run_dir / "proxy.mp4", ffprobe, args.video_model)
    stream = metadata["streams"][0]
    if (stream["width"], stream["height"]) != PROXY_SIZES[args.aspect_ratio] or abs(
        float(metadata["format"]["duration"]) - args.duration
    ) > 1 / 24:
        raise RuntimeError("Rendered proxy does not match the requested duration/aspect profile; no fal job was submitted.")
    return run_dir / "proxy.mp4", edit_prompt


def validate_proxy(path: Path, ffprobe: str, video_model: str = "seedance") -> dict[str, Any]:
    if not path.is_file() or path.suffix.lower() not in (".mp4", ".mov"):
        raise RuntimeError("--proxy must be an existing local MP4 or MOV file.")
    if path.stat().st_size == 0:
        raise RuntimeError("Reference video must be nonempty.")
    if video_model == "seedance" and path.stat().st_size >= 50_000_000:
        raise RuntimeError("Seedance reference video must be nonempty and under 50 MB.")
    metadata = json.loads(
        subprocess.check_output(
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height:format=duration",
                "-of",
                "json",
                str(path),
            ],
            text=True,
        )
    )
    streams = metadata.get("streams", [])
    if not streams:
        raise RuntimeError("Reference file has no video stream.")
    duration = float(metadata.get("format", {}).get("duration", 0))
    pixels = streams[0]["width"] * streams[0]["height"]
    if not 2 <= duration <= 15:
        raise RuntimeError(f"Reference duration is {duration:g}s; fal requires 2-15 seconds.")
    if pixels <= 0:
        raise RuntimeError("Reference video dimensions must be positive.")
    if video_model == "seedance" and not 640 * 640 <= pixels <= 834 * 1112:
        raise RuntimeError("Reference resolution is outside Seedance's supported pixel area. Resize it to 720p first.")
    return metadata


def reference_prompt(prompt: str, video_model: str = "seedance", duration: int = 5, image_to_ref2va: bool = False) -> str:
    if video_model != "seedance":
        prompt = prompt.replace("@Video1", "Video 1").replace("@Image1", "Image 1")
        if not prompt.startswith(H3_CLAY_CONTRACT):
            prompt = (
                f"{H3_CLAY_CONTRACT}\n\nScene description and physical constraints:\n{prompt}\n\n"
                f"Timeline: 0-{duration} seconds: follow the corresponding events in Video 1, "
                "including the initial and final states.\n"
                "Audio: follow any sound directions above; otherwise use natural ambience "
                "and sounds synchronized to the visible physical events."
            )
    else:
        prompt = (
            "Restyle @Video1 into a photorealistic video of the following scene. Preserve the reference's "
            "camera, object count, geometry, timing, motion, contacts, and causal sequence. Improve only "
            "appearance, materials, colors, and lighting; do not introduce cuts or new physical events.\n\n" + prompt
        )
    if image_to_ref2va and image_reference_instruction(video_model) not in prompt:
        prompt += "\n\n" + image_reference_instruction(video_model)
    validate_image_prompt(prompt, video_model, image_to_ref2va)
    return prompt


def arguments_for(
    prompt: str, args: argparse.Namespace, video_url: str | None = None, image_url: str | None = None
) -> dict[str, Any]:
    if args.image_to_ref2va != (image_url is not None):
        raise RuntimeError("The image URL must match --image-to-ref2va.")
    if args.video_model != "seedance":
        if video_url is None:
            raise RuntimeError("H3/H3-Max require a reference video in this runner; --direct uses Seedance.")
        payload = {
            "prompt": prompt,
            "duration": args.duration,
            "resolution": args.resolution.upper(),
            "aspect_ratio": args.aspect_ratio,
            "reference_video_urls": [video_url],
            "prompt_expansion_mode": "disabled",
        }
        if image_url is not None:
            payload["reference_image_urls"] = [image_url]
        return payload
    payload = {
        "prompt": prompt,
        "duration": str(args.duration),
        "resolution": args.resolution,
        "aspect_ratio": args.aspect_ratio,
        "generate_audio": args.audio,
    }
    if video_url is not None:
        payload["video_urls"] = [video_url]
    if image_url is not None:
        payload["image_urls"] = [image_url]
    return payload


def read_inputs(args: argparse.Namespace) -> tuple[Path, str, Path | None]:
    """Load folder inputs; ignore the image entirely when both routes are disabled."""
    if args.input_dir is None:
        raise RuntimeError("Provide --input-dir containing prompt.txt and an optional reference.png/.jpg/.jpeg/.webp.")
    folder = args.input_dir.expanduser().resolve()
    if not folder.is_dir():
        raise RuntimeError(f"Input folder does not exist: {folder}")
    prompt_path = folder / "prompt.txt"
    if args.proxy and (folder / "edit_prompt.txt").is_file():
        prompt_path = folder / "edit_prompt.txt"
    if not prompt_path.is_file():
        raise RuntimeError(f"Missing {prompt_path.name} in {folder}.")
    prompt = prompt_path.read_text(encoding="utf-8").strip()
    if not prompt:
        raise RuntimeError(f"{prompt_path.name} must contain a nonempty prompt.")
    if not (args.image_to_agent or args.image_to_ref2va):
        return folder, prompt, None
    images = sorted(path for path in folder.iterdir() if path.stem == "reference" and path.is_file())
    if len(images) != 1:
        raise RuntimeError("Image routing requires exactly one reference.png/.jpg/.jpeg/.webp in --input-dir.")
    reference = images[0]
    with reference.open("rb") as source:
        header = source.read(12)
    valid = {
        ".png": header.startswith(b"\x89PNG\r\n\x1a\n"),
        ".jpg": header.startswith(b"\xff\xd8\xff"),
        ".jpeg": header.startswith(b"\xff\xd8\xff"),
        ".webp": header.startswith(b"RIFF") and header[8:12] == b"WEBP",
    }
    if not valid.get(reference.suffix.lower(), False):
        raise RuntimeError("The reference image must be a nonempty PNG, JPEG or WebP with a matching extension.")
    if args.image_to_ref2va and args.video_model == "seedance" and reference.stat().st_size > 30_000_000:
        raise RuntimeError("Seedance reference images must not exceed 30 MB.")
    return folder, prompt, reference


def fal_client() -> tuple[SyncClient, ModuleType]:
    key = os.environ.get("FAL_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "FAL_KEY is blank. Set your fal.ai API key (see .env.example). "
            "Use --dry-run without a key, or --prepare-only to build only the physics draft."
        )
    try:
        module = importlib.import_module("fal_client")
    except ImportError as exc:
        raise RuntimeError(
            "Install the project dependencies with uv sync --locked, then use uv run scripts/generate_video.py."
        ) from exc
    return module.SyncClient(key=key), module


def download_video(url: str, output: Path) -> None:
    if urlparse(url).scheme != "https":
        raise RuntimeError("fal returned a video URL that is not HTTPS.")
    if output.exists():
        raise RuntimeError(f"Refusing to overwrite {output}. Choose a new --output path.")
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_name(output.name + ".part")
    try:
        # CDN download deliberately has no fal Authorization header.
        with urlopen(url, timeout=120) as response, partial.open("wb") as target:
            shutil.copyfileobj(response, target)
            expected = response.headers.get("Content-Length")
        if expected and partial.stat().st_size != int(expected):
            raise RuntimeError("Incomplete video download. Resume the saved request to download again.")
        with partial.open("rb") as source:
            if b"ftyp" not in source.read(32):
                raise RuntimeError("Downloaded result is not an MP4 container.")
        partial.replace(output)
    finally:
        partial.unlink(missing_ok=True)


def collect_result(client: SyncClient, module: ModuleType, record_path: Path, output: Path, timeout: int) -> None:
    record = json.loads(record_path.read_text(encoding="utf-8"))
    endpoint = record["endpoint"]
    if endpoint not in {TEXT_ENDPOINT, *(model.endpoint for model in VIDEO_MODELS.values())}:
        raise RuntimeError("Saved request is not a supported video endpoint.")
    print(f"fal request: {record['request_id']}", flush=True)
    print(f"Resume without submitting again: uv run scripts/generate_video.py --resume {record_path}", flush=True)
    if "result" not in record:
        deadline = time.monotonic() + timeout
        last_status = None
        while True:
            status = client.status(endpoint, record["request_id"], with_logs=True)
            label = type(status).__name__
            if label != last_status:
                print(f"fal: {label}", flush=True)
                last_status = label
            if isinstance(status, module.Completed):
                break
            if time.monotonic() >= deadline:
                raise RuntimeError("Timed out waiting for fal. The remote job is still active; use --resume.")
            time.sleep(min(5, max(0, deadline - time.monotonic())))
        record["result"] = client.result(endpoint, record["request_id"])
        write_json(record_path, record)
    url = record["result"].get("video", {}).get("url")
    if not url:
        raise RuntimeError("fal returned no video.url. Inspect the result in fal_request.json.")
    download_video(url, output)
    record["saved_video"] = str(output)
    write_json(record_path, record)
    print(f"Saved video: {output}")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    result.add_argument(
        "--input-dir",
        type=Path,
        help="Folder with prompt.txt and optional reference.png/.jpg/.jpeg/.webp. With --proxy, prefer edit_prompt.txt.",
    )
    result.add_argument(
        "--image-to-agent", action="store_true", help="Attach the folder's reference image to the physics agent (default: off)."
    )
    result.add_argument(
        "--image-to-ref2va",
        action="store_true",
        help="Include the folder's reference image in the final fal request (default: off).",
    )
    mode = result.add_mutually_exclusive_group()
    mode.add_argument("--direct", action="store_true", help="Seedance text-to-video; skip the agent and Blender.")
    mode.add_argument("--proxy", type=Path, help="Restyle an existing local proxy; skip the agent/Blender.")
    mode.add_argument("--resume", type=Path, help="Collect an existing fal_request.json; never resubmit.")
    mode.add_argument("--login", action="store_true", help="Log in to the selected agent's isolated auth store.")
    result.add_argument("-o", "--output", type=Path, help="MP4 path (default: outputs/video.mp4).")
    result.add_argument(
        "--video-model", choices=tuple(VIDEO_MODELS), help="Video backend (default: h3-max; --direct defaults to seedance)."
    )
    result.add_argument("--duration", type=int, choices=range(4, 16), default=5)
    result.add_argument(
        "--resolution",
        type=str.lower,
        choices=("480p", "720p", "768p", "1080p", "2k", "4k"),
        help="Output resolution (default: 768p for H3/H3-Max, 720p for Seedance); validated per model.",
    )
    result.add_argument("--aspect-ratio", choices=tuple(PROXY_SIZES), default="16:9")
    result.add_argument(
        "--audio",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Generate audio (default: on); --no-audio is supported only by Seedance.",
    )
    result.add_argument("--timeout", type=int, default=1800, help="Seconds to wait for fal (default: 1800).")
    result.add_argument("--dry-run", action="store_true", help="Print the plan; no calls, credentials or writes.")
    result.add_argument("--prepare-only", action="store_true", help="Build/audit the draft; do not call fal.")
    result.add_argument("--agent", choices=("codex", "pi"), default="codex", help="Physics draft harness (default: codex).")
    result.add_argument("--codex", default="codex", help="Codex CLI executable.")
    result.add_argument("--pi", default="pi", help="Pi CLI executable (uses ChatGPT subscription authentication).")
    result.add_argument("--blender", default="blender", help="Blender executable.")
    result.add_argument("--ffmpeg", default="ffmpeg", help="FFmpeg executable.")
    result.add_argument("--ffprobe", default="ffprobe", help="ffprobe executable (ships with FFmpeg).")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    cli = parser()
    args = cli.parse_args(argv)
    if args.timeout <= 0:
        cli.error("--timeout must be positive")
    if args.prepare_only and (args.direct or args.proxy or args.resume or args.login):
        cli.error("--prepare-only is for the physics agent/Blender pipeline")
    if args.input_dir is not None and (args.login or args.resume):
        cli.error("--input-dir does not apply to --login or --resume")
    if args.image_to_agent or args.image_to_ref2va:
        if args.direct or args.login or args.resume:
            cli.error("image routing requires the physics pipeline or --proxy, not --direct, --login or --resume")
        if args.image_to_agent and args.proxy:
            cli.error("--image-to-agent cannot be used with --proxy because no agent runs")
        if args.image_to_ref2va and not args.image_to_agent:
            print(
                "Warning: --image-to-ref2va is enabled without --image-to-agent (mode 3). "
                "The agent will not see the image in this run; it may conflict with the clay draft.",
                file=sys.stderr,
            )
    if args.login:
        if args.dry_run:
            print(f"Would log in to a dedicated {args.agent} auth store: {PI_STATE if args.agent == 'pi' else CODEX_STATE}")
        elif args.agent == "pi":
            pi_login(executable(args.pi))
        else:
            login(executable(args.codex))
        return 0
    if args.resume:
        record_path = args.resume.expanduser().resolve()
        record = json.loads(record_path.read_text(encoding="utf-8"))
        output = (args.output or Path(record["output"])).expanduser().resolve()
        if args.dry_run:
            print(json.dumps({"resume": str(record_path), "output": str(output)}, indent=2))
            return 0
        if output.exists():
            raise RuntimeError(f"Output exists: {output}. Choose another --output path.")
        client, module = fal_client()
        collect_result(client, module, record_path, output, args.timeout)
        return 0
    args.video_model = args.video_model or ("seedance" if args.direct else "h3-max")
    model = VIDEO_MODELS[args.video_model]
    args.resolution = args.resolution or model.default_resolution
    if args.direct and args.video_model != "seedance":
        cli.error("--direct supports only --video-model seedance; H3/H3-Max use the physics pipeline or --proxy")
    if args.duration < model.minimum_duration:
        cli.error(f"{model.label} output duration must be {model.minimum_duration}-15 seconds")
    if args.resolution not in model.resolutions:
        cli.error(f"{model.label} supports these output resolutions: {', '.join(model.resolutions)}")
    if not args.audio and args.video_model != "seedance":
        cli.error("H3/H3-Max generate native audio and expose no audio-off switch; --no-audio requires --video-model seedance")
    input_dir, prompt, reference_image = read_inputs(args)
    output = (args.output or Path("outputs/video.mp4")).expanduser().resolve()
    if output.suffix.lower() != ".mp4":
        cli.error("--output must end in .mp4")
    run_dir = output.with_suffix(".run")
    proxy = args.proxy.expanduser().resolve() if args.proxy else None
    endpoint = TEXT_ENDPOINT if args.direct else model.endpoint
    if args.dry_run:
        print(
            json.dumps(
                {
                    "mode": "direct" if args.direct else "reference" if proxy else "physics",
                    "video_model": args.video_model,
                    "endpoint": endpoint,
                    "output": str(output),
                    "artifacts": str(run_dir),
                    "input_dir": str(input_dir),
                    "reference_image": str(reference_image) if reference_image else None,
                    "image_to_agent": args.image_to_agent,
                    "image_to_ref2va": args.image_to_ref2va,
                    "input": arguments_for(
                        reference_prompt(prompt, args.video_model, args.duration, args.image_to_ref2va)
                        if not args.direct
                        else prompt,
                        args,
                        "<uploaded proxy URL>" if not args.direct else None,
                        "<uploaded reference image URL>" if args.image_to_ref2va else None,
                    ),
                    "agent": None
                    if args.direct or proxy
                    else {
                        "harness": args.agent,
                        "provider": PI_PROVIDER if args.agent == "pi" else "openai",
                        "model": MODEL,
                        "service_tier": "fast",
                        "reasoning": "xhigh",
                        "memories": False,
                        "auth_directory": str(PI_STATE if args.agent == "pi" else CODEX_STATE),
                        "sandbox": "none (normal local permissions)" if args.agent == "pi" else "workspace-write",
                        "skills": list(SKILLS),
                        "note": "The final fal prompt will be the audited draft's edit_prompt.txt.",
                    },
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0
    if output.exists() or run_dir.exists():
        raise RuntimeError(
            f"Output or artifacts already exist: {output}, {run_dir}. "
            "Choose another --output, reuse --proxy, or --resume the saved fal_request.json."
        )
    # Check cheap prerequisites before launching the agent or uploading anything.
    client, module = (None, None) if args.prepare_only else fal_client()
    if not args.direct:
        ffprobe = executable(args.ffprobe)
        if proxy:
            validate_proxy(proxy, ffprobe, args.video_model)
        else:
            agent, blender, ffmpeg = map(executable, (args.pi if args.agent == "pi" else args.codex, args.blender, args.ffmpeg))
            if args.agent == "pi":
                check_pi(agent)
            else:
                check_codex(agent)
    run_dir.mkdir(parents=True)
    (run_dir / "prompt.txt").write_text(prompt + "\n", encoding="utf-8")
    if reference_image is not None:
        saved_image = run_dir / ("reference" + reference_image.suffix.lower())
        shutil.copy2(reference_image, saved_image)
        reference_image = saved_image
    write_json(
        run_dir / "input.json",
        {
            "prompt": prompt,
            "input_dir": str(input_dir),
            "reference_image": str(reference_image) if reference_image else None,
            "image_to_agent": args.image_to_agent,
            "image_to_ref2va": args.image_to_ref2va,
            "duration": args.duration,
            "resolution": args.resolution,
            "aspect_ratio": args.aspect_ratio,
            "audio": args.audio,
            "endpoint": endpoint,
            "video_model": args.video_model,
            "proxy": str(proxy) if proxy else None,
            "agent": None if args.direct or proxy else args.agent,
            "model": None if args.direct or proxy else MODEL,
        },
    )
    if not args.direct and not proxy:
        proxy, prompt = create_draft(
            prompt,
            args,
            run_dir,
            agent,
            blender,
            ffmpeg,
            ffprobe,
            reference_image if args.image_to_agent else None,
        )
    elif proxy:
        prompt = reference_prompt(prompt, args.video_model, args.duration, args.image_to_ref2va)
        (run_dir / "edit_prompt.txt").write_text(prompt + "\n", encoding="utf-8")
    if not args.direct:
        validate_image_prompt(prompt, args.video_model, args.image_to_ref2va)
    if args.prepare_only:
        print(f"Audited physics draft: {proxy}\nEdit prompt: {run_dir / 'edit_prompt.txt'}")
        return 0
    assert client is not None and module is not None
    video_url = client.upload_file(proxy) if proxy else None
    image_url = client.upload_file(reference_image) if args.image_to_ref2va and reference_image else None
    payload = arguments_for(prompt, args, video_url, image_url)
    write_json(run_dir / "fal_input.json", payload)
    print(f"Submitting to {endpoint}", flush=True)
    try:
        handle = client.submit(endpoint, arguments=payload)
    except Exception as exc:
        raise RuntimeError(
            f"fal submission failed ({exc}); the server may have accepted it. "
            "Check the fal dashboard before retrying to avoid a duplicate charge."
        ) from exc
    record_path = run_dir / "fal_request.json"
    print(f"Submitted fal request ID: {handle.request_id}", flush=True)
    write_json(record_path, {"endpoint": endpoint, "request_id": handle.request_id, "output": str(output), "input": payload})
    collect_result(client, module, record_path, output, args.timeout)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print(
            "\nInterrupted. If fal_request.json exists, use --resume; a submitted fal job continues remotely.", file=sys.stderr
        )
        raise SystemExit(130) from None
    except Exception as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1) from None
