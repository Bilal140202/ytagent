#!/usr/bin/env bash
# publish_pypi.sh — publish ytagent to PyPI.
#
# Prerequisites:
#   1. Get a PyPI API token from https://pypi.org/manage/account/token/ (scope: "Entire account")
#   2. Export it as an env var:
#        export TWINE_PASSWORD=pypi-xxxxxxxxxxxxxxxxxxxxxxxxxxxx
#      (TWINE_USERNAME should be "__token__")
#
# Usage:
#   bash scripts/publish_pypi.sh              # publish to real PyPI
#   bash scripts/publish_pypi.sh --test       # publish to TestPyPI first (recommended)

set -euo pipefail

cd "$(dirname "$0")/.."

TEST_MODE="${1:-}"
if [ "$TEST_MODE" = "--test" ]; then
    REPOSITORY="testpypi"
    echo "=== Publishing to TestPyPI ==="
    echo "View at: https://test.pypi.org/project/ytagent/"
else
    REPOSITORY="pypi"
    echo "=== Publishing to PyPI ==="
    echo "View at: https://pypi.org/project/ytagent/"
fi

# Verify TWINE_PASSWORD is set.
if [ -z "${TWINE_PASSWORD:-}" ]; then
    echo "ERROR: TWINE_PASSWORD is not set."
    echo "Get a PyPI API token from https://pypi.org/manage/account/token/"
    echo "Then: export TWINE_PASSWORD=pypi-xxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    exit 1
fi

export TWINE_USERNAME="__token__"

# Clean previous builds.
echo "Cleaning previous builds..."
rm -rf dist/ build/ src/ytagent.egg-info

# Build.
echo "Building package..."
python3 -m build

# Check.
echo "Checking package..."
python3 -m twine check dist/*

# Upload.
echo "Uploading to $REPOSITORY..."
python3 -m twine upload --repository "$REPOSITORY" dist/*

echo ""
echo "=== Done ==="
if [ "$REPOSITORY" = "testpypi" ]; then
    echo "Test install with:"
    echo "  pip install --index-url https://test.pypi.org/simple/ ytagent"
else
    echo "Anyone can now install with:"
    echo "  pip install ytagent"
fi
