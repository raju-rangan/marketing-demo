# The Marketing Content Assistant (Marketing Agent)

Welcome to the **Marketing Content Assistant**—an agentic workflow built on Google's Agent Development Kit (ADK). This agent acts as an automated, highly-disciplined digital studio orchestrator designed to transform legacy knowledge articles (like PDFs and FAQs) into broadcast-quality, brand-compliant dynamic video content (Shorts and Slidecasts).

*Agent generated with [`googleCloudPlatform/agent-starter-pack`](https://github.com/GoogleCloudPlatform/agent-starter-pack).*

---

## 📚 Technical Documentation

To understand the architecture and the "art of the possible" behind this engine, please read our technical blog series located in the `marketing-agent/documentation/technical/` directory:

1. **[The Marketing Content Assistant](marketing-agent/documentation/technical/01-marketing-content-assistant.md)**: The executive pitch and overall workflow (Ideation → Storyboarding → Motion → Post-Production).
2. **[Precision Storyboarding](marketing-agent/documentation/technical/02-precision-storyboarding.md)**: How we use Skill-Driven Prompt Engineering, VLM-as-a-Judge (Gemini 2.5 Flash), and Stateful Surgical Edits to guarantee brand safety.
3. **[Predictable Motion with Veo](marketing-agent/documentation/technical/03-predictable-motion-with-veo.md)**: How First and Last Frame Conditioning puts a leash on `veo-3.1-generate-001` to eliminate AI video drift.
4. **[Cinematic Post-Production](marketing-agent/documentation/technical/04-cinematic-post-production.md)**: Using FFmpeg and "Hold Frame" transitions to stitch clips seamlessly and solve audio duration limits.

---

## 🗂️ Project Structure

```
marketing-agent/
├── app/                  # Core agent code
│   ├── agent.py          # Main agent logic
│   ├── brands/           # Brand-specific config & asset vaults
│   ├── skills/           # Composable skills (e.g., shorts-production)
│   ├── tools/            # Python backend functions
│   └── shared_infra/     # Media utilities (FFmpeg stitching)
├── documentation/        # Architecture and technical blog posts
├── tests/                # Unit, integration, and load tests
├── GEMINI.md             # AI-assisted development guide
└── Makefile              # Development commands
```

> 💡 **Tip:** Use [Gemini CLI](https://github.com/google-gemini/gemini-cli) for AI-assisted development - project context is pre-configured in `marketing-agent/GEMINI.md`.

---

## 🚀 Getting Started

For full installation instructions, infrastructure setup, and deployment guides, please see the **[Getting Started Guide](marketing-agent/getting-started.md)**.

---

## 🛠️ Project Management Commands

| Command | Description |
|---------|--------------|
| `make install` | Install dependencies using uv |
| `make playground` | Launch local development environment |
| `make lint` | Run code quality checks |
| `make test` | Run unit and integration tests |
| `make deploy` | Deploy agent to Agent Engine |
| `uvx agent-starter-pack enhance` | Add CI/CD pipelines and Terraform infrastructure |
| `uvx agent-starter-pack setup-cicd` | One-command setup of entire CI/CD pipeline + infrastructure |
| `uvx agent-starter-pack upgrade` | Auto-upgrade to latest version while preserving customizations |
