"""Tier 9 — GitHub Actions remote download farm.

When all local methods fail (datacenter IP blocked), this method triggers
a GitHub Actions workflow that runs on GitHub's runners (which have
residential-ish Azure IPs that YouTube doesn't block). The workflow
downloads the video using yt-dlp with Cloudflare WARP, uploads it as a
workflow artifact, and this method downloads the artifact back to our cloud.

Requirements:
  - A GitHub repo (default: Bilal140202/ytagent) with the workflow file
    at .github/workflows/yt-download-farm.yml
  - A GitHub token with `actions` and `contents` scope
  - The workflow must be on the default branch or a branch that exists

Flow:
  1. POST /repos/{owner}/{repo}/actions/workflows/{workflow_id}/dispatches
     with the video URL as input
  2. Poll /repos/{owner}/{repo}/actions/runs until the run completes
  3. GET /repos/{owner}/{repo}/actions/runs/{run_id}/artifacts
  4. Download the artifact ZIP, extract the video file

Latency: ~30-90 seconds (workflow startup + download + artifact upload).
Size limit: 10 GB per artifact, 5 GB per file (GitHub limit).
Cost: Free for public repos (2,000 minutes/month for private, unlimited for public).
"""

from __future__ import annotations

import io
import json
import time
import zipfile
from pathlib import Path
from typing import Any

from .. import log
from .base import MethodResult
from ..utils.net import make_session, safe_request, DEFAULT_UA

NAME = "github_actions_farm"

# Default GitHub configuration. Override via opts.
DEFAULT_GITHUB_OWNER = "Bilal140202"
DEFAULT_GITHUB_REPO = "ytagent"
DEFAULT_WORKFLOW_FILENAME = "yt-download-farm.yml"

# How long to wait for the workflow to complete (seconds).
DEFAULT_WAIT_TIMEOUT = 300

# How often to poll for workflow status (seconds).
POLL_INTERVAL = 10


def _github_api(
    session,
    method: str,
    path: str,
    token: str,
    *,
    json_body: dict | None = None,
    timeout: int = 30,
):
    """Make a GitHub API request. Returns the Response or None."""
    url = f"https://api.github.com{path}"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": DEFAULT_UA,
    }
    return safe_request(
        session, method, url,
        headers=headers,
        json=json_body,
        timeout=timeout,
    )


def _trigger_workflow(
    session, token: str, owner: str, repo: str, workflow: str, video_url: str
) -> int | None:
    """Trigger the download workflow. Returns the workflow run ID or None."""
    # First, trigger the workflow
    path = f"/repos/{owner}/{repo}/actions/workflows/{workflow}/dispatches"
    body = {
        "ref": "main",  # or the branch name
        "inputs": {
            "video_url": video_url,
            "video_id": video_url.split("v=")[-1][:11] if "v=" in video_url else video_url[:11],
        },
    }
    resp = _github_api(session, "POST", path, token, json_body=body)
    if resp is None or resp.status_code != 204:
        log.warn("github_actions_farm: failed to trigger workflow",
                 status=resp.status_code if resp else "no response",
                 body=resp.text[:200] if resp else "")
        return None

    log.info("github_actions_farm: workflow triggered, waiting for run to start")
    # Wait a few seconds for the run to appear
    time.sleep(5)

    # Poll for the latest run
    for attempt in range(20):
        path = f"/repos/{owner}/{repo}/actions/runs?per_page=5"
        resp = _github_api(session, "GET", path, token)
        if resp and resp.status_code == 200:
            data = resp.json()
            runs = data.get("workflow_runs", [])
            for run in runs:
                if run.get("name") == "YT Download Farm" or "download" in run.get("name", "").lower():
                    return run.get("id")
        time.sleep(3)

    log.warn("github_actions_farm: could not find the triggered run")
    return None


def _wait_for_completion(
    session, token: str, owner: str, repo: str, run_id: int, timeout: int
) -> str | None:
    """Wait for a workflow run to complete. Returns the conclusion or None."""
    path = f"/repos/{owner}/{repo}/actions/runs/{run_id}"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        resp = _github_api(session, "GET", path, token)
        if resp and resp.status_code == 200:
            data = resp.json()
            status = data.get("status")
            conclusion = data.get("conclusion")
            if status == "completed":
                return conclusion
            log.debug("github_actions_farm: waiting",
                      status=status, run_id=run_id)
        time.sleep(POLL_INTERVAL)
    log.warn("github_actions_farm: timed out waiting for completion",
             run_id=run_id, timeout=timeout)
    return None


