/** The runner's only Pi extension: match Codex fast/xhigh request settings. */
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export default function (pi: ExtensionAPI) {
  pi.on("before_provider_request", (event, ctx) => {
    const payload = event.payload as Record<string, unknown>;
    if (ctx.model?.provider !== "openai-codex" || payload.model !== "gpt-6-astra") {
      // Pi catches ordinary extension exceptions and continues. Exit instead of
      // silently making a paid request with an unintended model/provider.
      process.stderr.write("VideoCoCo requires openai-codex/gpt-6-astra.\n");
      process.exit(1);
    }
    return {
      ...payload,
      service_tier: "priority",
      reasoning: { ...(payload.reasoning as object), effort: "xhigh" },
      store: false,
    };
  });
}
