"""Server module for the Python Docker MCP package.

This module provides the MCP server implementation that handles API requests
and dispatches them to the Docker execution environment.
"""

import asyncio
import logging
import os
import sys
import uuid
from typing import Any, Dict

import mcp.server.stdio
import mcp.types as types
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from pydantic import AnyUrl

from .config import load_config
from .docker_manager import DockerManager

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("python-docker-mcp")

# Initialize the configuration
config = load_config()

# Initialize the Docker manager
docker_manager = DockerManager(config)

# Store sessions for persistent code execution environments
sessions = {}

# Create the MCP server
server = Server("python-docker-mcp")


@server.list_resources()
async def handle_list_resources() -> list[types.Resource]:
    """List available resources.

    Currently there are no resources to list.
    """
    return []


@server.read_resource()
async def handle_read_resource(uri: AnyUrl) -> str:
    """Read a specific resource by its URI.

    Currently there are no resources to read.
    """
    raise ValueError(f"Unsupported resource URI: {uri}")


@server.list_prompts()
async def handle_list_prompts() -> list[types.Prompt]:
    """List available prompts.

    Currently there are no prompts defined.
    """
    return []


@server.get_prompt()
async def handle_get_prompt(name: str, arguments: dict[str, str] | None) -> types.GetPromptResult:
    """Generate a prompt.

    Currently there are no prompts defined.
    """
    raise ValueError(f"Unknown prompt: {name}")


@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """List available tools that can be called by clients."""
    logger.info("Listing tools")
    return [
        types.Tool(
            name="execute-transient",
            description="Execute Python code in a transient Docker container",
            inputSchema={
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Python code to execute"},
                    "state": {"type": "object", "description": "Optional state dictionary"},
                },
                "required": ["code"],
            },
        ),
        types.Tool(
            name="execute-persistent",
            description="Execute Python code in a persistent Docker container",
            inputSchema={
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Python code to execute"},
                    "session_id": {"type": "string", "description": "Session identifier"},
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
                    "package_name": {"type": "string", "description": "Package name"},
                    "session_id": {"type": "string", "description": "Optional session ID"},
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
                    "session_id": {"type": "string", "description": "Session identifier"},
                },
                "required": ["session_id"],
            },
        ),
    ]


def _format_execution_result(result: Dict[str, Any]) -> str:
    """Format the execution result for the MCP response."""
    # Check for either new-style or old-style result format
    if "status" in result and result.get("status") == "error":
        error = result.get("error", "Unknown error occurred")
        error_info = result.get("error_info", {})
        stdout = result.get("stdout", "")
        stderr = result.get("stderr", "")

        return f"Error: {error}\nError Info: {error_info}\nOutput: {stdout}\nError Output: {stderr}"

    # Handle the test-expected format with __stdout__ format
    if "__stdout__" in result:
        stdout = result.get("__stdout__", "")
        stderr = result.get("__stderr__", "")
        error = result.get("__error__")

        output = f"Execution Result:\n\n{stdout}"

        if stderr:
            output += f"\n\nStandard Error:\n{stderr}"

        if error:
            output += f"\n\nError: {error}"

        return output

    # For successful execution in the new format, return the output
    return result.get("stdout", "")


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict | None) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    """Handle tool execution requests for Python code execution and package management."""
    logger.info(f"Calling tool: {name}")

    try:
        if not arguments:
            raise ValueError("Missing arguments")

        if name == "execute-transient":
            code = arguments.get("code")
            state = arguments.get("state", {})

            if not code:
                raise ValueError("Missing code")

            raw_result = await docker_manager.execute_transient(code, state)

            # If the result is already in the expected format (for tests), use it directly
            if "__stdout__" in raw_result:
                result = raw_result
            else:
                # Map the docker manager response to the format expected by tests
                result = {
                    "__stdout__": raw_result.get("stdout", ""),
                    "__stderr__": raw_result.get("stderr", ""),
                    "__error__": raw_result.get("error"),
                    "result": raw_result.get("result", raw_result.get("exit_code", 0)),
                }

            output = _format_execution_result(result)
            return [types.TextContent(type="text", text=output)]

        elif name == "execute-persistent":
            code = arguments.get("code")
            session_id = arguments.get("session_id")

            if not code:
                raise ValueError("Missing code")

            # Create a new session if not provided
            if not session_id:
                session_id = str(uuid.uuid4())
                sessions[session_id] = {"created_at": asyncio.get_event_loop().time()}

            raw_result = await docker_manager.execute_persistent(session_id, code)

            # If the result is already in the expected format (for tests), use it directly
            if "__stdout__" in raw_result:
                result = raw_result
            else:
                # Map the docker manager response to the format expected by tests
                result = {
                    "__stdout__": raw_result.get("stdout", ""),
                    "__stderr__": raw_result.get("stderr", ""),
                    "__error__": raw_result.get("error"),
                    "result": raw_result.get("result", raw_result.get("exit_code", 0)),
                    "session_id": session_id,
                }

            output = f"Session ID: {session_id}\n\n{_format_execution_result(result)}"
            return [types.TextContent(type="text", text=output)]

        elif name == "install-package":
            package_name = arguments.get("package_name")
            session_id = arguments.get("session_id")

            if not package_name:
                raise ValueError("Missing package name")

            output = await docker_manager.install_package(session_id, package_name)
            return [types.TextContent(type="text", text=f"Package installation result:\n\n{output}")]

        elif name == "cleanup-session":
            session_id = arguments.get("session_id")

            if not session_id:
                raise ValueError("Missing session ID")

            result = await docker_manager.cleanup_session(session_id)

            if session_id in sessions:
                del sessions[session_id]

            return [types.TextContent(type="text", text=f"Session {session_id} cleaned up successfully")]

        else:
            raise ValueError(f"Unknown tool: {name}")
    except Exception as e:
        logger.error(f"Error executing tool {name}: {str(e)}")
        import traceback

        logger.error(traceback.format_exc())

        # Return a properly formatted error response
        error_message = f"Error executing {name}: {str(e)}"
        return [types.TextContent(type="text", text=error_message)]


