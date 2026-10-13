#!/usr/bin/env bash
# Builds infra/build/api.zip for the mc-ec2-api Lambda.
# PY_VERSION and ARCH must match the Lambda's runtime and architecture.
set -euo pipefail

PY_VERSION="${PY_VERSION:-3.12}"
ARCH="${ARCH:-aarch64}"   # aarch64 for arm64 Lambdas, x86_64 for x86_64 Lambdas

INFRA_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$INFRA_DIR")"
BUILD_DIR="$INFRA_DIR/build"
PKG_DIR="$BUILD_DIR/pkg"

rm -rf "$PKG_DIR" "$BUILD_DIR/api.zip"
mkdir -p "$PKG_DIR/backend"

# Linux wheels only: packages installed for macOS won't load on Lambda.
python3 -m pip install --quiet --no-cache-dir \
  -r "$INFRA_DIR/requirements-lambda.txt" \
  -t "$PKG_DIR" \
  --platform "manylinux2014_${ARCH}" \
  --platform "manylinux_2_28_${ARCH}" \
  --platform "manylinux_2_34_${ARCH}" \
  --implementation cp \
  --python-version "$PY_VERSION" \
  --only-binary=:all:

# Frontend: bake the public Cognito settings into the build and ship dist/ only.
# Assign before export so a failed terraform output stops the script (set -e).
tf_out() { terraform -chdir="$INFRA_DIR" output -raw "$1"; }
VITE_COGNITO_AUTHORITY="$(tf_out cognito_issuer)"
VITE_COGNITO_CLIENT_ID="$(tf_out cognito_client_id)"
VITE_COGNITO_DOMAIN="$(tf_out cognito_login_url)"
VITE_SERVER_IDS="$(tf_out admin_server_id)"
export VITE_COGNITO_AUTHORITY VITE_COGNITO_CLIENT_ID VITE_COGNITO_DOMAIN VITE_SERVER_IDS
(cd "$ROOT_DIR/frontend" && npm ci && npm run build)

# Mirror the repo layout so backend/app.py finds ../frontend/dist.
cp "$INFRA_DIR/lambda_handler.py" "$PKG_DIR/"
cp "$ROOT_DIR"/backend/*.py "$PKG_DIR/backend/"
mkdir -p "$PKG_DIR/frontend"
cp -R "$ROOT_DIR/frontend/dist" "$PKG_DIR/frontend/dist"

find "$PKG_DIR" -name "__pycache__" -type d -prune -exec rm -rf {} +
(cd "$PKG_DIR" && zip -qr -X "$BUILD_DIR/api.zip" .)

echo "Built $BUILD_DIR/api.zip ($(du -h "$BUILD_DIR/api.zip" | cut -f1))"
