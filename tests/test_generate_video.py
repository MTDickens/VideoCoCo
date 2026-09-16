"""Offline orchestration tests; no model calls, credentials, or fal charges."""

import base64
import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

from scripts import generate_video as runner

MP4 = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 32
H3_PROMPT = "Video 1 is an untextured clay render. Render its melting ice cube with realistic materials."
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNoaGgAAAMEAYFL09IQAAAAAElFTkSuQmCC")


class Completed:
    pass


class Queued:
    pass


class FalModule(ModuleType):
    Completed = Completed


class Response(io.BytesIO):
    def __init__(self, data=MP4, size=None):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data) if size is None else size)}


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / "video.mp4"
        self.artifacts = self.output.with_suffix(".run")
        self.client = Mock()
        self.client.submit.return_value = SimpleNamespace(request_id="test-request")
        self.client.status.return_value = Completed()
        self.client.result.return_value = {"video": {"url": "https://cdn.example/video.mp4"}, "seed": 42}
        self.client.upload_file.return_value = "https://cdn.example/proxy.mp4"
        self.module = FalModule("fal_client_stub")
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
        self.stack.enter_context(patch.dict(os.environ, {}, clear=True))

    def api(self):
        self.stack.enter_context(patch.object(runner, "fal_client", return_value=(self.client, self.module)))
        self.stack.enter_context(patch.object(runner, "urlopen", side_effect=lambda *a, **kw: Response()))

    def inputs(self, prompt: str = "ice melts") -> list[str]:
        folder = self.root / "input"
        folder.mkdir(exist_ok=True)
        (folder / "prompt.txt").write_text(prompt, encoding="utf-8")
        return ["--input-dir", str(folder)]

    @contextlib.contextmanager
    def image_draft(self, agent: str, model: str, image_to_agent: bool, image_to_ref2va: bool):
        def fake_exec(command: list[str], **kwargs):
            workspace = Path(kwargs["cwd"])
            image = workspace / "reference.png"
            self.assertEqual(image.exists(), image_to_agent)
            self.assertEqual("A reference image is attached." in kwargs["input"], image_to_agent)
            self.assertNotIn(str(self.root / "input"), kwargs["input"])
            if agent == "codex":
                self.assertEqual("--image" in command, image_to_agent)
                if image_to_agent:
                    self.assertEqual(command[command.index("--image") + 1], str(image))
                    self.assertLess(command.index("--image"), command.index("-c"))
                self.draft_files(workspace)
            else:
                self.assertEqual(f"@{image}" in command, image_to_agent)
                kwargs["stdout"].write(self.pi_events(workspace))
            if image_to_agent:
                self.assertEqual(image.read_bytes(), PNG)
            if image_to_agent and not image_to_ref2va:
                self.assertIn("video model will not receive the image", kwargs["input"])
            if image_to_ref2va and not image_to_agent:
                self.assertIn("without inventing visual details", kwargs["input"])
            edit = H3_PROMPT if model != "seedance" else "Restyle @Video1 as photorealistic melting ice."
            if image_to_ref2va:
                edit += "\n" + runner.image_reference_instruction(model)
            (workspace / "edit_prompt.txt").write_text(edit)
            return subprocess.CompletedProcess(command, 0)

        with (
            patch.object(runner, "CODEX_STATE", self.root / "codex-auth"),
            patch.object(runner, "PI_STATE", self.root / "pi-auth"),
            patch.object(runner, "check_codex"),
            patch.object(runner, "check_pi"),
            patch.object(runner, "executable", side_effect=lambda value: value),
            patch.object(runner, "isolate_skill_context", return_value="skills.config=[]"),
            patch.object(runner.subprocess, "run", side_effect=fake_exec),
            patch.object(
                runner,
                "validate_proxy",
                return_value={"streams": [{"width": 1280, "height": 720}], "format": {"duration": "5"}},
            ),
        ):
            yield

    def test_all_four_image_modes_for_both_agents_and_each_video_backend(self) -> None:
        self.api()
        inputs = self.inputs()
        (self.root / "input/reference.png").write_bytes(PNG)
        self.client.upload_file.side_effect = lambda path: f"https://cdn.example/{path.name}"
        for agent in ("codex", "pi"):
            for model in runner.VIDEO_MODELS:
                for to_agent, to_video in ((True, False), (True, True), (False, True), (False, False)):
                    output = self.root / f"{agent}-{model}-{to_agent}-{to_video}.mp4"
                    flags = (["--image-to-agent"] if to_agent else []) + (["--image-to-ref2va"] if to_video else [])
                    stderr = io.StringIO()
                    self.client.upload_file.reset_mock()
                    with (
                        self.subTest(agent=agent, model=model, to_agent=to_agent, to_video=to_video),
                        contextlib.redirect_stderr(stderr),
                        self.image_draft(agent, model, to_agent, to_video),
                    ):
                        runner.main([*inputs, "--agent", agent, "--video-model", model, *flags, "-o", str(output)])
                        payload = self.client.submit.call_args.kwargs["arguments"]
                        image_field = "image_urls" if model == "seedance" else "reference_image_urls"
                        self.assertEqual(image_field in payload, to_video)
                        other_field = "reference_image_urls" if model == "seedance" else "image_urls"
                        self.assertNotIn(other_field, payload)
                        if to_video:
                            self.assertEqual(payload[image_field], ["https://cdn.example/reference.png"])
                        self.assertEqual(self.client.upload_file.call_count, 2 if to_video else 1)
                        self.assertEqual("Warning:" in stderr.getvalue(), to_video and not to_agent)
                        artifacts = output.with_suffix(".run")
                        record = json.loads((artifacts / "input.json").read_text())
                        self.assertEqual(record["image_to_agent"], to_agent)
                        self.assertEqual(record["image_to_ref2va"], to_video)
                        self.assertEqual((artifacts / "reference.png").exists(), to_agent or to_video)
                        if to_agent or to_video:
                            self.assertEqual((artifacts / "reference.png").read_bytes(), PNG)
                        self.assertEqual(output.read_bytes(), MP4)

    def test_prepare_images_then_generate_from_saved_folder_without_agent(self) -> None:
        inputs = self.inputs()
        (self.root / "input/reference.png").write_bytes(PNG)
        with (
            self.image_draft("codex", "h3-max", True, True),
            patch.object(runner, "fal_client", side_effect=AssertionError("No fal during preparation")),
        ):
            runner.main([*inputs, "--image-to-agent", "--image-to-ref2va", "--prepare-only", "-o", str(self.output)])
        self.assertFalse(self.output.exists())
        self.assertEqual((self.artifacts / "reference.png").read_bytes(), PNG)
        self.assertEqual((self.artifacts / "prompt.txt").read_text().strip(), "ice melts")
        # Prepared folders include preview.png too; only reference.* is an input.
        self.api()
        self.client.upload_file.side_effect = lambda path: f"https://cdn.example/{path.name}"
        output = self.root / "finished.mp4"
        with (
            patch.object(runner, "executable", return_value="ffprobe"),
            patch.object(runner, "validate_proxy"),
            patch.object(runner, "create_draft", side_effect=AssertionError("No agent on proxy reuse")),
        ):
            runner.main(
                [
                    "--input-dir",
                    str(self.artifacts),
                    "--proxy",
                    str(self.artifacts / "proxy.mp4"),
                    "--image-to-ref2va",
                    "-o",
                    str(output),
                ]
            )
        payload = self.client.submit.call_args.kwargs["arguments"]
        self.assertIn(H3_PROMPT, payload["prompt"])
        self.assertEqual(payload["reference_image_urls"], ["https://cdn.example/reference.png"])
        self.assertEqual(payload["reference_video_urls"], ["https://cdn.example/proxy.mp4"])
        self.assertEqual(payload["prompt"].count(runner.image_reference_instruction("h3-max")), 1)

    def test_image_routing_dry_run_has_no_side_effects(self) -> None:
        inputs = self.inputs()
        (self.root / "input/reference.png").write_bytes(PNG)
        with (
            patch.object(runner, "fal_client", side_effect=AssertionError("No fal")),
            patch.object(runner, "executable", side_effect=AssertionError("No tools")),
        ):
            for flags in ([], ["--image-to-agent"], ["--image-to-ref2va"], ["--image-to-agent", "--image-to-ref2va"]):
                stream = io.StringIO()
                with self.subTest(flags=flags), contextlib.redirect_stdout(stream):
                    runner.main([*inputs, *flags, "--dry-run", "-o", str(self.output)])
                record = json.loads(stream.getvalue())
                self.assertEqual(record["image_to_agent"], "--image-to-agent" in flags)
                self.assertEqual("reference_image_urls" in record["input"], "--image-to-ref2va" in flags)
        self.assertEqual(list(self.root.iterdir()), [self.root / "input"])

    def test_folder_validation_and_disabled_images(self) -> None:
        with patch.object(runner, "fal_client", side_effect=AssertionError("No fal")):
            with self.assertRaisesRegex(RuntimeError, "--input-dir"):
                runner.main(["--dry-run"])
            with self.assertRaisesRegex(RuntimeError, "does not exist"):
                runner.main(["--input-dir", str(self.root / "absent"), "--dry-run"])
            inputs = self.inputs("")
            with self.assertRaisesRegex(RuntimeError, "nonempty"):
                runner.main([*inputs, "--dry-run"])
            (self.root / "input/prompt.txt").unlink()
            with self.assertRaisesRegex(RuntimeError, "Missing prompt.txt"):
                runner.main([*inputs, "--dry-run"])
            inputs = self.inputs()
            with self.assertRaisesRegex(RuntimeError, "exactly one"):
                runner.main([*inputs, "--image-to-agent", "--dry-run"])
            image = self.root / "input/reference.png"
            image.write_text("invalid image")
            self.assertEqual(runner.main([*inputs, "--dry-run"]), 0)  # Mode 4 ignores it.
            with self.assertRaisesRegex(RuntimeError, "nonempty PNG"):
                runner.main([*inputs, "--image-to-agent", "--dry-run"])
            image.write_bytes(PNG)
            (self.root / "input/reference.jpg").write_bytes(b"\xff\xd8\xfffixture")
            with self.assertRaisesRegex(RuntimeError, "exactly one"):
                runner.main([*inputs, "--image-to-ref2va", "--dry-run"])
        self.assertFalse(self.artifacts.exists())

    def test_conflicting_image_options_and_removed_prompt_flags(self) -> None:
        with (
            patch.object(runner, "fal_client", side_effect=AssertionError("No fal")),
            patch.object(runner, "executable", side_effect=AssertionError("No tools")),
        ):
            for flags in (
                ["--direct", "--image-to-agent"],
                ["--direct", "--image-to-ref2va"],
                ["--login", "--image-to-agent"],
                ["--resume", "job.json", "--image-to-ref2va"],
                ["--proxy", "proxy.mp4", "--image-to-agent"],
                ["--login", "--input-dir", "inputs"],
                ["--resume", "job.json", "--input-dir", "inputs"],
                ["--prompt", "obsolete"],
                ["--prompt-file", "obsolete.txt"],
            ):
                with self.subTest(flags=flags), self.assertRaises(SystemExit) as error:
                    runner.main(flags)
                self.assertEqual(error.exception.code, 2)

    def test_reused_prompt_cannot_reference_an_omitted_image(self) -> None:
        self.api()
        for model in runner.VIDEO_MODELS:
            inputs = self.inputs("Use Image 1 for the ice and Video 1 for its melting motion.")
            output = self.root / f"{model}.mp4"
            with (
                self.subTest(model=model),
                patch.object(runner, "executable", return_value="ffprobe"),
                patch.object(runner, "validate_proxy"),
                self.assertRaisesRegex(RuntimeError, "--image-to-ref2va is off"),
            ):
                runner.main([*inputs, "--video-model", model, "--proxy", "proxy.mp4", "-o", str(output)])
        self.client.upload_file.assert_not_called()
        self.client.submit.assert_not_called()

    def test_draft_prompt_requires_correct_image_reference(self) -> None:
        self.draft_files(self.root)
        for model in runner.VIDEO_MODELS:
            video_prompt = H3_PROMPT if model != "seedance" else "Restyle @Video1."
            with self.subTest(model=model):
                for ending in ("", " Use Image 10."):
                    (self.root / "edit_prompt.txt").write_text(video_prompt + ending)
                    with self.assertRaisesRegex(RuntimeError, "supplied image"):
                        runner.validate_draft(self.root, 120, model, True)
                prompt = video_prompt + runner.image_reference_instruction(model)
                (self.root / "edit_prompt.txt").write_text(prompt)
                self.assertEqual(runner.validate_draft(self.root, 120, model, True), prompt)
                with self.assertRaisesRegex(RuntimeError, "--image-to-ref2va is off"):
                    runner.validate_draft(self.root, 120, model, False)

    def record(self, cached=False):
        path = self.root / "fal_request.json"
        data = {"endpoint": runner.TEXT_ENDPOINT, "request_id": "existing-job", "output": str(self.output)}
        if cached:
            data["result"] = self.client.result.return_value
        runner.write_json(path, data)
        return path

    def draft_files(self, workspace, status="pass"):
        for name in ("scene.blender.py", "preview.png"):
            (workspace / name).write_text("test artifact")
        (workspace / "proxy.mp4").write_bytes(MP4)
        (workspace / "edit_prompt.txt").write_text(H3_PROMPT)
        runner.write_json(
            workspace / "physical_plan.json",
            {
                "semantic_keyframes": [{"id": f"K{i}"} for i in range(4)],
            },
        )
        runner.write_json(
            workspace / "audit.json",
            {
                "status": "passed",
                "summary": "All requested states inspected.",
                "known_limitations": ["Offline fixture, not a physical simulation."],
                "checks": [{"status": status, "check": "timing", "evidence": "frames"}],
                "keyframe_frame_map": [{"keyframe": f"K{i}", "frame": frame} for i, frame in enumerate((1, 30, 60, 120))],
            },
        )

    def test_direct_cli_submits_text_and_saves_mp4_without_codex(self):
        self.api()
        with (
            patch.object(runner, "create_draft", side_effect=AssertionError("Codex must not run")),
            patch.object(runner, "executable", side_effect=AssertionError("No media tools required")),
        ):
            self.assertEqual(runner.main(["--direct", *self.inputs("ice melts"), "--no-audio", "-o", str(self.output)]), 0)
        endpoint = self.client.submit.call_args.args[0]
        payload = self.client.submit.call_args.kwargs["arguments"]
        self.assertEqual(endpoint, "bytedance/seedance-2.0/text-to-video")
        self.assertEqual(
            payload,
            {"prompt": "ice melts", "duration": "5", "resolution": "720p", "aspect_ratio": "16:9", "generate_audio": False},
        )
        self.client.upload_file.assert_not_called()
        self.assertEqual(self.output.read_bytes(), MP4)
        saved = json.loads((self.artifacts / "fal_request.json").read_text())
        self.assertEqual(saved["request_id"], "test-request")
        self.assertEqual(saved["saved_video"], str(self.output.resolve()))

    def test_reference_cli_uploads_proxy_and_mentions_video(self):
        self.api()
        proxy = self.root / "proxy.mp4"
        proxy.write_bytes(MP4)
        with (
            patch.object(runner, "validate_proxy") as validate,
            patch.object(runner, "executable", return_value="ffprobe"),
            patch.object(runner, "create_draft", side_effect=AssertionError("No Codex")),
        ):
            runner.main(["--video-model", "seedance", "--proxy", str(proxy), *self.inputs("gold ring"), "-o", str(self.output)])
        validate.assert_called_once()
        self.client.upload_file.assert_called_once_with(proxy.resolve())
        self.assertEqual(self.client.submit.call_args.args[0], runner.REFERENCE_ENDPOINT)
        payload = self.client.submit.call_args.kwargs["arguments"]
        self.assertIn("@Video1", payload["prompt"])
        self.assertEqual(payload["video_urls"], ["https://cdn.example/proxy.mp4"])

    def test_default_cli_renders_audits_then_uploads(self):
        self.api()

        def fake_exec(command, **kwargs):
            workspace = Path(kwargs["cwd"])
            self.assertEqual(command[1], "exec")
            self.assertIn("--ephemeral", command)
            self.assertIn('model="gpt-6-astra"', command)
            self.assertIn('service_tier="fast"', command)
            self.assertIn('model_reasoning_effort="xhigh"', command)
            self.assertNotEqual(kwargs["env"]["CODEX_HOME"], str(runner.CODEX_STATE))
            self.assertTrue((workspace / "skill/physical-state-planner/SKILL.md").is_file())
            self.draft_files(workspace)
            return subprocess.CompletedProcess(command, 0)

        with (
            patch.object(runner, "CODEX_STATE", self.root / "auth"),
            patch.object(runner, "check_codex"),
            patch.object(runner, "executable", side_effect=lambda x: x),
            patch.object(runner, "isolate_skill_context", return_value="skills.config=[]"),
            patch.object(runner.subprocess, "run", side_effect=fake_exec),
            patch.object(
                runner,
                "validate_proxy",
                return_value={"streams": [{"width": 1280, "height": 720}], "format": {"duration": "5"}},
            ),
        ):
            runner.main([*self.inputs("ice melts"), "-o", str(self.output)])
        self.assertTrue((self.artifacts / "audit.json").is_file())
        self.assertEqual(self.client.submit.call_args.args[0], "minimax/h3-max/reference-to-video")
        self.assertEqual(self.client.submit.call_args.kwargs["arguments"]["prompt"], H3_PROMPT)
        self.assertEqual(self.output.read_bytes(), MP4)

    def test_failed_audit_preserves_artifacts_and_never_submits(self):
        self.api()

        def fake_exec(command, **kwargs):
            self.draft_files(Path(kwargs["cwd"]), status="uncertain")

        with (
            patch.object(runner, "CODEX_STATE", self.root / "auth"),
            patch.object(runner, "check_codex"),
            patch.object(runner, "executable", side_effect=lambda x: x),
            patch.object(runner, "isolate_skill_context", return_value="skills.config=[]"),
            patch.object(runner.subprocess, "run", side_effect=fake_exec),
        ):
            with self.assertRaisesRegex(RuntimeError, "did not pass"):
                runner.main([*self.inputs("ice melts"), "-o", str(self.output)])
        self.client.submit.assert_not_called()
        self.client.upload_file.assert_not_called()
        self.assertTrue((self.artifacts / "audit.json").is_file())

    def test_dry_run_needs_no_key_or_tools_and_writes_nothing(self):
        with (
            patch.object(runner, "fal_client", side_effect=AssertionError("No calls")),
            patch.object(runner, "executable", side_effect=AssertionError("No tools")),
        ):
            for mode in ([], ["--agent", "pi"], ["--direct"], ["--agent", "pi", "--direct"]):
                self.assertEqual(runner.main(mode + [*self.inputs("a ball"), "--dry-run", "-o", str(self.output)]), 0)
        self.assertEqual(list(self.root.iterdir()), [self.root / "input"])

    def test_blank_key_fails_before_creating_artifacts(self):
        with self.assertRaisesRegex(RuntimeError, "FAL_KEY is blank"):
            runner.main([*self.inputs("a ball"), "-o", str(self.output)])
        self.assertEqual(list(self.root.iterdir()), [self.root / "input"])

    def test_prepare_only_does_not_need_fal(self):
        with (
            patch.object(runner, "fal_client", side_effect=AssertionError("No fal")),
            patch.object(runner, "check_codex"),
            patch.object(runner, "executable", side_effect=lambda x: x),
            patch.object(runner, "create_draft", return_value=(self.artifacts / "proxy.mp4", "edit")),
        ):
            runner.main(["--prepare-only", *self.inputs("a ball"), "-o", str(self.output)])
        self.assertFalse(self.output.exists())

    def test_resume_existing_request_never_submits(self):
        self.api()
        record = self.record()
        runner.main(["--resume", str(record)])
        self.client.submit.assert_not_called()
        self.client.upload_file.assert_not_called()
        self.client.result.assert_called_once_with(runner.TEXT_ENDPOINT, "existing-job")
        self.assertTrue(self.output.is_file())

    def test_resume_cached_result_does_not_poll(self):
        self.api()
        record = self.record(cached=True)
        runner.main(["--resume", str(record)])
        self.client.status.assert_not_called()
        self.client.result.assert_not_called()
        self.client.submit.assert_not_called()

    def test_queue_timeout_preserves_job_for_resume(self):
        record = self.record()
        self.client.status.return_value = Queued()
        with patch.object(runner.time, "monotonic", side_effect=[0, 2]):
            with self.assertRaisesRegex(RuntimeError, "remote job is still active"):
                runner.collect_result(self.client, self.module, record, self.output, timeout=1)
        self.assertEqual(json.loads(record.read_text())["request_id"], "existing-job")
        self.client.cancel.assert_not_called()
        self.client.submit.assert_not_called()

    def test_failed_download_keeps_completed_result(self):
        record = self.record()
        with patch.object(runner, "urlopen", return_value=Response(b"not a video")):
            with self.assertRaisesRegex(RuntimeError, "not an MP4"):
                runner.collect_result(self.client, self.module, record, self.output, timeout=10)
        self.assertIn("result", json.loads(record.read_text()))
        self.assertFalse(self.output.exists())
        self.assertFalse(self.output.with_suffix(".mp4.part").exists())

    def test_incomplete_download_is_not_saved(self):
        with patch.object(runner, "urlopen", return_value=Response(size=10000)):
            with self.assertRaisesRegex(RuntimeError, "Incomplete"):
                runner.download_video("https://cdn.example/video.mp4", self.output)
        self.assertFalse(self.output.exists())

    def test_existing_output_is_not_overwritten_or_billed(self):
        self.output.write_bytes(b"existing")
        with patch.object(runner, "fal_client", side_effect=AssertionError("No fal")):
            with self.assertRaisesRegex(RuntimeError, "already exist"):
                runner.main(["--direct", *self.inputs("a ball"), "-o", str(self.output)])
        self.assertEqual(self.output.read_bytes(), b"existing")

    def test_child_environment_removes_personal_overrides_and_fal_key(self):
        with patch.dict(
            os.environ,
            {
                "FAL_KEY": "secret",
                "CODEX_HOME": "/personal",
                "CODEX_THREAD_ID": "old",
                "OPENAI_BASE_URL": "https://other.example",
                "HOME": "/user",
                "CODEX_API_KEY": "explicit-key",
                "PATH": "/bin",
            },
        ):
            env = runner.codex_environment(self.root / "runtime")
        self.assertEqual(env["CODEX_HOME"], str(self.root / "runtime"))
        self.assertEqual(env["HOME"], "/user")
        self.assertEqual(env["CODEX_API_KEY"], "explicit-key")
        for name in ("FAL_KEY", "OPENAI_BASE_URL", "CODEX_THREAD_ID"):
            self.assertNotIn(name, env)

    def test_isolation_fails_closed_when_cli_still_injects_skills(self):
        responses = [
            subprocess.CompletedProcess([], 0, stdout="", stderr=""),
            subprocess.CompletedProcess([], 0, stdout="<skills_instructions>personal</skills_instructions>", stderr=""),
        ]
        with patch.object(runner.subprocess, "run", side_effect=responses):
            with self.assertRaisesRegex(RuntimeError, "Isolation check failed"):
                runner.isolate_skill_context("codex", self.root, self.root / "runtime")

    def test_video_limits_checked_before_upload(self):
        proxy = self.root / "proxy.mp4"
        proxy.write_bytes(MP4)
        metadata = {"streams": [{"width": 1280, "height": 720}], "format": {"duration": "16"}}
        with patch.object(runner.subprocess, "check_output", return_value=json.dumps(metadata)):
            with self.assertRaisesRegex(RuntimeError, "2-15 seconds"):
                runner.validate_proxy(proxy, "ffprobe")
        metadata["format"]["duration"] = "5"
        with patch.object(runner.subprocess, "check_output", return_value=json.dumps(metadata)):
            self.assertEqual(runner.validate_proxy(proxy, "ffprobe"), metadata)

    def test_draft_audit_must_cover_final_frame(self):
        self.draft_files(self.root)
        with self.assertRaisesRegex(RuntimeError, "final frame"):
            runner.validate_draft(self.root, frame_count=240)

    def test_h3_backends_upload_clay_with_integer_duration_and_native_resolution(self) -> None:
        self.api()
        proxy = self.root / "clay.mp4"
        proxy.write_bytes(MP4)
        for model, resolution in (("h3-max", "1080P"), ("h3", "2K")):
            with (
                self.subTest(model=model),
                patch.object(runner, "validate_proxy"),
                patch.object(runner, "executable", return_value="ffprobe"),
            ):
                output = self.root / f"{model}.mp4"
                runner.main(
                    [
                        "--video-model",
                        model,
                        "--proxy",
                        str(proxy),
                        *self.inputs("Restyle @Video1: gold ring"),
                        "--duration",
                        "8",
                        "--resolution",
                        resolution,
                        "-o",
                        str(output),
                    ]
                )
                self.assertEqual(self.client.submit.call_args.args[0], f"minimax/{model}/reference-to-video")
                payload = self.client.submit.call_args.kwargs["arguments"]
                self.assertEqual(payload["reference_video_urls"], ["https://cdn.example/proxy.mp4"])
                self.assertEqual(payload["duration"], 8)
                self.assertEqual(payload["resolution"], resolution)
                self.assertEqual(payload["prompt_expansion_mode"], "disabled")
                self.assertNotIn("generate_audio", payload)
                self.assertNotIn("video_urls", payload)
                self.assertNotIn("@Video1", payload["prompt"])
                self.assertIn("untextured clay", payload["prompt"])
                self.assertIn("gold ring", payload["prompt"])
                self.assertEqual(output.read_bytes(), MP4)
                self.assertEqual((output.with_suffix(".run") / "edit_prompt.txt").read_text().strip(), payload["prompt"])

    def test_invalid_model_options_fail_before_keys_tools_or_writes(self) -> None:
        with (
            patch.object(runner, "fal_client", side_effect=AssertionError("No API")),
            patch.object(runner, "executable", side_effect=AssertionError("No tools")),
        ):
            for options in (
                ["--video-model", "h3", "--duration", "4"],
                ["--video-model", "h3-max", "--resolution", "720p"],
                ["--video-model", "h3", "--resolution", "1080p"],
                ["--video-model", "seedance", "--resolution", "768p"],
                ["--video-model", "h3-max", "--no-audio"],
                ["--video-model", "h3", "--direct"],
            ):
                with self.subTest(options=options), self.assertRaises(SystemExit) as error:
                    runner.main([*self.inputs("a ball"), "-o", str(self.output), *options])
                self.assertEqual(error.exception.code, 2)
        self.assertFalse(self.artifacts.exists())

    def test_h3_resume_uses_saved_backend_without_resubmitting(self) -> None:
        self.api()
        for model in ("h3-max", "h3"):
            with self.subTest(model=model):
                output = self.root / f"{model}.mp4"
                record = self.root / f"{model}.json"
                runner.write_json(
                    record,
                    {
                        "endpoint": f"minimax/{model}/reference-to-video",
                        "request_id": "existing-job",
                        "output": str(output),
                    },
                )
                runner.main(["--resume", str(record)])
                self.client.result.assert_called_with(f"minimax/{model}/reference-to-video", "existing-job")
                self.assertEqual(output.read_bytes(), MP4)
        self.client.submit.assert_not_called()
        self.client.upload_file.assert_not_called()

    def test_h3_draft_rejects_missing_clay_and_wrong_reference_syntax(self) -> None:
        self.draft_files(self.root)
        for model in ("h3-max", "h3"):
            for prompt in ("Restyle @Video1 as a clay render.", "Video 1 shows a ball.", "Video 10 is clay."):
                with self.subTest(model=model, prompt=prompt), self.assertRaisesRegex(RuntimeError, "edit_prompt.txt"):
                    (self.root / "edit_prompt.txt").write_text(prompt)
                    runner.validate_draft(self.root, 120, model)
        (self.root / "edit_prompt.txt").write_text(H3_PROMPT)
        self.assertEqual(runner.validate_draft(self.root, 120, "h3"), H3_PROMPT)
        (self.root / "edit_prompt.txt").write_text("Restyle @Video1: ice melts.")
        self.assertEqual(runner.validate_draft(self.root, 120, "seedance"), "Restyle @Video1: ice melts.")

    def test_h3_accepts_hd_reference_without_seedance_pixel_restrictions(self) -> None:
        proxy = self.root / "clay.mp4"
        proxy.write_bytes(MP4)
        metadata = {"streams": [{"width": 1920, "height": 1080}], "format": {"duration": "5"}}
        with patch.object(runner.subprocess, "check_output", return_value=json.dumps(metadata)):
            self.assertEqual(runner.validate_proxy(proxy, "ffprobe", "h3-max"), metadata)
            with self.assertRaisesRegex(RuntimeError, "Seedance"):
                runner.validate_proxy(proxy, "ffprobe", "seedance")

    def test_both_h3_agents_receive_shared_prompt_contract_and_full_timeline(self) -> None:
        for model in ("h3", "h3-max"):
            for agent in ("pi", "codex"):
                with self.subTest(model=model, agent=agent):
                    args = runner.parser().parse_args(["--video-model", model, "--agent", agent, "--duration", "8"])
                    instructions = runner.draft_instructions("ice melts", args, "blender", "ffmpeg", "ffprobe")
                    self.assertIn(runner.H3_CLAY_CONTRACT, instructions)
                    self.assertIn("Timeline section spanning 0 through 8 seconds", instructions)
                    self.assertIn("audited keyframes", instructions)

    def test_default_dry_run_shows_h3_max_payload_without_calls(self) -> None:
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream), patch.object(runner, "fal_client", side_effect=AssertionError("No fal")):
            runner.main([*self.inputs("a ball"), "--dry-run", "-o", str(self.output)])
        record = json.loads(stream.getvalue())
        self.assertEqual(record["endpoint"], "minimax/h3-max/reference-to-video")
        self.assertEqual(record["input"]["resolution"], "768P")
        self.assertEqual(record["input"]["duration"], 5)
        self.assertIn("clay", record["input"]["prompt"])
        self.assertFalse(self.artifacts.exists())

    def pi_events(self, workspace, *, status="pass", stop="stop", inspect=True, response=None):
        self.draft_files(workspace, status=status)
        events = []
        if inspect:
            events.extend(
                [
                    {
                        "type": "tool_execution_start",
                        "toolName": "read",
                        "toolCallId": "image",
                        "args": {"path": "preview.png"},
                    },
                    {
                        "type": "tool_execution_end",
                        "toolName": "read",
                        "toolCallId": "image",
                        "isError": False,
                        "result": {"content": [{"type": "image", "mimeType": "image/png", "data": "fixture"}]},
                    },
                ]
            )
        events.extend(
            [
                {
                    "type": "message_end",
                    "message": {
                        "role": "assistant",
                        "model": runner.MODEL,
                        "provider": runner.PI_PROVIDER,
                        "stopReason": stop,
                        "content": [{"type": "text", "text": response or (workspace / "audit.json").read_text()}],
                    },
                },
                {"type": "agent_end"},
            ]
        )
        return "".join(json.dumps(event) + "\n" for event in events)

    def pi_process(self, **options):
        def fake_exec(command, **kwargs):
            workspace = Path(kwargs["cwd"])
            runtime = Path(kwargs["env"]["PI_CODING_AGENT_DIR"])
            self.assertIn("--no-context-files", command)
            self.assertIn("--no-session", command)
            self.assertIn("--no-extensions", command)
            self.assertIn(runner.PI_PROVIDER, command)
            self.assertIn(runner.MODEL, command)
            self.assertNotIn("CODEX_HOME", kwargs["env"])
            self.assertNotIn("FAL_KEY", kwargs["env"])
            self.assertEqual(json.loads((runtime / "settings.json").read_text())["images"]["blockImages"], False)
            self.assertTrue((runtime / "pi_video.ts").is_file())
            self.assertTrue((workspace / "skill/physical-state-planner/SKILL.md").is_file())
            self.assertIn("read (open preview.png", kwargs["input"])
            self.assertNotIn("view_image", kwargs["input"])
            kwargs["stdout"].write(self.pi_events(workspace, **options))
            return subprocess.CompletedProcess(command, 0)

        self.stack.enter_context(patch.object(runner, "PI_STATE", self.root / "pi-auth"))
        self.stack.enter_context(patch.object(runner, "check_pi"))
        self.stack.enter_context(patch.object(runner, "check_codex", side_effect=AssertionError("No Codex")))
        self.stack.enter_context(patch.object(runner, "executable", side_effect=lambda value: value))
        self.stack.enter_context(patch.object(runner.subprocess, "run", side_effect=fake_exec))
        self.stack.enter_context(
            patch.object(
                runner,
                "validate_proxy",
                return_value={"streams": [{"width": 1280, "height": 720}], "format": {"duration": "5"}},
            )
        )

    def test_pi_renders_audits_uploads_and_saves_same_artifacts(self):
        self.api()
        self.pi_process()
        runner.main(["--agent", "pi", *self.inputs("ice melts"), "-o", str(self.output)])
        self.assertEqual(self.output.read_bytes(), MP4)
        self.assertTrue((self.artifacts / "audit.json").is_file())
        self.assertTrue((self.artifacts / "pi.events.jsonl").is_file())
        self.assertTrue((self.artifacts / "pi_prompt.txt").is_file())
        self.assertFalse((self.artifacts / "settings.json").exists())
        self.assertEqual(self.client.submit.call_args.args[0], "minimax/h3-max/reference-to-video")
        self.assertEqual(self.client.submit.call_args.kwargs["arguments"]["prompt"], H3_PROMPT)

    def test_pi_provider_error_even_with_zero_exit_never_submits(self):
        self.api()
        self.pi_process(stop="error")
        with self.assertRaisesRegex(RuntimeError, "did not finish"):
            runner.main(["--agent", "pi", *self.inputs("a ball"), "-o", str(self.output)])
        self.client.submit.assert_not_called()
        self.client.upload_file.assert_not_called()
        self.assertTrue((self.artifacts / "pi.events.jsonl").is_file())

    def test_pi_requires_image_inspection_before_submission(self):
        self.api()
        self.pi_process(inspect=False)
        with self.assertRaisesRegex(RuntimeError, "did not inspect"):
            runner.main(["--agent", "pi", *self.inputs("a ball"), "-o", str(self.output)])
        self.client.submit.assert_not_called()
        self.client.upload_file.assert_not_called()

    def test_pi_prepare_only_needs_no_fal_and_rejects_uncertain_audit(self):
        self.pi_process(status="uncertain")
        with patch.object(runner, "fal_client", side_effect=AssertionError("No fal")):
            with self.assertRaisesRegex(RuntimeError, "did not pass"):
                runner.main(["--agent", "pi", "--prepare-only", *self.inputs("a ball"), "-o", str(self.output)])
        self.assertTrue((self.artifacts / "audit.json").is_file())

    def test_pi_cannot_reuse_earlier_audit_when_final_response_is_malformed(self):
        self.api()
        self.pi_process(response="I finished!")
        with self.assertRaisesRegex(RuntimeError, "JSON audit object"):
            runner.main(["--agent", "pi", *self.inputs("a ball"), "-o", str(self.output)])
        self.client.submit.assert_not_called()

    def test_shared_audit_schema_rejects_missing_fields_and_wrong_types(self):
        self.draft_files(self.root)
        audit = json.loads((self.root / "audit.json").read_text())
        for invalid in ({k: v for k, v in audit.items() if k != "summary"}, {**audit, "known_limitations": "none"}):
            runner.write_json(self.root / "audit.json", invalid)
            with self.assertRaisesRegex(RuntimeError, "does not match"):
                runner.validate_draft(self.root, 120)

    def test_pi_environment_excludes_personal_config_provider_overrides_and_keys(self):
        with patch.dict(
            os.environ,
            {
                "HOME": "/user",
                "PATH": "/bin",
                "PI_CODING_AGENT_DIR": "/personal",
                "PI_CODING_AGENT_SESSION_DIR": "/old-sessions",
                "PI_PACKAGE_DIR": "/custom",
                "NODE_OPTIONS": "--require=personal.js",
                "BASH_ENV": "/personal.sh",
                "FAL_KEY": "secret",
                "OPENAI_API_KEY": "secret",
                "CODEX_API_KEY": "secret",
            },
        ):
            env = runner.pi_environment(self.root / "runtime")
        self.assertEqual(env["HOME"], "/user")
        self.assertEqual(env["PI_CODING_AGENT_DIR"], str(self.root / "runtime"))
        self.assertEqual(env["PI_OFFLINE"], "1")
        self.assertEqual(env["PI_TELEMETRY"], "0")
        for key in ("PI_PACKAGE_DIR", "NODE_OPTIONS", "BASH_ENV", "FAL_KEY", "OPENAI_API_KEY", "CODEX_API_KEY"):
            self.assertNotIn(key, env)

    def test_pi_login_routes_to_pi_without_starting_codex_or_fal(self):
        with (
            patch.object(runner, "pi_login") as login,
            patch.object(runner, "login", side_effect=AssertionError("No Codex")),
            patch.object(runner, "executable", side_effect=lambda value: value),
        ):
            runner.main(["--agent", "pi", "--pi", "/custom/pi", "--login"])
        login.assert_called_once_with("/custom/pi")

    def test_pi_requires_dedicated_oauth_and_checks_cli_before_generation(self):
        help_text = " ".join([*runner.PI_ISOLATION_FLAGS, "--extension", "--mode", "--thinking"])
        with (
            patch.object(runner, "PI_STATE", self.root),
            patch.object(runner.subprocess, "check_output", return_value=help_text),
        ):
            with self.assertRaisesRegex(RuntimeError, "dedicated ChatGPT"):
                runner.check_pi("pi")
            runner.write_json(self.root / "auth.json", {runner.PI_PROVIDER: {"type": "oauth", "access": "fixture"}})
            runner.check_pi("pi")
        with patch.object(runner.subprocess, "check_output", return_value="old CLI"):
            with self.assertRaisesRegex(RuntimeError, "Update Pi"):
                runner.check_pi("pi", require_auth=False)


if __name__ == "__main__":
    unittest.main()
