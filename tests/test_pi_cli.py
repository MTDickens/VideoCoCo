"""Optional installed-Pi checks using synthetic credentials and no model calls."""

import base64
import json
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from scripts import generate_video as runner

PI = shutil.which("pi")


@unittest.skipUnless(PI, "Pi CLI is optional; unit tests cover both backends without it")
class PiCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="videococo-pi-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / "workspace"
        self.runtime = self.root / "runtime"
        self.workspace.mkdir()
        self.runtime.mkdir()
        runner.pi_settings(self.runtime)
        claims = {"https://api.openai.com/auth": {"chatgpt_account_id": "offline-fixture"}}
        token = "fixture." + base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=") + ".fixture"
        runner.write_json(
            self.runtime / "auth.json",
            {
                runner.PI_PROVIDER: {
                    "type": "oauth",
                    "access": token,
                    "refresh": "offline-fixture",
                    "expires": int(time.time() * 1000) + 3_600_000,
                }
            },
        )
        for path in (self.root / "AGENTS.md", self.runtime / "AGENTS.md", self.workspace / "AGENTS.md"):
            path.write_text("UNRELATED_CONTEXT_MARKER")
        (self.runtime / "extensions").mkdir()
        (self.runtime / "extensions/personal.ts").write_text('throw new Error("UNRELATED_EXTENSION_LOADED");')
        self.extension = self.runtime / "pi_video.ts"
        shutil.copy2(runner.REPO / "scripts/pi_video.ts", self.extension)
        self.report = self.root / "report.json"

    def invoke(self, probe_source, *, rpc):
        probe = self.runtime / "probe.ts"
        probe.write_text(probe_source, encoding="utf-8")
        assert PI is not None
        command = runner.pi_command(PI, self.extension)
        command.extend(["--extension", str(probe)])
        if rpc:
            command[command.index("json")] = "rpc"
            command.remove("--print")
        result = subprocess.run(
            command,
            cwd=self.workspace,
            env=runner.pi_environment(self.runtime),
            input='{"id":"verify","type":"get_state"}\n' if rpc else "Offline request serialization test.",
            text=True,
            capture_output=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr.strip(), "")
        self.assertTrue(self.report.is_file(), result.stdout)
        return result

    def test_real_cli_isolates_context_extensions_sessions_and_selects_model(self):
        result = self.invoke(
            'import {writeFileSync} from "node:fs"; export default function(pi) {'
            'pi.on("session_start", (event,ctx) => {'
            f"writeFileSync({json.dumps(str(self.report))}, JSON.stringify({{"
            "model:ctx.model?.id, provider:ctx.model?.provider, "
            'contaminated:ctx.getSystemPrompt().includes("UNRELATED_CONTEXT_MARKER")})); }); }',
            rpc=True,
        )
        self.assertEqual(
            json.loads(self.report.read_text()), {"model": runner.MODEL, "provider": runner.PI_PROVIDER, "contaminated": False}
        )
        state = next(json.loads(line)["data"] for line in result.stdout.splitlines() if json.loads(line).get("id") == "verify")
        self.assertEqual(state["thinkingLevel"], "xhigh")
        self.assertNotIn("sessionFile", state)

    def test_real_provider_payload_requests_priority_xhigh_before_any_network_call(self):
        # This hook runs after our extension and exits BEFORE the provider sends
        # the request. The credentials are synthetic and never sent anywhere.
        self.invoke(
            'import {writeFileSync} from "node:fs"; export default function(pi) {'
            'pi.on("before_provider_request", (event) => {'
            "const p=event.payload;"
            f"writeFileSync({json.dumps(str(self.report))}, JSON.stringify({{"
            "model:p.model,tier:p.service_tier,effort:p.reasoning.effort,store:p.store})); process.exit(0); }); }",
            rpc=False,
        )
        self.assertEqual(
            json.loads(self.report.read_text()), {"model": runner.MODEL, "tier": "priority", "effort": "xhigh", "store": False}
        )
