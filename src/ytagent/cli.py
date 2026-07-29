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


def main() -> None:
    """Entry point for the `ytagent` console script."""
    cli()


if __name__ == "__main__":
    main()
