"""Integration tests for the MCP client interaction with the server."""

import asyncio
import os
import subprocess
import sys
import tempfile
import time
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

import pytest
from mcp import ClientSession, McpError, StdioServerParameters
from mcp.client.stdio import stdio_client


class TestMCPClient:
    """Integration tests for the MCP client."""

    @pytest.fixture
    async def client_session(self) -> AsyncGenerator[ClientSession, None]:
        """Create a client session connected to the MCP server."""
        # Start the server subprocess
        server_env = os.environ.copy()

        # Ensure PYTHONPATH includes the current directory
        python_path = os.environ.get("PYTHONPATH", "")
        server_env["PYTHONPATH"] = f"{os.path.abspath('.')}:{python_path}"

        server_module = "python_docker_mcp"
        
        # Use the StdioServerParameters class to define the server
        server_params = StdioServerParameters(
            command=sys.executable,
            args=["-m", server_module],
            env=server_env
        )

        # Use the stdio_client context manager properly
        async with stdio_client(server_params) as session:
            # Yield the session for the test
            yield session
        
        # The context manager will handle cleanup automatically

    @pytest.mark.asyncio
    async def test_list_tools(self, client_session: ClientSession) -> None:
        """Test that we can list available tools."""
        response = await client_session.list_tools()

        # Verify we have the expected tools
        assert len(response.tools) == 4

        # Check for expected tool names
        tool_names = [tool.name for tool in response.tools]
        assert "execute-transient" in tool_names
        assert "execute-persistent" in tool_names
        assert "install-package" in tool_names
        assert "cleanup-session" in tool_names

    @pytest.mark.asyncio
    async def test_execute_transient(self, client_session: ClientSession) -> None:
        """Test execution of Python code in a transient container."""
        code = "print('Hello from transient container')\nresult = 42"

        response = await client_session.call_tool("execute-transient", {"code": code})

        # Verify the response
        assert len(response.content) == 1
        text_content = response.content[0]
        assert text_content.type == "text"
        assert "Hello from transient container" in text_content.text
        assert "Error:" not in text_content.text

    @pytest.mark.asyncio
    async def test_execute_persistent(self, client_session: ClientSession) -> None:
        """Test execution of Python code in a persistent container."""
        # First execution - define a variable
        code1 = "x = 42\nprint(f'Defined x = {x}')"

        response1 = await client_session.call_tool("execute-persistent", {"code": code1})

        # Extract the session ID from the response
        text_content1 = response1.content[0]
        assert text_content1.type == "text"

        # Parse session ID from the response text
        import re

        session_id_match = re.search(r"Session ID: ([a-f0-9-]+)", text_content1.text)
        assert session_id_match, "Session ID not found in response"
        session_id = session_id_match.group(1)

        # Second execution - use the previously defined variable
        code2 = "print(f'The value of x is {x}')\ny = x * 2\nprint(f'y = {y}')"

        response2 = await client_session.call_tool("execute-persistent", {"code": code2, "session_id": session_id})

        # Verify the response
        text_content2 = response2.content[0]
        assert text_content2.type == "text"
        assert "The value of x is 42" in text_content2.text
        assert "y = 84" in text_content2.text
        assert "Error:" not in text_content2.text

        # Clean up the session
        await client_session.call_tool("cleanup-session", {"session_id": session_id})

    @pytest.mark.asyncio
    async def test_execute_with_error(self, client_session: ClientSession) -> None:
        """Test execution of Python code that results in an error."""
        code = "undefined_variable"

        response = await client_session.call_tool("execute-transient", {"code": code})

        # Verify the response contains an error
        text_content = response.content[0]
        assert text_content.type == "text"
        assert "Error:" in text_content.text
        assert "undefined_variable" in text_content.text

    @pytest.mark.asyncio
    async def test_missing_required_argument(self, client_session: ClientSession) -> None:
        """Test calling a tool without a required argument."""
        with pytest.raises(McpError):
            await client_session.call_tool("execute-transient", {})

    @pytest.mark.asyncio
    async def test_container_error_handling(self, client_session: ClientSession) -> None:
        """Test error handling when containers fail unexpectedly."""
        # Test code that causes Docker interaction issues
        code = """
import os
# Code that attempts to access restricted resources
try:
    os.system("touch /root/test.txt")  # This should fail in a restricted container
except Exception as e:
    print(f"Error: {e}")
"""
        # This should execute without raising an exception, even if the Docker operation fails
        response = await client_session.call_tool("execute-transient", {"code": code})
        
        # Verify the response has content
        assert len(response.content) > 0
        text_content = response.content[0]
        assert text_content.type == "text"
        
        # We don't necessarily get a specific error message, but the execution should complete
        assert "Error" in text_content.text or "execution complete" in text_content.text.lower()
        
    @pytest.mark.asyncio
    async def test_execute_with_traceback(self, client_session: ClientSession) -> None:
        """Test that execution errors include traceback information."""
        # Code with a runtime error
        code = """
def divide_by_zero():
    return 1/0
    
divide_by_zero()
"""
        response = await client_session.call_tool("execute-transient", {"code": code})
        
        # Verify the response contains a traceback
        text_content = response.content[0]
        assert text_content.type == "text"
        assert "Error:" in text_content.text
        assert "ZeroDivisionError" in text_content.text
        # Check for traceback elements
        assert "Traceback" in text_content.text or "line" in text_content.text


