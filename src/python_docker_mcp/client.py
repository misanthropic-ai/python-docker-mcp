"""Client module for interacting with the python-docker-mcp server."""

import asyncio
import re
from typing import Dict, List, Optional, Any, Tuple

import mcp.types as types
from mcp import ClientSession


class PythonDockerClient:
    """Client for interacting with the Python Docker MCP server."""

    def __init__(self, mcp_client=None):
        """Initialize the client.
        
        Args:
            mcp_client: Optional MCP client instance to use. If None, the caller must handle
                        client initialization separately.
        """
        self._mcp_client = mcp_client

    async def list_tools(self) -> List[types.Tool]:
        """List available tools on the server.
        
        Returns:
            List of available tools
        """
        return await self._mcp_client.list_tools()

    async def execute_transient(self, code: str, state: Optional[Dict[str, Any]] = None) -> str:
        """Execute code in a transient container.

        Args:
            code: Python code to execute
            state: Optional state to provide to the execution environment

        Returns:
            Formatted execution result as a string
        """
        if state is None:
            state = {}

        response = await self._mcp_client.call_tool("execute-transient", {"code": code, "state": state})
        if response and len(response) > 0 and hasattr(response[0], "text"):
            return response[0].text
        return "No execution result returned"

    async def execute_persistent(self, code: str, session_id: Optional[str] = None) -> str:
        """Execute code in a persistent container.

        Args:
            code: Python code to execute
            session_id: Optional session ID to use (creates new if None)

        Returns:
            Formatted execution result as a string with session ID information
        """
        args = {"code": code}
        if session_id:
            args["session_id"] = session_id

        response = await self._mcp_client.call_tool("execute-persistent", args)
        if response and len(response) > 0 and hasattr(response[0], "text"):
            return response[0].text
        return "No execution result returned"

    async def install_package(self, package_name: str, session_id: Optional[str] = None) -> str:
        """Install a Python package in a container.

        Args:
            package_name: Name of the package to install
            session_id: Optional session ID for installing in a persistent environment

        Returns:
            Installation result as a string
        """
        args = {"package_name": package_name}
        if session_id:
            args["session_id"] = session_id

        response = await self._mcp_client.call_tool("install-package", args)
        if response and len(response) > 0 and hasattr(response[0], "text"):
            return response[0].text
        return "No installation result returned"

    async def cleanup_session(self, session_id: str) -> str:
        """Clean up a persistent session.

        Args:
            session_id: Session ID to clean up

        Returns:
            Cleanup result as a string
        """
        response = await self._mcp_client.call_tool("cleanup-session", {"session_id": session_id})
        if response and len(response) > 0 and hasattr(response[0], "text"):
            return response[0].text
        return "No cleanup result returned"

    def _extract_session_id(self, text: str) -> Optional[str]:
        """Extract session ID from response text.
        
        Args:
            text: Response text to parse
            
        Returns:
            Session ID if found, None otherwise
        """
        session_match = re.search(r"Session ID: ([a-f0-9-]+)", text)
        return session_match.group(1) if session_match else None

    async def execute_code_blocks(self, code_blocks: List[str], shared_state: bool = False, persistent: bool = False) -> List[str]:
        """Execute multiple code blocks in sequence.
        
        Args:
            code_blocks: List of code blocks to execute
            shared_state: If True, state is shared between transient executions
            persistent: If True, code blocks are executed in a persistent session
            
        Returns:
            List of execution results
        """
        results = []
        state = {}
        session_id = None
        
        for code in code_blocks:
            if persistent:
                result = await self.execute_persistent(code, session_id)
                if not session_id:
                    # Extract the session ID from the first execution result
                    session_id = self._extract_session_id(result)
                    if not session_id:
                        raise ValueError("Failed to extract session ID from persistent execution result")
                results.append(result)
            elif shared_state:
                result = await self.execute_transient(code, state)
                results.append(result)
                # We'd need to parse the state back from the result in a real implementation
            else:
                result = await self.execute_transient(code)
                results.append(result)
        
        return results


async def main() -> None:
    """Run a simple demo of the client."""
    # For a real example, we'd need to set up a client session first
    try:
        print("This is just a demo script showing API usage.")
        print("To use this as a real client, you need to:")
        print("1. Create a ClientSession and connect to a server")
        print("2. Pass the session to PythonDockerClient")
        print("3. Use the client methods to interact with the server")
        
        print("\nExample usage would look like:")
        print("client = PythonDockerClient(session)")
        print("tools = await client.list_tools()")
        print("result = await client.execute_transient('print(\"Hello, world!\")')")
        
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    asyncio.run(main())
