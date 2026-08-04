# Contributing to ytagent

First, read these files in order:

1. **`CLAUDE.md`** — master orientation, constraints, the 10 commandments.
2. **`agents.md`** — the role prompt for the agent you're touching.
3. **`techstack.md`** — if you're adding a dependency.
4. **`phases.md`** — to know which phase the work belongs to.
5. **`skills.md`** — to know which skill you're implementing or extending.

## Development setup

```bash
git clone https://github.com/Bilal140202/ytagent.git
cd ytagent
pip install -e ".[dev]"

# Set up the BGutil POT provider (required for downloads from datacenter IPs)
git clone https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git /home/z/bgutil-ytdlp-pot-provider
cd /home/z/bgutil-ytdlp-pot-provider/server
npm install --production && npm install typescript && ./node_modules/.bin/tsc
cd -

# Generate test fixtures
python scripts/make_fixtures.py

# Run tests
pytest tests/ -x

# Run self-test
ytagent self-test --mode quick
```

## Before opening a PR

1. `ruff check .` is clean.
2. `ruff format --check .` is clean.
3. `pytest tests/ -x` passes.
4. `ytagent self-test --mode quick` exits 0.
5. You've updated `plan.md` checkboxes.
6. You've documented any new dependency in `techstack.md`.
7. You've updated `agents.md` if you changed an agent's interface.
8. You've updated `skills.md` if you added a new skill.

## The 10 commandments (read before every PR)

1. Thou shalt not add cookies.
2. Thou shalt not call an LLM at runtime.
3. Thou shalt not skip the Verifier.
4. Thou shalt not stop at the first failure.
5. Thou shalt not write outside `/home/z/my-project/`.
6. Thou shalt not `print()`. Use the logger.
7. Thou shalt not hard-code video IDs in production code.
8. Thou shalt not trust a method's self-report.
9. Thou shalt pin `yt-dlp` to a known-good version.
10. Thou shalt append to `observations.jsonl`, never overwrite.
