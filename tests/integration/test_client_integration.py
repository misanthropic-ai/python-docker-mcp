"""Integration tests for the Python Docker MCP client."""

import asyncio
import json
import os
import subprocess
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from python_docker_mcp.client import PythonDockerClient


class MockServerProcess:
    """A class that mimics a running server process for testing."""
    
    def __init__(self, responses=None):
        """Initialize with predefined responses for different requests."""
        self.responses = responses or {}
        self.stdin = AsyncMock()
        self.stdout = AsyncMock()
        self.returncode = None
        
        # Configure stdout.readline to return appropriate responses
        self.configure_stdout_readline()
    
    def configure_stdout_readline(self):
        """Configure the stdout readline method to return appropriate responses."""
        async def mock_readline():
            # Get the last message sent to stdin
            if not hasattr(self, 'last_message') or not self.last_message:
                # Initial response - server information
                return json.dumps({
                    "jsonrpc": "2.0",
                    "method": "server/initialize",
                    "params": {
                        "name": "python-docker-mcp-server",
                        "version": "0.1.0",
                        "capabilities": {
                            "tools": True
                        }
                    }
                }).encode() + b"\n"
            
            # Parse the last message to determine what response to provide
            try:
                req = json.loads(self.last_message)
                if "method" in req:
                    method = req["method"]
                    if method == "initialize":
                        return json.dumps({
                            "jsonrpc": "2.0",
                            "id": req.get("id"),
                            "result": {
                                "server_info": {
                                    "name": "python-docker-mcp-server",
                                    "version": "0.1.0"
                                }
                            }
                        }).encode() + b"\n"
                    elif method == "list_tools":
                        return json.dumps({
                            "jsonrpc": "2.0",
                            "id": req.get("id"),
                            "result": {
                                "tools": [
                                    {
                                        "name": "execute-transient",
                                        "description": "Execute Python code in a transient container",
                                        "inputSchema": {"type": "object"}
                                    },
                                    {
                                        "name": "execute-persistent",
                                        "description": "Execute Python code in a persistent container",
                                        "inputSchema": {"type": "object"}
                                    },
                                    {
                                        "name": "install-package",
                                        "description": "Install a Python package in a container",
                                        "inputSchema": {"type": "object"}
                                    },
                                    {
                                        "name": "cleanup-session",
                                        "description": "Clean up a persistent session",
                                        "inputSchema": {"type": "object"}
                                    }
                                ]
                            }
                        }).encode() + b"\n"
                    elif method.startswith("tool/"):
                        tool_name = method[5:]  # Remove "tool/" prefix
                        if tool_name == "execute-transient":
                            return json.dumps({
                                "jsonrpc": "2.0",
                                "id": req.get("id"),
                                "result": {
                                    "content": [
                                        {
                                            "type": "text",
                                            "text": "Execution Result:\nHello, World!\n"
                                        }
                                    ]
                                }
                            }).encode() + b"\n"
                        elif tool_name == "execute-persistent":
                            return json.dumps({
                                "jsonrpc": "2.0",
                                "id": req.get("id"),
                                "result": {
                                    "content": [
                                        {
                                            "type": "text",
                                            "text": "Session ID: test-session-123\n\nExecution Result:\nHello from persistent container"
                                        }
                                    ]
                                }
                            }).encode() + b"\n"
                        elif tool_name == "install-package":
                            return json.dumps({
                                "jsonrpc": "2.0",
                                "id": req.get("id"),
                                "result": {
                                    "content": [
                                        {
                                            "type": "text",
                                            "text": "Package installation result:\n\nSuccessfully installed numpy-1.24.0"
                                        }
                                    ]
                                }
                            }).encode() + b"\n"
                        elif tool_name == "cleanup-session":
                            return json.dumps({
                                "jsonrpc": "2.0",
                                "id": req.get("id"),
                                "result": {
                                    "content": [
                                        {
                                            "type": "text",
                                            "text": "Session test-session-123 cleaned up successfully"
                                        }
                                    ]
                                }
                            }).encode() + b"\n"
            except (json.JSONDecodeError, KeyError):
                pass
            
            # Default response
            return json.dumps({
                "jsonrpc": "2.0",
                "id": 1,
                "error": {
                    "code": -32601,
                    "message": "Method not found"
                }
            }).encode() + b"\n"
        
        self.stdout.readline = mock_readline
    
    async def write(self, message):
        """Store the message and handle the write operation."""
        self.last_message = message.decode('utf-8')
        return len(message)
    
    def terminate(self):
        """Terminate the mock server."""
        self.returncode = 0


