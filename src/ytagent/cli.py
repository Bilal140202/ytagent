"""ytagent CLI — click-based entry point.

Subcommands:
  ytagent download <url|id> [--out-dir DIR] [--format FMT] [--proxy URL]
  ytagent truth show
  ytagent truth reset [--method NAME]
  ytagent --self-test [--quick|--full]
  ytagent --list-methods
  ytagent --version
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

from . import __version__, log
from .agents.tester import Tester
from .agents.truth import TruthAgent
from .agents.verifier import Verifier
from .bootstrap import bgutil_status, ensure_bgutil_ready, stop_server, BGUTIL_PORT
from .methods import METHOD_REGISTRY, list_methods
from .methods.base import default_opts
from .orchestrator import Orchestrator

try:
    from rich.console import Console
    from rich.table import Table
    _RICH = True
except ImportError:  # pragma: no cover
    _RICH = False

_console = Console() if _RICH else None

DEFAULT_STATE_DIR = Path("/home/z/my-project/ytdl-agent/state")
DEFAULT_OUT_DIR = Path("/home/z/my-project/ytdl-agent/downloads")


def _make_orchestrator(state_dir: Path) -> Orchestrator:
    truth = TruthAgent(state_dir=state_dir)
    verifier = Verifier()
    return Orchestrator(truth=truth, verifier=verifier, methods=METHOD_REGISTRY)


@click.group(invoke_without_command=True)
@click.option("--version", is_flag=True, help="Print version and exit.")
@click.pass_context
def cli(ctx: click.Context, version: bool) -> None:
    """ytagent — agentic YouTube downloader for cloud-based AI agents."""
    if version:
        click.echo(f"ytagent {__version__}")
        return
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@cli.command(name="download")
@click.argument("target")
@click.option("--out-dir", default=str(DEFAULT_OUT_DIR), help="Directory to save the video.")
@click.option("--format", "format_str", default=None, help="Override yt-dlp format string.")
@click.option("--proxy", default=None, help="HTTP proxy URL (e.g. WARP sidecar http://127.0.0.1:3128).")
@click.option("--timeout", type=int, default=180, help="Per-method timeout in seconds.")
@click.option("--state-dir", default=str(DEFAULT_STATE_DIR), help="State directory.")
@click.option("--json", "as_json", is_flag=True, help="Print result as JSON.")
def download_cmd(target: str, out_dir: str, format_str: str | None, proxy: str | None,
                 timeout: int, state_dir: str, as_json: bool) -> None:
    """Download a YouTube video to a verified file on disk."""
    orchestrator = _make_orchestrator(Path(state_dir))
    opts = default_opts(timeout=timeout, format=format_str, proxy=proxy)
    result = orchestrator.download(target, Path(out_dir), opts=opts)

    if as_json:
        import json
        click.echo(json.dumps(result.to_dict(), indent=2, default=str))
    else:
        if result.ok:
            log.success("download ok", video_id=result.video_id,
                        method=result.method_used, path=result.final_path)
            click.echo(f"\nOK  video_id={result.video_id}")
            click.echo(f"    method={result.method_used}")
            click.echo(f"    path={result.final_path}")
            click.echo(f"    total_duration_ms={result.total_duration_ms}")
            click.echo(f"    attempts={len(result.attempts)}")
        else:
            log.error("download failed", video_id=result.video_id, attempts=len(result.attempts))
            click.echo(f"\nFAIL  video_id={result.video_id}")
            click.echo(f"      attempts={len(result.attempts)}")
            for a in result.attempts:
                status = "ok" if a.ok else "fail"
                click.echo(f"      [{status}] {a.method}: {a.reason}")
                if a.verify_reason:
                    click.echo(f"             verify: {a.verify_reason}")
    sys.exit(0 if result.ok else 1)


@cli.group(name="truth")
def truth_group() -> None:
    """Inspect or reset the Truth Agent's state."""


