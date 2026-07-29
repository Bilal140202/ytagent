"""Generate test fixtures for the Verifier unit tests.

Creates:
  - fixtures/valid_5s.mp4 — a real 5-second MP4 with video+audio
  - fixtures/truncated.mp4 — a truncated MP4 (head only, no moov at the end)
  - fixtures/not_a_video.txt — an HTML error page saved as .mp4
"""
import subprocess
from pathlib import Path

FIXTURES = Path(__file__).parent.parent / "fixtures"
FIXTURES.mkdir(parents=True, exist_ok=True)


def make_valid_mp4():
    out = FIXTURES / "valid_5s.mp4"
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "testsrc=duration=5:size=320x240:rate=30",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=5",
        "-c:v", "libx264", "-c:a", "aac",
        "-movflags", "+faststart",
        str(out),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    print(f"created {out} ({out.stat().st_size} bytes)")


def make_truncated_mp4():
    # First make a valid MP4 with moov at the END (no +faststart).
    src = FIXTURES / "_trunc_src.mp4"
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "testsrc=duration=5:size=320x240:rate=30",
        "-c:v", "libx264",
        str(src),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    # Now truncate it: take only the first 60% of the file (cuts off moov).
    size = src.stat().st_size
    out = FIXTURES / "truncated.mp4"
    with src.open("rb") as fin, out.open("wb") as fout:
        fout.write(fin.read(int(size * 0.6)))
    src.unlink()
    print(f"created {out} ({out.stat().st_size} bytes)")


def make_html_fake():
    out = FIXTURES / "not_a_video.txt"
    out.write_text(
        "<!DOCTYPE html><html><head><title>Video unavailable</title></head>"
        "<body>This video is unavailable.</body></html>",
        encoding="utf-8",
    )
    print(f"created {out} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    make_valid_mp4()
    make_truncated_mp4()
    make_html_fake()
    print("done")