def _download_artifact(
    session, token: str, owner: str, repo: str, run_id: int, out_dir: Path, video_id: str
) -> str | None:
    """Download the workflow artifact and extract the video. Returns the video path or None."""
    path = f"/repos/{owner}/{repo}/actions/runs/{run_id}/artifacts"
    resp = _github_api(session, "GET", path, token)
    if resp is None or resp.status_code != 200:
        return None

    artifacts = resp.json().get("artifacts", [])
    if not artifacts:
        log.warn("github_actions_farm: no artifacts found", run_id=run_id)
        return None

    # Find the video artifact
    artifact = None
    for a in artifacts:
        if "video" in a.get("name", "").lower() or video_id in a.get("name", ""):
            artifact = a
            break
    if artifact is None:
        artifact = artifacts[0]  # take the first one

    # Download the artifact ZIP
    archive_url = artifact["archive_download_url"]
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": DEFAULT_UA,
    }
    try:
        r = session.get(archive_url, headers=headers, timeout=300, stream=False, verify=False)
        if r.status_code != 200:
            log.warn("github_actions_farm: artifact download failed",
                     status=r.status_code)
            return None
    except Exception as e:
        log.warn("github_actions_farm: artifact download error", error=str(e))
        return None

    # Extract the ZIP and find the video file
    try:
        zf = zipfile.ZipFile(io.BytesIO(r.content))
        out_dir.mkdir(parents=True, exist_ok=True)
        video_path = None
        for name in zf.namelist():
            if name.endswith((".mp4", ".webm", ".m4a", ".mkv")):
                target = out_dir / Path(name).name
                target.write_bytes(zf.read(name))
                video_path = str(target)
                break
        if video_path is None:
            # Extract everything and look for the video
            zf.extractall(out_dir)
            for p in out_dir.rglob("*"):
                if p.suffix in (".mp4", ".webm", ".m4a", ".mkv"):
                    video_path = str(p)
                    break
        return video_path
    except Exception as e:
        log.warn("github_actions_farm: ZIP extraction failed", error=str(e))
        return None


def download(
    video_id: str,
    out_dir: Path,
    opts: dict[str, Any] | None = None,
) -> MethodResult:
    """Trigger a GitHub Actions workflow to download the video remotely."""
    started = time.monotonic()
    opts = opts or {}
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    token = opts.get("github_token") or ""
    if not token:
        return MethodResult(
            ok=False,
            reason="github_actions_farm: no github_token in opts",
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    owner = opts.get("github_owner", DEFAULT_GITHUB_OWNER)
    repo = opts.get("github_repo", DEFAULT_GITHUB_REPO)
    workflow = opts.get("github_workflow", DEFAULT_WORKFLOW_FILENAME)
    wait_timeout = opts.get("github_wait_timeout", DEFAULT_WAIT_TIMEOUT)

    session = make_session(retries=1, backoff=2.0)
    video_url = f"https://www.youtube.com/watch?v={video_id}"

    # Step 1: trigger the workflow
    log.info("github_actions_farm: triggering workflow",
             owner=owner, repo=repo, video_id=video_id)
    run_id = _trigger_workflow(session, token, owner, repo, workflow, video_url)
    if run_id is None:
        return MethodResult(
            ok=False,
            reason="github_actions_farm: failed to trigger workflow (check token, repo, workflow file)",
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    # Step 2: wait for completion
    log.info("github_actions_farm: waiting for run", run_id=run_id)
    conclusion = _wait_for_completion(session, token, owner, repo, run_id, wait_timeout)
    if conclusion is None:
        return MethodResult(
            ok=False,
            reason=f"github_actions_farm: timed out after {wait_timeout}s",
            duration_ms=int((time.monotonic() - started) * 1000),
        )
    if conclusion != "success":
        return MethodResult(
            ok=False,
            reason=f"github_actions_farm: workflow concluded as {conclusion}",
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    # Step 3: download the artifact
    log.info("github_actions_farm: downloading artifact", run_id=run_id)
    video_path = _download_artifact(session, token, owner, repo, run_id, out_dir, video_id)
    if video_path is None:
        return MethodResult(
            ok=False,
            reason="github_actions_farm: no video file in artifact",
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    size = Path(video_path).stat().st_size
    elapsed = time.monotonic() - started
    log.success("github_actions_farm: downloaded",
                path=video_path, size=size, elapsed_s=f"{elapsed:.1f}")

    return MethodResult(
        ok=True,
        path=video_path,
        bytes_downloaded=size,
        duration_ms=int(elapsed * 1000),
        reason=f"github_actions_farm: run {run_id} (GitHub runner + WARP)",
    )