@truth_group.command(name="show")
@click.option("--state-dir", default=str(DEFAULT_STATE_DIR))
def truth_show(state_dir: str) -> None:
    """Show the current truth.json contents."""
    truth = TruthAgent(state_dir=Path(state_dir))
    snap = truth.snapshot()
    if _RICH:
        table = Table(title="Truth Agent state")
        table.add_column("Rank", justify="right")
        table.add_column("Method")
        table.add_column("Failures", justify="right")
        table.add_column("Ratio", justify="right")
        table.add_column("Attempts", justify="right")
        for m in sorted(snap.get("methods", []), key=lambda x: x["rank"]):
            table.add_row(
                str(m["rank"]),
                m["name"],
                str(m["consecutive_failures"]),
                f"{m['success_ratio']:.2f}",
                str(m["attempts"]),
            )
        _console.print(table)
        _console.print(f"\nUpdated: {snap.get('updated_at')}")
    else:
        click.echo(f"Updated: {snap.get('updated_at')}")
        for m in sorted(snap.get("methods", []), key=lambda x: x["rank"]):
            click.echo(f"  rank={m['rank']}  {m['name']:<25}  "
                       f"failures={m['consecutive_failures']}  "
                       f"ratio={m['success_ratio']:.2f}  "
                       f"attempts={m['attempts']}")


@truth_group.command(name="reset")
@click.option("--method", default=None, help="Reset only this method (default: all).")
@click.option("--state-dir", default=str(DEFAULT_STATE_DIR))
def truth_reset(method: str | None, state_dir: str) -> None:
    """Reset truth.json to defaults."""
    truth = TruthAgent(state_dir=Path(state_dir))
    truth.reset(method=method)
    click.echo(f"Reset truth.json (method={method or 'all'})")


@cli.command(name="self-test")
@click.option("--mode", type=click.Choice(["quick", "full"]), default="quick")
@click.option("--out-dir", default=str(DEFAULT_STATE_DIR / "self-test"))
@click.option("--keep-files", is_flag=True, help="Keep downloaded files after testing.")
@click.option("--state-dir", default=str(DEFAULT_STATE_DIR))
def self_test_cmd(mode: str, out_dir: str, keep_files: bool, state_dir: str) -> None:
    """Run end-to-end smoke test against known-stable public videos."""
    orchestrator = _make_orchestrator(Path(state_dir))
    verifier = Verifier()
    tester = Tester(orchestrator=orchestrator, verifier=verifier)
    report = tester.run(mode=mode, out_dir=Path(out_dir), keep_files=keep_files)

    if _RICH:
        _console.print("\n" + report.to_markdown())
    else:
        click.echo(report.to_markdown())

    sys.exit(report.exit_code)


@cli.command(name="list-methods")
def list_methods_cmd() -> None:
    """List all registered download methods."""
    for name in list_methods():
        click.echo(name)


@cli.command(name="setup")
@click.option("--status", "show_status", is_flag=True, help="Print BGutil status and exit.")
@click.option("--stop", is_flag=True, help="Stop the auto-started BGutil server.")
@click.option("--no-install", is_flag=True, help="Skip cloning/installing if missing.")
@click.option("--no-start", is_flag=True, help="Skip starting the HTTP server.")
def setup_cmd(show_status: bool, stop: bool, no_install: bool, no_start: bool) -> None:
    """One-command setup: clone, compile, and start the BGutil POT provider.

    This is what makes `ytagent download <url>` Just Work on a fresh machine.
    Safe to re-run; skips steps that are already done.
    """
    if show_status:
        s = bgutil_status()
        if _RICH:
            table = Table(title="BGutil POT provider status")
            table.add_column("Check")
            table.add_column("Value")
            for k, v in s.items():
                table.add_row(k, str(v))
            _console.print(table)
        else:
            for k, v in s.items():
                click.echo(f"  {k}: {v}")
        sys.exit(0 if s["ready"] else 1)

    if stop:
        ok = stop_server()
        click.echo("stopped" if ok else "no auto-started server found")
        return

    click.echo("Setting up BGutil POT provider...")
    ok = ensure_bgutil_ready(
        auto_install=not no_install,
        auto_start=not no_start,
    )
    if ok:
        click.echo("\nBGutil POT provider is ready.")
        click.echo(f"   HTTP server running on http://127.0.0.1:{BGUTIL_PORT}")
        click.echo("\nYou can now download videos:")
        click.echo('  ytagent download "https://www.youtube.com/watch?v=..."')
        sys.exit(0)
    else:
        click.echo("\nSetup incomplete. Run `ytagent setup --status` to diagnose.")
        sys.exit(1)


