"""Task domain enumeration for the playbook library."""

from __future__ import annotations

from enum import StrEnum


class TaskDomain(StrEnum):
    """The task domains ARNES ships pre-built playbook templates for.

    The value of each member is the canonical template name used by
    ``arnes plan --template <name>`` and returned by :class:`TaskRouter`.
    """

    SOFTWARE_MOBILE = "mobile_app"
    SOFTWARE_WEB = "web_app"
    SOFTWARE_CLI = "cli_tool"
    SOFTWARE_API = "rest_api"
    OSINT = "osint"
    FINANCIAL_ANALYSIS = "financial_analysis"
    SECURITY_AUDIT = "security_audit"
    DATA_ANALYSIS = "data_analysis"
    DEVOPS = "devops"
    DESIGN = "graphic_design"
    CONTENT = "content_creation"
    RESEARCH = "academic_research"
    GENERIC = "generic"