@pytest.fixture
async def mock_server():
    """Create a mock server for integration testing."""
    server = MockServerProcess()
    # Mock the stdin.write method
    server.stdin.write = server.write
    return server


@pytest.fixture
def mock_subprocess_popen(mock_server):
    """Mock subprocess.Popen to return our mock server."""
    with patch('subprocess.Popen') as mock_popen:
        mock_popen.return_value = mock_server
        yield mock_popen


@pytest.mark.asyncio
async def test_full_client_workflow(mock_subprocess_popen, mock_server):
    """Test the full client workflow from connecting to cleanup."""
    client = PythonDockerClient()
    
    # Test connection
    await client.connect_to_server()
    
    # Test listing tools
    tools = await client.list_tools()
    assert len(tools) == 4
    tool_names = [tool["name"] for tool in tools]
    assert "execute-transient" in tool_names
    assert "execute-persistent" in tool_names
    assert "install-package" in tool_names
    assert "cleanup-session" in tool_names
    
    # Test executing code in transient container
    result = await client.execute_transient("print('Hello, World!')")
    assert "Hello, World!" in result["output"]
    assert result["error"] is None
    
    # Test executing code in persistent container
    result, session_id = await client.execute_persistent("print('Hello from persistent container')")
    assert "Hello from persistent container" in result["output"]
    assert session_id == "test-session-123"
    
    # Test installing a package
    result = await client.install_package("numpy", session_id)
    assert result["package_name"] == "numpy"
    assert result["success"] is True
    
    # Test cleaning up a session
    success = await client.cleanup_session(session_id)
    assert success is True
    
    # Test closing the connection
    await client.close()
    assert client.session is None


@pytest.mark.asyncio
async def test_script_detection():
    """Test that the client correctly detects script types."""
    client = PythonDockerClient()
    
    # Test Python script detection
    with patch('subprocess.Popen') as mock_popen:
        mock_popen.return_value = MockServerProcess()
        mock_popen.return_value.stdin.write = mock_popen.return_value.write
        
        await client.connect_to_server("server.py")
        mock_popen.assert_called_once()
        
        # The command should include python and the script path
        cmd_args = mock_popen.call_args[0][0]
        assert "python" in cmd_args[0].lower()
        assert "server.py" in cmd_args
    
    await client.close()
    
    # Test JavaScript script detection
    with patch('subprocess.Popen') as mock_popen:
        mock_popen.return_value = MockServerProcess()
        mock_popen.return_value.stdin.write = mock_popen.return_value.write
        
        await client.connect_to_server("server.js")
        mock_popen.assert_called_once()
        
        # The command should include node and the script path
        cmd_args = mock_popen.call_args[0][0]
        assert "node" in cmd_args[0].lower()
        assert "server.js" in cmd_args
    
    await client.close()


@pytest.mark.asyncio
async def test_invalid_response_handling():
    """Test how the client handles invalid server responses."""
    # Create a server that returns invalid JSON
    class InvalidResponseServer(MockServerProcess):
        async def mock_readline(self):
            return b"invalid json\n"
    
    invalid_server = InvalidResponseServer()
    invalid_server.stdout.readline = invalid_server.mock_readline
    invalid_server.stdin.write = invalid_server.write
    
    # Test with the invalid server
    with patch('subprocess.Popen') as mock_popen:
        mock_popen.return_value = invalid_server
        
        client = PythonDockerClient()
        
        # Connection should raise an exception
        with pytest.raises(Exception):
            await client.connect_to_server() 