@cli.command(name="agent-instructions")
@click.option("--format", "fmt", type=click.Choice(["text", "json", "markdown"]),
              default="text", help="Output format.")
def agent_instructions_cmd(fmt: str) -> None:
    """Step-by-step instructions for AI agents using ytagent.

    Prints a complete guide that an AI agent can follow to use ytagent
    from install to verified download — with zero manual human steps.

    The instructions cover:
      1. Install (pip install ytagent)
      2. Setup (ytagent setup — auto-installs BGutil POT provider)
      3. Download (ytagent download <url>)
      4. Verify the result (parse JSON output)
      5. Troubleshoot (what to do if download fails)
      6. Advanced (bypass methods, proxy, batch, self-test)

    An AI agent reading ONLY this output should be able to download any
    public YouTube video without asking a human a single question.
    """
    instructions = _build_agent_instructions()
    if fmt == "json":
        import json
        click.echo(json.dumps({"instructions": instructions, "version": __version__}, indent=2))
    elif fmt == "markdown":
        click.echo("# ytagent — AI Agent Instructions\n")
        for step in instructions:
            click.echo(f"## Step {step['step']}: {step['title']}\n")
            click.echo(f"{step['description']}\n")
            if step.get("command"):
                click.echo(f"```bash\n{step['command']}\n```\n")
            if step.get("expected_output"):
                click.echo(f"**Expected output:**\n```\n{step['expected_output']}\n```\n")
    else:
        click.echo(f"\n{'='*70}")
        click.echo(f"  ytagent v{__version__} — AI Agent Instructions")
        click.echo(f"  Complete step-by-step guide. Follow these steps in order.")
        click.echo(f"{'='*70}\n")
        for step in instructions:
            click.echo(f"── Step {step['step']}: {step['title']} " + "─" * (50 - len(step['title'])))
            click.echo(f"\n{step['description']}\n")
            if step.get("command"):
                click.echo(f"  Command:")
                click.echo(f"    {step['command']}\n")
            if step.get("expected_output"):
                click.echo(f"  Expected output (look for):")
                for line in step['expected_output'].split('\n'):
                    click.echo(f"    {line}")
                click.echo("")
            if step.get("on_failure"):
                click.echo(f"  If this step fails:")
                for line in step['on_failure'].split('\n'):
                    click.echo(f"    {line}")
                click.echo("")
        click.echo("─" * 70)
        click.echo("  After completing all steps, the video is at the path shown in Step 4.")
        click.echo("  No human intervention is needed at any point.")
        click.echo("─" * 70 + "\n")


