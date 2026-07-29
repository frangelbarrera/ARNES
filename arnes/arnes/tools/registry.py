"""Default tool registry with all built-in tools registered."""

from arnes.tools.base import ToolRegistry
from arnes.tools.builtin import (
    FilesystemReadTool,
    FilesystemWriteTool,
    HttpTool,
    HumanApprovalTool,
    ShellTool,
)


def get_default_registry() -> ToolRegistry:
    """Return a fresh ToolRegistry with all built-in tools registered."""
    registry = ToolRegistry()
    for tool_class in [
        ShellTool,
        HttpTool,
        FilesystemReadTool,
        FilesystemWriteTool,
        HumanApprovalTool,
    ]:
        registry.register_class(tool_class)
    return registry
