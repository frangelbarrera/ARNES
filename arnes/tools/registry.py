"""Default tool registry with all built-in tools registered."""

from arnes.tools.base import Tool, ToolRegistry
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
    # Concrete subclasses of the abstract ``Tool`` base. Annotated explicitly
    # so mypy does not infer ``type[Tool]`` (which is abstract and rejected).
    tool_classes: tuple[type[Tool], ...] = (
        ShellTool,
        HttpTool,
        FilesystemReadTool,
        FilesystemWriteTool,
        HumanApprovalTool,
    )
    for tool_class in tool_classes:
        registry.register_class(tool_class)
    return registry