def _build_agent_instructions() -> list[dict]:
    """Build the step-by-step instruction list for AI agents."""
    return [
        {
            "step": 1,
            "title": "Install ytagent",
            "description": (
                "Install ytagent from PyPI. This pulls yt-dlp, the BGutil POT "
                "provider plugin, and all other dependencies automatically.\n\n"
                "Requirements: Python 3.11+, ffmpeg, ffprobe, node, npm, git "
                "(all available on most Linux/macOS systems)."
            ),
            "command": "pip install ytagent",
            "expected_output": "Successfully installed ytagent-x.x.x",
            "on_failure": (
                "If pip install fails, try: pip install --break-system-packages ytagent\n"
                "If pysocks is missing for SOCKS5 proxy support: pip install pysocks"
            ),
        },
        {
            "step": 2,
            "title": "Verify install + check system requirements",
            "description": (
                "Confirm ytagent is installed and print its version. "
                "This also verifies the CLI entry point is on PATH."
            ),
            "command": "ytagent --version",
            "expected_output": "ytagent x.x.x",
            "on_failure": (
                "If 'ytagent: command not found', the install directory is not on PATH.\n"
                "Find it with: python3 -m pip show ytagent | grep Location\n"
                "Then add ~/.local/bin to PATH: export PATH=\"$HOME/.local/bin:$PATH\""
            ),
        },
        {
            "step": 3,
            "title": "Run one-time setup (auto-installs BGutil POT provider)",
            "description": (
                "This clones the BGutil POT provider repo, runs npm install, "
                "compiles TypeScript, and starts the HTTP server on port 4416.\n\n"
                "The BGutil server generates Proof-of-Origin tokens that bypass "
                "YouTube's 'Sign in to confirm you're not a bot' block on "
                "datacenter IPs.\n\n"
                "This step takes ~15 seconds and only needs to be run once. "
                "The server keeps running in the background."
            ),
            "command": "ytagent setup",
            "expected_output": (
                "Setting up BGutil POT provider...\n"
                "Cloning BGutil POT provider\n"
                "Running npm install --production\n"
                "Compiling BGutil TypeScript\n"
                "Starting BGutil HTTP server\n"
                "BGutil HTTP server started\n"
                "BGutil POT provider is ready."
            ),
            "on_failure": (
                "If setup fails, check: node --version (need v18+), npm --version, git --version.\n"
                "If the server doesn't start, check port 4416 is free.\n"
                "You can still download without BGutil — the fallback chain will try other methods."
            ),
        },
        {
            "step": 4,
            "title": "Check setup status (optional but recommended)",
            "description": (
                "Verify the BGutil server is running and ready. "
                "All fields should show True/ready."
            ),
            "command": "ytagent setup --status",
            "expected_output": (
                "is_cloned: True\n"
                "is_compiled: True\n"
                "http_server_running: True\n"
                "ready: True"
            ),
            "on_failure": (
                "If ready is False, re-run: ytagent setup\n"
                "If still failing, the download will still work — it just won't use BGutil."
            ),
        },
        {
            "step": 5,
            "title": "Download a YouTube video",
            "description": (
                "Download any public YouTube video. ytagent will:\n"
                "  1. Resolve the video ID from the URL\n"
                "  2. Try 13 download methods in order (fallback chain)\n"
                "  3. Verify the downloaded file (6-layer integrity check)\n"
                "  4. Move the verified file to the output directory\n"
                "  5. Return a JSON result with the file path\n\n"
                "The download typically takes 5-30 seconds for a standard video.\n"
                "For blocked datacenter IPs, the bypass methods (SOCKS5 proxy farm, "
                "Invidious local=true, Cobalt community) add ~30-120 seconds."
            ),
            "command": (
                'ytagent download "https://www.youtube.com/watch?v=VIDEO_ID" \\\n'
                '  --out-dir ./downloads --json'
            ),
            "expected_output": (
                '{"ok": true, "video_id": "VIDEO_ID", "final_path": "./downloads/VIDEO_ID.mp4",\n'
                ' "method_used": "ytdlp_default", "total_duration_ms": 5432, ...}'
            ),
            "on_failure": (
                "If ok is false, the 'attempts' array shows which methods were tried and why they failed.\n"
                "Common fixes:\n"
                "  - Run ytagent setup again (BGutil server may have stopped)\n"
                "  - Try with a longer timeout: --timeout 300\n"
                "  - Check if the video is public (not private/age-restricted)\n"
                "  - The Truth Agent auto-demotes failing methods; retry after a few minutes"
            ),
        },
        {
            "step": 6,
            "title": "Parse the JSON result (for programmatic use)",
            "description": (
                "The --json flag outputs clean JSON to stdout (all logs go to stderr).\n"
                "Parse the JSON to get the file path and verification details.\n\n"
                "Key fields:\n"
                "  ok            — true if download succeeded and verified\n"
                "  final_path    — the path to the verified MP4 file\n"
                "  method_used   — which of the 13 methods succeeded\n"
                "  attempts[]    — full audit trail of every method tried\n"
                "  total_duration_ms — wall-clock time"
            ),
            "command": (
                'result=$(ytagent download "$URL" --json 2>/dev/null)\n'
                'path=$(echo "$result" | python3 -c "import sys,json; print(json.load(sys.stdin)[\'final_path\'])")\n'
                'echo "Video saved to: $path"'
            ),
            "expected_output": "Video saved to: ./downloads/VIDEO_ID.mp4",
            "on_failure": (
                "If the JSON is empty or invalid, check stderr for error logs.\n"
                "Ensure you're using --json (not just parsing the text output)."
            ),
        },
        {
            "step": 7,
            "title": "Download a blocked video (datacenter IP bypass)",
            "description": (
                "If the video is blocked by YouTube's 'Sign in to confirm you're "
                "not a bot' (common on cloud/datacenter IPs), ytagent automatically "
                "tries 4 bypass methods:\n\n"
                "  Tier 8:  cobalt_community — public Cobalt relay instances\n"
                "  Tier 10: invidious — Invidious local=true proxy (instance streams through its IP)\n"
                "  Tier 11: socks5_farm — discovers free SOCKS5 proxies, tests 50 in parallel\n"
                "  Tier 12: github_actions_farm — remote download on GitHub runners with WARP\n\n"
                "No special flags needed — the fallback chain runs automatically."
            ),
            "command": (
                '# This is the same command — bypass is automatic\n'
                'ytagent download "https://www.youtube.com/watch?v=VIDEO_ID" --timeout 300 --json'
            ),
            "expected_output": (
                'The "method_used" field will show which bypass method worked:\n'
                '  "cobalt_community" or "invidious" or "socks5_farm"'
            ),
            "on_failure": (
                "If all 13 methods fail, the video may be private, deleted, or region-locked.\n"
                "Check the 'attempts' array for the specific failure reasons.\n"
                "For sustained bypass, self-host Cobalt on Oracle Cloud Free Tier with WARP."
            ),
        },
        {
            "step": 8,
            "title": "Run the self-test (optional health check)",
            "description": (
                "Download a known-stable public video to verify the system works.\n"
                "Quick mode (default) tests one video in <2 minutes.\n"
                "Full mode tests 5 videos with 5-second pauses between them."
            ),
            "command": "ytagent self-test --mode quick",
            "expected_output": (
                "A markdown table with per-video results.\n"
                "Exit code 0 means all videos passed."
            ),
            "on_failure": (
                "If self-test fails, run ytagent setup again.\n"
                "Check ytagent truth show to see which methods are demoted."
            ),
        },
        {
            "step": 9,
            "title": "Inspect the Truth Agent's learned state (optional)",
            "description": (
                "The Truth Agent tracks which methods work best in your environment "
                "and reorders the fallback chain accordingly. After 3 consecutive "
                "failures, a method is demoted. After a success, it may be promoted."
            ),
            "command": "ytagent truth show",
            "expected_output": (
                "A table showing each method's rank, failure count, success ratio, "
                "and total attempts."
            ),
            "on_failure": (
                "To reset the Truth Agent's learning: ytagent truth reset\n"
                "To reset a single method: ytagent truth reset --method <name>"
            ),
        },
        {
            "step": 10,
            "title": "Batch download (for AI agents processing multiple videos)",
            "description": (
                "ytagent processes one video per invocation. For batch downloads, "
                "call ytagent in a loop. The 3-second pause between downloads "
                "avoids rate-limiting."
            ),
            "command": (
                "for url in 'URL1' 'URL2' 'URL3'; do\n"
                "  ytagent download \"$url\" --out-dir ./downloads --json 2>/dev/null\n"
                "  sleep 3\n"
                "done"
            ),
            "expected_output": "One JSON object per video, each with ok=true and final_path.",
            "on_failure": (
                "If some videos fail, the Truth Agent will have demoted the failing methods.\n"
                "Retry the failed videos after a few minutes — bypass services recover.\n"
                "For large batches, consider running ytagent self-test first to warm up the Truth Agent."
            ),
        },
    ]


def main() -> None:
    """Entry point for the `ytagent` console script."""
    cli()


if __name__ == "__main__":
    main()