class MockMCPClient:
    """Mock MCP client for testing."""

    def __init__(self):
        """Initialize the client."""
        self.session = None

    async def connect_to_server(self, server_env_var: str = None) -> None:
        """Connect to the MCP server."""
        # Start the server subprocess
        server_env = os.environ.copy()

        # Ensure PYTHONPATH includes the current directory
        python_path = os.environ.get("PYTHONPATH", "")
        server_env["PYTHONPATH"] = f"{os.path.abspath('.')}:{python_path}"

        server_module = "python_docker_mcp"
        server_params = StdioServerParameters(command=sys.executable, args=["-m", server_module], env=server_env)

        # Use the async context manager properly
        self.client_context = stdio_client(server_params)
        self.session = await self.client_context.__aenter__()

        # Initialize the session
        await self.session.initialize()

    async def list_tools(self) -> List[Dict[str, Any]]:
        """List available tools on the server."""
        if not self.session:
            raise RuntimeError("Not connected to server")

        response = await self.session.list_tools()
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.inputSchema,
            }
            for tool in response.tools
        ]

    async def execute_transient(self, code: str, state: Optional[Dict[str, Any]] = None) -> str:
        """Execute code in a transient container."""
        if not self.session:
            raise RuntimeError("Not connected to server")

        args = {"code": code}
        if state:
            args["state"] = state

        response = await self.session.call_tool("execute-transient", args)
        return response.content[0].text

    async def execute_persistent(self, code: str, session_id: Optional[str] = None) -> Tuple[str, str]:
        """Execute code in a persistent container."""
        if not self.session:
            raise RuntimeError("Not connected to server")

        args = {"code": code}
        if session_id:
            args["session_id"] = session_id

        response = await self.session.call_tool("execute-persistent", args)
        text = response.content[0].text

        # Extract session ID if not provided
        if not session_id:
            import re

            match = re.search(r"Session ID: ([a-f0-9-]+)", text)
            session_id = match.group(1) if match else "unknown"

        return text, session_id

    async def install_package(self, package_name: str, session_id: Optional[str] = None) -> str:
        """Install a package in a container."""
        if not self.session:
            raise RuntimeError("Not connected to server")

        args = {"package_name": package_name}
        if session_id:
            args["session_id"] = session_id

        response = await self.session.call_tool("install-package", args)
        return response.content[0].text

    async def cleanup_session(self, session_id: str) -> str:
        """Clean up a session."""
        if not self.session:
            raise RuntimeError("Not connected to server")

        args = {"session_id": session_id}
        response = await self.session.call_tool("cleanup-session", args)
        return response.content[0].text

    async def close(self) -> None:
        """Close the client session."""
        if hasattr(self, 'session') and self.session:
            await self.session.close()
            # Properly exit the async context manager
            if hasattr(self, 'client_context'):
                await self.client_context.__aexit__(None, None, None)
            self.session = None


@pytest.mark.asyncio
async def test_mock_mcp_client_workflow():
    """Test the complete workflow using the mock client."""
    client = MockMCPClient()
    try:
        await client.connect_to_server()
        
        # List tools
        tools = await client.list_tools()
        assert len(tools) >= 4
        
        # Execute transient code
        result = await client.execute_transient("print('Hello, world!')")
        assert "Hello, world!" in result
        
        # Execute persistent code
        result, session_id = await client.execute_persistent("x = 42\nprint(f'x = {x}')")
        assert "x = 42" in result
        assert session_id != "unknown"
        
        # Use the session_id for another execution
        result, _ = await client.execute_persistent("y = x * 2\nprint(f'y = {y}')", session_id)
        assert "y = 84" in result
        
        # Install a package
        result = await client.install_package("numpy", session_id)
        assert "numpy" in result
        
        # Clean up
        result = await client.cleanup_session(session_id)
        assert session_id in result
        
    finally:
        await client.close()
