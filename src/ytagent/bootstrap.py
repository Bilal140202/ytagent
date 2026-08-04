"""Bootstrap module — auto-installs and starts the BGutil POT provider.

This is what makes `pip install ytagent && ytagent download <url>` Just Work
on a fresh machine. No manual clone, no manual npm install, no manual server
start. ytagent does it all for you (and for the AI agent calling it).

Public API:
  - ensure_bgutil_ready() -> bool
      Check that BGutil is installed, compiled, and the HTTP server is
      running. If any step is missing, do it. Returns True on success.
      Never raises.

  - bgutil_status() -> dict
      Return a structured status dict for `ytagent setup --status`.

  - stop_server() -> bool
      Stop the auto-started BGutil server (best-effort).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

from . import log

# Where to put the BGutil server source. Override with YTAGENT_BGUTIL_HOME env.
DEFAULT_BGUTIL_HOME = Path(os.environ.get(
    "YTAGENT_BGUTIL_HOME", "/home/z/bgutil-ytdlp-pot-provider"
))
BGUTIL_REPO = "https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git"
BGUTIL_PORT = 4416
BGUTIL_PING_URL = f"http://127.0.0.1:{BGUTIL_PORT}/ping"

# Path to the PID file tracking the auto-started server.
_PID_FILE = Path("/tmp/ytagent-bgutil.pid")


def _run(cmd: list[str], cwd: Path | None = None, timeout: int = 300) -> tuple[int, str, str]:
    """Run a command, return (returncode, stdout, stderr). Never raises."""
    try:
        proc = subprocess.run(
            cmd, cwd=str(cwd) if cwd else None,
            capture_output=True, text=True, timeout=timeout, check=False,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout after {timeout}s"
    except FileNotFoundError:
        return 127, "", f"command not found: {cmd[0]}"
    except Exception as e:
        return 1, "", str(e)


def _http_server_running() -> bool:
    """Quick ping check if the BGutil HTTP server is up."""
    try:
        import requests
        r = requests.get(BGUTIL_PING_URL, timeout=2)
        return r.status_code == 200
    except Exception:
        return False


def _server_dir() -> Path:
    return DEFAULT_BGUTIL_HOME / "server"


def _build_dir() -> Path:
    return _server_dir() / "build"


def _main_js() -> Path:
    return _build_dir() / "main.js"


def _is_cloned() -> bool:
    return (_server_dir() / "package.json").exists()


def _is_compiled() -> bool:
    return _main_js().exists()


def _has_node() -> bool:
    return shutil.which("node") is not None


def _has_npm() -> bool:
    return shutil.which("npm") is not None


def _has_git() -> bool:
    return shutil.which("git") is not None


def _step_clone() -> bool:
    """Step 1: clone the BGutil repo."""
    if _is_cloned():
        log.info("BGutil already cloned", path=str(DEFAULT_BGUTIL_HOME))
        return True
    if not _has_git():
        log.error("git not found on PATH; cannot clone BGutil")
        return False
    log.info("Cloning BGutil POT provider", path=str(DEFAULT_BGUTIL_HOME))
    rc, out, err = _run(["git", "clone", "--depth=1", BGUTIL_REPO, str(DEFAULT_BGUTIL_HOME)])
    if rc != 0:
        log.error("git clone failed", rc=rc, stderr=err[:300])
        return False
    return _is_cloned()


def _step_npm_install() -> bool:
    """Step 2: npm install (production deps + typescript)."""
    if not _has_npm():
        log.error("npm not found on PATH; cannot install BGutil deps")
        return False
    server = _server_dir()
    if not (server / "node_modules").exists():
        log.info("Running npm install --production")
        rc, out, err = _run(["npm", "install", "--production"], cwd=server, timeout=300)
        if rc != 0:
            log.error("npm install --production failed", rc=rc, stderr=err[:300])
            return False
    if not (server / "node_modules" / ".bin" / "tsc").exists():
        log.info("Installing TypeScript compiler")
        rc, out, err = _run(["npm", "install", "typescript"], cwd=server, timeout=120)
        if rc != 0:
            log.error("npm install typescript failed", rc=rc, stderr=err[:300])
            return False
    return True


def _step_compile() -> bool:
    """Step 3: compile TypeScript."""
    if _is_compiled():
        log.info("BGutil already compiled")
        return True
    server = _server_dir()
    tsc = server / "node_modules" / ".bin" / "tsc"
    if not tsc.exists():
        log.error("tsc not found; npm install did not complete")
        return False
    log.info("Compiling BGutil TypeScript")
    rc, out, err = _run([str(tsc)], cwd=server, timeout=120)
    if rc != 0:
        log.error("tsc failed", rc=rc, stderr=err[:300])
        return False
    return _is_compiled()


def _step_start_server() -> bool:
    """Step 4: start the HTTP server in the background (if not running)."""
    if _http_server_running():
        log.info("BGutil HTTP server already running")
        return True
    if not _has_node():
        log.error("node not found on PATH; cannot start BGutil server")
        return False
    main_js = _main_js()
    if not main_js.exists():
        log.error("BGutil not compiled; run setup first")
        return False

    log.info("Starting BGutil HTTP server", port=BGUTIL_PORT)
    log_path = "/tmp/ytagent-bgutil.log"
    try:
        with open(log_path, "w") as logf:
            proc = subprocess.Popen(
                ["node", str(main_js), "--port", str(BGUTIL_PORT)],
                stdout=logf, stderr=logf,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
        _PID_FILE.write_text(str(proc.pid))
    except Exception as e:
        log.error("failed to spawn BGutil server", error=str(e))
        return False

    for _ in range(20):
        if _http_server_running():
            log.success("BGutil HTTP server started",
                        port=BGUTIL_PORT, pid=proc.pid, log=log_path)
            return True
        time.sleep(0.5)

    log.error("BGutil HTTP server did not come up within 10s", log=log_path)
    return False


def ensure_bgutil_ready(*, auto_install: bool = True, auto_start: bool = True) -> bool:
    """Top-level: make sure BGutil is installed, compiled, and running.

    Args:
        auto_install: if True, clone + npm install + compile if missing.
        auto_start:   if True, start the HTTP server if not running.

    Returns True if BGutil HTTP server is reachable at the end. Never raises.
    """
    if _http_server_running():
        return True

    if not _is_cloned() and not auto_install:
        log.warn("BGutil not installed and auto_install=False")
        return False

    if auto_install:
        if not _step_clone():
            return False
        if not _step_npm_install():
            return False
        if not _step_compile():
            return False

    if not _is_compiled():
        log.error("BGutil not compiled; cannot start server")
        return False

    if auto_start:
        return _step_start_server()
    return True


def bgutil_status() -> dict:
    """Return a structured status dict for `ytagent setup --status`."""
    return {
        "node_available": _has_node(),
        "npm_available": _has_npm(),
        "git_available": _has_git(),
        "bgutil_home": str(DEFAULT_BGUTIL_HOME),
        "is_cloned": _is_cloned(),
        "is_compiled": _is_compiled(),
        "http_server_running": _http_server_running(),
        "http_server_port": BGUTIL_PORT,
        "main_js": str(_main_js()),
        "ready": _http_server_running(),
    }


def stop_server() -> bool:
    """Stop the auto-started BGutil server (best-effort)."""
    if not _PID_FILE.exists():
        return False
    try:
        pid = int(_PID_FILE.read_text().strip())
        os.kill(pid, 15)  # SIGTERM
        _PID_FILE.unlink()
        log.info("BGutil server stopped", pid=pid)
        return True
    except Exception as e:
        log.warn("failed to stop BGutil server", error=str(e))
        return False
