#!/usr/bin/env bash
# scripts/build-sandbox.sh — build the arnes-sandbox:latest Docker image.
#
# This is the Tier 1 dev-local sandbox image ARNES specialists use to run
# untrusted code. See Dockerfile.sandbox for the runtime hardening flags.
#
# Usage:
#   scripts/build-sandbox.sh                # build arnes-sandbox:latest
#   scripts/build-sandbox.sh --tag v0.2     # also tag arnes-sandbox:v0.2
#   scripts/build-sandbox.sh --check        # build, then run a smoke test
#
# Requirements: Docker (or a drop-in like `podman`/`buildah`) on PATH.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

IMAGE_NAME="arnes-sandbox"
IMAGE_TAG="latest"
EXTRA_TAGS=()
RUN_SMOKE=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --tag)
            EXTRA_TAGS+=("$2")
            shift 2
            ;;
        --check)
            RUN_SMOKE=1
            shift
            ;;
        -h|--help)
            sed -n '2,12p' "$0"
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            exit 64
            ;;
    esac
done

# Pick the container CLI: prefer Docker, fall back to Podman (same CLI shape).
if command -v docker >/dev/null 2>&1; then
    CLI=(docker)
elif command -v podman >/dev/null 2>&1; then
    CLI=(podman)
else
    echo "ERROR: neither 'docker' nor 'podman' found on PATH." >&2
    echo "Install Docker Desktop, or: brew install podman && podman machine init" >&2
    exit 127
fi

echo "→ Building ${IMAGE_NAME}:${IMAGE_TAG} using ${CLI[*]} ..."
"${CLI[@]}" build \
    -f Dockerfile.sandbox \
    -t "${IMAGE_NAME}:${IMAGE_TAG}" \
    .

for tag in "${EXTRA_TAGS[@]:-}"; do
    [[ -z "$tag" ]] && continue
    echo "→ Tagging ${IMAGE_NAME}:${tag} ..."
    "${CLI[@]}" tag "${IMAGE_NAME}:${IMAGE_TAG}" "${IMAGE_NAME}:${tag}"
done

if [[ "$RUN_SMOKE" -eq 1 ]]; then
    echo "→ Smoke test: run python3 -c 'print(...)' under Tier 1 hardening ..."
    "${CLI[@]}" run --rm \
        --network=none \
        --read-only \
        --security-opt=no-new-privileges \
        -u 1000:1000 \
        --tmpfs /tmp:rw,size=64m,mode=1777 \
        --tmpfs /workspace:rw,size=128m,mode=1777 \
        "${IMAGE_NAME}:${IMAGE_TAG}" \
        python3 -c 'import sys; print("arnes-sandbox ok:", sys.version.split()[0]); sys.exit(0)'
fi

echo "✅ Built ${IMAGE_NAME}:${IMAGE_TAG}"
echo
echo "Run with Tier 1 hardening:"
echo "  ${CLI[*]} run --rm \\"
echo "    --network=none --read-only --security-opt=no-new-privileges \\"
echo "    -u 1000:1000 \\"
echo "    --tmpfs /tmp:rw,size=64m,mode=1777 \\"
echo "    --tmpfs /workspace:rw,size=128m,mode=1777 \\"
echo "    ${IMAGE_NAME}:${IMAGE_TAG} python3 -c '...'"