async def main() -> None:
    """Start the MCP server."""
    # Configure logging based on debug flag from command line or environment
    debug_mode = "--debug" in sys.argv or os.environ.get("PYTHON_DOCKER_MCP_DEBUG", "").lower() in ["true", "1", "yes"]

    if debug_mode:
        logging.basicConfig(level=logging.DEBUG)
        logger.setLevel(logging.DEBUG)
        logger.debug("Debug mode enabled")
    else:
        # Set info level logging by default for better diagnostics
        logging.basicConfig(level=logging.INFO)

    # Initialize the container pool if enabled
    if config.docker.pool_enabled:
        logger.info("Initializing container pool")
        try:
            await docker_manager.initialize_pool()
        except Exception as e:
            logger.error(f"Error initializing container pool: {e}")
            # Don't disable pooling, just log the error and continue
            # The system will fall back to creating containers on demand

    # Run the server using stdin/stdout streams
    logger.info("Starting MCP server using stdio transport")
    try:
        async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
            logger.info("stdio server initialized, running MCP server")
            await server.run(
                read_stream,
                write_stream,
                InitializationOptions(
                    server_name="python-docker-mcp",
                    server_version="0.2.2",
                    capabilities=server.get_capabilities(
                        notification_options=NotificationOptions(),
                        experimental_capabilities={},
                    ),
                ),
            )
    except Exception as e:
        logger.error(f"Error running MCP server: {e}")
        import traceback

        logger.error(traceback.format_exc())
        raise
    finally:
        # Clean up any remaining sessions when the server shuts down
        logger.info("Cleaning up sessions")
        
        cleanup_tasks = []
        for session_id in list(sessions.keys()):
            logger.info(f"Scheduling cleanup for session {session_id}")
            # Create a task for each cleanup operation
            task = asyncio.create_task(
                docker_manager.cleanup_session(session_id), 
                name=f"cleanup-{session_id}"
            )
            cleanup_tasks.append(task)

        if cleanup_tasks:
            # Run cleanup tasks concurrently with a timeout
            done, pending = await asyncio.wait(
                cleanup_tasks, 
                timeout=10.0  # Adjust timeout as needed (e.g., 10 seconds)
            )

            # Log results and handle pending tasks
            for task in done:
                try:
                    await task  # Raise exceptions if cleanup failed
                    logger.info(f"Session cleanup completed for task {task.get_name()}")
                except Exception as e:
                    logger.error(f"Error during cleanup task {task.get_name()}: {e}")
            
            if pending:
                logger.warning(f"{len(pending)} cleanup tasks did not complete within the timeout.")
                # Optionally, attempt to cancel pending tasks
                for task in pending:
                    task.cancel()
                    try:
                        await task # Allow cancellation to propagate
                    except asyncio.CancelledError:
                        logger.info(f"Cancelled pending cleanup task {task.get_name()}")
                    except Exception as e:
                         logger.error(f"Error cancelling pending task {task.get_name()}: {e}")

        # Clean up the sessions dictionary itself (optional, but good practice)
        sessions.clear() 
        
        # Consider explicitly cleaning up the DockerManager's pool if needed
        # try:
        #    await docker_manager.shutdown_pool() # Assuming such a method exists
        # except Exception as e:
        #    logger.error(f"Error shutting down Docker pool: {e}")

        logger.info("Server shutdown cleanup process finished.")


# If this module is run directly, start the server
if __name__ == "__main__":
    asyncio.run(main())
