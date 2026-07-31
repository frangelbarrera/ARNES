"""Docker sandbox detection for the PlaybookExecutor.

Holds the default sandbox container image name and the
``_is_docker_available`` presence check used by the executor to auto-wire
the Docker sandbox into the default ``ToolContext``.
"""

from __future__ import annotations

import shutil

# Default Docker image used by the ShellTool sandbox. The image is expected
# to be present locally (built via `docker build -t arnes-sandbox:latest .`
# from the project's Dockerfile.sandbox). The ShellTool falls back to a
# clear error message if the daemon or image is missing at execution time.
DEFAULT_SANDBOX_CONTAINER = "arnes-sandbox:latest"


def _is_docker_available() -> bool:
    """Return True if the ``docker`` CLI is on PATH.

    Used by the executor to decide whether to wire the Docker sandbox into
    the default ``ToolContext``. This is a presence check only — it does NOT
    verify the daemon is running or that ``arnes-sandbox:latest`` exists.
    The ``ShellTool`` surfaces a clear error if either is missing at
    execution time (``FileNotFoundError`` on ``docker run``).

    We deliberately avoid probing the daemon (``docker info`` / ``docker
    version``) here because:

    1. It spawns a subprocess on every ``PlaybookExecutor`` construction,
       which is wasteful for tests and high-throughput runs.
    2. The daemon may be temporarily down even if the CLI is installed —
       failing fast at construction time would prevent the user from
       running non-shell playbooks that don't need Docker at all.
    3. The ``ShellTool._execute_in_sandbox`` already handles the
       ``FileNotFoundError`` case (docker binary missing) and returns a
       actionable error message.
    """
    return shutil.which("docker") is not None
