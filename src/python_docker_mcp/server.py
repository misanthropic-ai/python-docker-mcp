import asyncio
import uuid

import mcp.server.stdio
import mcp.types as types
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from pydantic import AnyUrl

from .config import load_config
from .docker_manager import DockerManager

# Initialize the Docker manager
docker_manager = DockerManager()

# Store sessions for persistent code execution environments
sessions = {}

server = Server("python-docker-mcp")


@server.list_resources()
async def handle_list_resources() -> list[types.Resource]:
    """
    List available resources.
    Currently there are no resources to list.
    """
    return []


@server.read_resource()
async def handle_read_resource(uri: AnyUrl) -> str:
    """
    Read a specific resource by its URI.
    Currently there are no resources to read.
    """
    raise ValueError(f"Unsupported resource URI: {uri}")


@server.list_prompts()
async def handle_list_prompts() -> list[types.Prompt]:
    """
    List available prompts.
    Currently there are no prompts defined.
    """
    return []


@server.get_prompt()
async def handle_get_prompt(name: str, arguments: dict[str, str] | None) -> types.GetPromptResult:
    """
    Generate a prompt.
    Currently there are no prompts defined.
    """
    raise ValueError(f"Unknown prompt: {name}")


@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """
    List available tools for Python code execution and package management.
    """
    return [
        types.Tool(
            name="execute-transient",
            description="Execute Python code in a transient Docker container that doesn't persist state",
            inputSchema={
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Python code to execute"},
                    "state": {
                        "type": "object",
                        "description": "Optional state dictionary to provide to the execution environment",
                    },
                },
                "required": ["code"],
            },
        ),
        types.Tool(
            name="execute-persistent",
            description="Execute Python code in a persistent Docker container that retains state between calls",
            inputSchema={
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Python code to execute"},
                    "session_id": {
                        "type": "string",
                        "description": "Session identifier for the persistent environment (created automatically if not provided)",
                    },
                },
                "required": ["code"],
            },
        ),
        types.Tool(
            name="install-package",
            description="Install a Python package in a Docker container",
            inputSchema={
                "type": "object",
                "properties": {
                    "package_name": {
                        "type": "string",
                        "description": "Name of the package to install",
                    },
                    "session_id": {
                        "type": "string",
                        "description": "Optional session ID for installing in a persistent environment",
                    },
                },
                "required": ["package_name"],
            },
        ),
        types.Tool(
            name="cleanup-session",
            description="Clean up a persistent session and its resources",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "Session identifier to clean up",
                    },
                },
                "required": ["session_id"],
            },
        ),
    ]


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict | None) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    """
    Handle tool execution requests for Python code execution and package management.
    """
    if not arguments:
        raise ValueError("Missing arguments")

    if name == "execute-transient":
        code = arguments.get("code")
        state = arguments.get("state", {})

        if not code:
            raise ValueError("Missing code")

        result = await docker_manager.execute_transient(code, state)

        return [
            types.TextContent(
                type="text",
                text=_format_execution_result(result),
            )
        ]

    elif name == "execute-persistent":
        code = arguments.get("code")
        session_id = arguments.get("session_id")

        if not code:
            raise ValueError("Missing code")

        # Create a new session if not provided
        if not session_id:
            session_id = str(uuid.uuid4())
            sessions[session_id] = {"created_at": asyncio.get_event_loop().time()}

        result = await docker_manager.execute_persistent(session_id, code)

        return [
            types.TextContent(
                type="text",
                text=_format_execution_result(result, session_id),
            )
        ]

    elif name == "install-package":
        package_name = arguments.get("package_name")
        session_id = arguments.get("session_id")

        if not package_name:
            raise ValueError("Missing package name")

        output = await docker_manager.install_package(session_id, package_name)

        return [
            types.TextContent(
                type="text",
                text=f"Package installation result:\n\n{output}",
            )
        ]

    elif name == "cleanup-session":
        session_id = arguments.get("session_id")

        if not session_id:
            raise ValueError("Missing session ID")

        docker_manager.cleanup_session(session_id)

        if session_id in sessions:
            del sessions[session_id]

        return [
            types.TextContent(
                type="text",
                text=f"Session {session_id} cleaned up successfully",
            )
        ]

    else:
        raise ValueError(f"Unknown tool: {name}")


def _format_execution_result(result, session_id=None):
    """Format execution result for display."""
    if "__stdout__" in result and "__stderr__" in result and "__error__" in result:
        # Transient execution result
        output = result.get("__stdout__", "")
        error = result.get("__error__")
        stderr = result.get("__stderr__", "")

        if error:
            error_text = f"\n\nError: {error}"
        else:
            error_text = ""

        if stderr and not error:
            stderr_text = f"\n\nStandard Error:\n{stderr}"
        else:
            stderr_text = ""

        session_text = f"Session ID: {session_id}\n\n" if session_id else ""

        return f"{session_text}Execution Result:\n\n{output}{stderr_text}{error_text}"
    else:
        # Persistent execution result
        output = result.get("output", "")
        error = result.get("error")

        if error:
            error_text = f"\n\nError: {error}"
        else:
            error_text = ""

        session_text = f"Session ID: {session_id}\n\n" if session_id else ""

        return f"{session_text}Execution Result:\n\n{output}{error_text}"


async def main():
    # Run the server using stdin/stdout streams
    try:
        async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                InitializationOptions(
                    server_name="python-docker-mcp",
                    server_version="0.1.0",
                    capabilities=server.get_capabilities(
                        notification_options=NotificationOptions(),
                        experimental_capabilities={},
                    ),
                ),
            )
    finally:
        # Clean up any remaining sessions when the server shuts down
        docker_manager.cleanup_all_sessions()
