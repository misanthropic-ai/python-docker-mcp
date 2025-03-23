"""Client module for interacting with the python-docker-mcp server."""

import asyncio
import os
import re
import sys
from contextlib import AsyncExitStack
from typing import Any, Dict, List, Optional, Tuple

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class PythonDockerClient:
    """Client for interacting with the Python Docker MCP server."""

    def __init__(self) -> None:
        """Initialize the client."""
        self.session: Optional[ClientSession] = None
        self.exit_stack = AsyncExitStack()

    async def connect_to_server(self, server_script_path: Optional[str] = None) -> None:
        """Connect to the MCP server.

        Args:
            server_script_path: Optional path to the server script
                                If None, uses module name directly
        """
        server_env = os.environ.copy()

        if server_script_path:
            is_python = server_script_path.endswith(".py")
            is_js = server_script_path.endswith(".js")
            if not (is_python or is_js):
                raise ValueError("Server script must be a .py or .js file")

            command = "python" if is_python else "node"
            server_params = StdioServerParameters(command=command, args=[server_script_path], env=server_env)
        else:
            # Use the module directly
            server_params = StdioServerParameters(command=sys.executable, args=["-m", "python_docker_mcp"], env=server_env)

        stdio_transport = await self.exit_stack.enter_async_context(stdio_client(server_params))
        read_stream, write_stream = stdio_transport
        self.session = await self.exit_stack.enter_async_context(ClientSession(read_stream, write_stream))

        await self.session.initialize()

    async def list_tools(self) -> List[Dict[str, Any]]:
        """List available tools on the server."""
        self._ensure_connected()

        response = await self.session.list_tools()
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.inputSchema,
            }
            for tool in response.tools
        ]

    async def execute_transient(self, code: str, state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Execute code in a transient container.

        Args:
            code: Python code to execute
            state: Optional state to provide to the execution environment

        Returns:
            Dictionary containing execution results and state
        """
        self._ensure_connected()

        args = {"code": code}
        if state:
            args["state"] = state

        response = await self.session.call_tool("execute-transient", args)
        result_text = response.content[0].text

        # Parse the result to extract state information
        result = {"raw_output": result_text}

        # Check for error
        error_match = re.search(r"Error: (.+)$", result_text, re.MULTILINE)
        if error_match:
            result["error"] = error_match.group(1)
        else:
            result["error"] = None

        # Extract stdout
        # This is a simplified approach - in a real implementation, you might need
        # more sophisticated parsing based on the format of your output
        execution_start = result_text.find("Execution Result:")
        if execution_start >= 0:
            output_text = result_text[execution_start + len("Execution Result:") :].strip()
            if result["error"]:
                error_start = output_text.find("Error:")
                if error_start >= 0:
                    output_text = output_text[:error_start].strip()
            result["output"] = output_text

        return result

    async def execute_persistent(self, code: str, session_id: Optional[str] = None) -> Tuple[Dict[str, Any], str]:
        """Execute code in a persistent container.

        Args:
            code: Python code to execute
            session_id: Optional session ID to use (creates new if None)

        Returns:
            Tuple of (execution_results, session_id)
        """
        self._ensure_connected()

        args = {"code": code}
        if session_id:
            args["session_id"] = session_id

        response = await self.session.call_tool("execute-persistent", args)
        result_text = response.content[0].text

        # Extract session ID
        session_match = re.search(r"Session ID: ([a-f0-9-]+)", result_text)
        current_session_id = session_match.group(1) if session_match else session_id

        # Parse the result
        result = {"raw_output": result_text}

        # Check for error
        error_match = re.search(r"Error: (.+)$", result_text, re.MULTILINE)
        if error_match:
            result["error"] = error_match.group(1)
        else:
            result["error"] = None

        # Extract stdout
        execution_start = result_text.find("Execution Result:")
        if execution_start >= 0:
            output_text = result_text[execution_start + len("Execution Result:") :].strip()
            if result["error"]:
                error_start = output_text.find("Error:")
                if error_start >= 0:
                    output_text = output_text[:error_start].strip()
            result["output"] = output_text

        if current_session_id is None:
            raise RuntimeError("Failed to extract session ID from response")

        return result, current_session_id

    async def install_package(self, package_name: str, session_id: Optional[str] = None) -> Dict[str, Any]:
        """Install a Python package in a container.

        Args:
            package_name: Name of the package to install
            session_id: Optional session ID for installing in a persistent environment

        Returns:
            Dictionary containing installation results
        """
        self._ensure_connected()

        args = {"package_name": package_name}
        if session_id:
            args["session_id"] = session_id

        response = await self.session.call_tool("install-package", args)
        result_text = response.content[0].text

        # Parse the result
        result = {"raw_output": result_text, "package_name": package_name}

        # Check if installation was successful
        if "Successfully installed" in result_text:
            result["success"] = True
        else:
            result["success"] = False

        return result

    async def cleanup_session(self, session_id: str) -> bool:
        """Clean up a persistent session.

        Args:
            session_id: Session ID to clean up

        Returns:
            True if cleanup was successful
        """
        self._ensure_connected()

        args = {"session_id": session_id}
        response = await self.session.call_tool("cleanup-session", args)
        result_text = response.content[0].text

        return "cleaned up successfully" in result_text

    async def close(self) -> None:
        """Close the connection to the server."""
        await self.exit_stack.aclose()
        self.session = None

    def _ensure_connected(self) -> None:
        """Ensure that the client is connected to the server."""
        if not self.session:
            raise RuntimeError("Not connected to server. Call connect_to_server() first.")


async def main() -> None:
    """Run a simple demo of the client."""
    client = PythonDockerClient()

    try:
        print("Connecting to MCP server...")
        await client.connect_to_server()

        print("Listing tools...")
        tools = await client.list_tools()
        for tool in tools:
            print(f"- {tool['name']}: {tool['description']}")

        print("\nExecuting transient code...")
        result = await client.execute_transient("x = 42\nprint(f'The answer is {x}')")
        print(f"Result: {result}")

        print("\nExecuting persistent code...")
        result, session_id = await client.execute_persistent("y = 84\nprint(f'Twice the answer is {y}')")
        print(f"Result: {result}")
        print(f"Session ID: {session_id}")

        print("\nExecuting more code in the same session...")
        result2, _ = await client.execute_persistent("z = y / 2\nprint(f'Back to the answer: {z}')", session_id)
        print(f"Result: {result2}")

        print("\nCleaning up session...")
        success = await client.cleanup_session(session_id)
        print(f"Cleanup successful: {success}")

    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
