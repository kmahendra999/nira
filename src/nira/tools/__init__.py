"""Tools primitive — tool system with ABC interface and built-in tools."""

from __future__ import annotations

from nira.tools._stubs import BaseTool, ToolExecutor, ToolSpec

# Import built-in tools to trigger @ToolRegistry.register() decorators.
# Each is wrapped in try/except so the package loads even before the
# individual tool modules are created.
try:
    import nira.tools.calculator  # noqa: F401
except ImportError:
    pass

try:
    import nira.tools.think  # noqa: F401
except ImportError:
    pass

try:
    import nira.tools.retrieval  # noqa: F401
except ImportError:
    pass

try:
    import nira.tools.llm_tool  # noqa: F401
except ImportError:
    pass

try:
    import nira.tools.file_read  # noqa: F401
except ImportError:
    pass

try:
    import nira.tools.web_search  # noqa: F401
except ImportError:
    pass

try:
    import nira.tools.weather  # noqa: F401
except ImportError:
    pass

try:
    import nira.tools.code_interpreter  # noqa: F401
except ImportError:
    pass

try:
    import nira.tools.code_interpreter_docker  # noqa: F401
except ImportError:
    pass

try:
    import nira.tools.repl  # noqa: F401
except ImportError:
    pass

try:
    import nira.tools.storage_tools  # noqa: F401
except ImportError:
    pass

try:
    import nira.tools.mcp_adapter  # noqa: F401
except ImportError:
    pass

try:
    import nira.tools.channel_tools  # noqa: F401
except ImportError:
    pass

try:
    import nira.tools.http_request  # noqa: F401
except ImportError:
    pass

try:
    import nira.tools.docker_shell_exec  # noqa: F401
    import nira.tools.shell_exec  # noqa: F401
except ImportError:
    pass

try:
    import nira.tools.memory_manage  # noqa: F401
except ImportError:
    pass
try:
    import nira.tools.user_profile_manage  # noqa: F401
except ImportError:
    pass

try:
    import nira.tools.skill_manage  # noqa: F401
except ImportError:
    pass

try:
    import nira.tools.file_write  # noqa: F401
except ImportError:
    pass

try:
    import nira.tools.apply_patch  # noqa: F401
except ImportError:
    pass

try:
    import nira.tools.git_tool  # noqa: F401
except ImportError:
    pass

try:
    import nira.tools.db_query  # noqa: F401
except ImportError:
    pass

try:
    import nira.tools.pdf_tool  # noqa: F401
except ImportError:
    pass

try:
    import nira.tools.image_tool  # noqa: F401
except ImportError:
    pass

try:
    import nira.tools.audio_tool  # noqa: F401
except ImportError:
    pass

try:
    import nira.tools.knowledge_tools  # noqa: F401
except ImportError:
    pass

try:
    import nira.tools.text_to_speech  # noqa: F401
except ImportError:
    pass

try:
    import nira.tools.digest_collect  # noqa: F401
except ImportError:
    pass

try:
    import nira.tools.scan_chunks  # noqa: F401
except ImportError:
    pass

try:
    import nira.tools.knowledge_sql  # noqa: F401
except ImportError:
    pass

try:
    import nira.tools.apple_calendar  # noqa: F401
except ImportError:
    pass

__all__ = ["BaseTool", "ToolExecutor", "ToolSpec"]
