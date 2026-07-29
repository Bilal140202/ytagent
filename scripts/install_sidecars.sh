#!/usr/bin/env bash
# install_sidecars.sh — set up the BGutil POT provider (required for datacenter IPs).
#
# This script does NOT require Docker. It clones the BGutil server, installs
# Node.js deps, and compiles the TypeScript. The HTTP server is optional —
# without it, ytagent falls back to script-node mode (spawns `node` per call).
#
# Usage:
#   bash scripts/install_sidecars.sh
#   nohup node /home/z/bgutil-ytdlp-pot-provider/server/build/main.js --port 4416 &

set -euo pipefail

BGUTIL_HOME="${BGUTIL_HOME:-/home/z/bgutil-ytdlp-pot-provider}"

echo "=== Installing BGutil POT provider ==="

# 1. Clone the repo if not present.
if [ ! -d "$BGUTIL_HOME" ]; then
    echo "Cloning bgutil-ytdlp-pot-provider to $BGUTIL_HOME..."
    git clone --depth=1 https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git "$BGUTIL_HOME"
else
    echo "Found existing clone at $BGUTIL_HOME."
fi

# 2. Install Node.js deps.
echo "Installing Node.js dependencies..."
cd "$BGUTIL_HOME/server"
npm install --production

# 3. Install TypeScript compiler if not present.
if [ ! -f "node_modules/.bin/tsc" ]; then
    echo "Installing TypeScript..."
    npm install typescript
fi

# 4. Compile TypeScript.
echo "Compiling TypeScript..."
./node_modules/.bin/tsc

# 5. Verify the build.
if [ -f "build/main.js" ]; then
    echo "✅ BGutil server built successfully at $BGUTIL_HOME/server/build/main.js"
else
    echo "❌ Build failed — no build/main.js produced."
    exit 1
fi

# 6. Install the Python plugin into the active Python.
echo "Installing bgutil-ytdlp-pot-provider Python package..."
pip install bgutil-ytdlp-pot-provider || pip3 install bgutil-ytdlp-pot-provider

echo ""
echo "=== Setup complete ==="
echo ""
echo "To start the HTTP server (optional, faster token generation):"
echo "  nohup node $BGUTIL_HOME/server/build/main.js --port 4416 > /tmp/bgutil-server.log 2>&1 &"
echo ""
echo "To verify:"
echo "  curl http://127.0.0.1:4416/ping"
echo ""
echo "ytagent will auto-detect the server if running, and fall back to"
echo "script-node mode if not."
