# NovelGraph contributor rules

This project is a **novel analysis and continuity-checking tool**, not an automated novel writer.

## Mandatory scope
- ChatGPT performs meaning-based extraction; Moon MCP provides file/CLI access. Do not add external paid LLM API dependencies or a second MCP service without a documented need.
- Preserve original source evidence, event ordering, approval status and reproducible historical world state.
- Keep code changes minimal. Inspect callers and tests, and do not rewrite unrelated files.

## Data safety
- This GitHub repository is **public**. Do not commit manuscripts, copyrighted source text, user datasets, SQLite DBs, model outputs containing passages, access tokens, credentials or keys.
- Keep real working data outside the Git working tree at `/shared/NovelGraph-data` (private directory).
- `.gitignore` is a precaution, **not** a security boundary. Before every commit, inspect staged file paths and diff content. Never use `git add -f` for ignored private files.
- Do not delete, reset or overwrite old Moon project sources or databases when found. Copy and audit first.

## Development and verification
- Use `/shared/NovelGraph` as the canonical working clone and `.venv/bin/python` for Python commands.
- Do not claim tests passed unless executed in this environment. Record command and result.
- Monetary values must not be computed using binary floating point.
- Source recovery status: only the present docs are verified; earlier `909e00d` and historic test counts are not available.
- Read `/shared/AGENTS.md` for workmachine-wide rules and preserve existing Moon services and reserved ports.

## Mandatory Moon project constitution

Before making changes in this project, read `/shared/AGENTS.md`, this repository `AGENTS.md` and `.agent/CONSTITUTION.md`. Check GitHub `origin/main` and the existing implementation first. For Moon work use `/shared/agent-tools/moon-project.mjs` and stop if the entry reports stale Git or missing policies. Read policy text, not merely the discovered file names. This is a guarded workflow; do not claim unrestricted direct Moon tools are centrally blocked.
