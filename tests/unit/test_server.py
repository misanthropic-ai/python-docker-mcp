"""Unit tests for the MCP server module."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import mcp.types as types
import pytest
from pydantic import AnyUrl

from python_docker_mcp.server import (
    _format_execution_result,
    handle_call_tool,
    handle_get_prompt,
    handle_list_prompts,
    handle_list_resources,
    handle_list_tools,
    handle_read_resource,
)


@pytest.mark.asyncio
async def test_handle_list_resources():
    """Test that list_resources returns an empty list."""
    resources = await handle_list_resources()
    assert isinstance(resources, list)
    assert len(resources) == 0


@pytest.mark.asyncio
async def test_handle_read_resource():
    """Test that read_resource raises a ValueError."""
    uri = AnyUrl("http://example.com")
    with pytest.raises(ValueError) as exc_info:
        await handle_read_resource(uri)
    assert "Unsupported resource URI" in str(exc_info.value)


@pytest.mark.asyncio
async def test_handle_list_prompts():
    """Test that list_prompts returns an empty list."""
    prompts = await handle_list_prompts()
    assert isinstance(prompts, list)
    assert len(prompts) == 0


@pytest.mark.asyncio
async def test_handle_get_prompt():
    """Test that get_prompt raises a ValueError."""
    with pytest.raises(ValueError) as exc_info:
        await handle_get_prompt("test-prompt", None)
    assert "Unknown prompt" in str(exc_info.value)


@pytest.mark.asyncio
async def test_handle_list_tools():
    """Test that list_tools returns the expected tools."""
    tools = await handle_list_tools()
    assert isinstance(tools, list)
    assert len(tools) == 4

    # Verify the tool names
    tool_names = [tool.name for tool in tools]
    assert "execute-transient" in tool_names
    assert "execute-persistent" in tool_names
    assert "install-package" in tool_names
    assert "cleanup-session" in tool_names

    # Verify the tools have proper schemas
    for tool in tools:
        assert isinstance(tool.inputSchema, dict)
        assert "properties" in tool.inputSchema
        assert "required" in tool.inputSchema


@pytest.mark.asyncio
@patch("python_docker_mcp.server.docker_manager")
async def test_handle_call_tool_missing_arguments(mock_docker_manager):
    """Test handle_call_tool with missing arguments."""
    # Our implementation now catches exceptions and returns them as text content
    result = await handle_call_tool("execute-transient", None)
    assert len(result) == 1
    assert result[0].type == "text"
    assert "Error executing execute-transient: Missing arguments" in result[0].text


@pytest.mark.asyncio
@patch("python_docker_mcp.server.docker_manager")
@patch("python_docker_mcp.server.uuid.uuid4")
async def test_handle_call_tool_execute_persistent_new_session(mock_uuid4, mock_docker_manager):
    """Test handle_call_tool with execute-persistent creating a new session."""
    # Setup the mock to return a proper result
    mock_uuid4.return_value = uuid.UUID("00000000-0000-0000-0000-000000000001")
    # Update the mock result to match our new format
    mock_result = {"__stdout__": "Test output", "__stderr__": "", "__error__": None, "result": 42}
    mock_docker_manager.execute_persistent = AsyncMock(return_value=mock_result)

    # Call the function
    response = await handle_call_tool("execute-persistent", {"code": "print('test')"})

    # Verify the call to the Docker manager
    mock_docker_manager.execute_persistent.assert_called_once_with("00000000-0000-0000-0000-000000000001", "print('test')")

    # Verify the response
    assert len(response) == 1
    assert isinstance(response[0], types.TextContent)
    assert "Test output" in response[0].text


@pytest.mark.asyncio
@patch("python_docker_mcp.server.docker_manager")
async def test_handle_call_tool_execute_persistent_existing_session(
    mock_docker_manager,
):
    """Test handle_call_tool with execute-persistent using an existing session."""
    # Setup the mock to return a proper result with the new format
    mock_result = {"__stdout__": "Test output", "__stderr__": "", "__error__": None, "result": 42}
    mock_docker_manager.execute_persistent = AsyncMock(return_value=mock_result)

    # Call the function
    response = await handle_call_tool(
        "execute-persistent",
        {"code": "print('test')", "session_id": "existing-session"},
    )

    # Verify the call to the Docker manager
    mock_docker_manager.execute_persistent.assert_called_once_with("existing-session", "print('test')")

    # Verify the response
    assert len(response) == 1
    assert isinstance(response[0], types.TextContent)
    assert "Session ID: existing-session" in response[0].text
    assert "Test output" in response[0].text


@pytest.mark.asyncio
@patch("python_docker_mcp.server.docker_manager")
@patch("python_docker_mcp.server.sessions")
async def test_handle_call_tool_cleanup_session(mock_sessions, mock_docker_manager):
    """Test handle_call_tool with cleanup-session."""
    # Setup the mock sessions
    mock_sessions.pop = MagicMock()
    mock_sessions.__contains__ = MagicMock(return_value=True)

    # Make sure the cleanup_session method is an AsyncMock
    mock_docker_manager.cleanup_session = AsyncMock()
    mock_docker_manager.cleanup_session.return_value = {"status": "success"}

    # Call the function
    response = await handle_call_tool("cleanup-session", {"session_id": "test-session"})

    # Verify the call to the Docker manager
    mock_docker_manager.cleanup_session.assert_called_once_with("test-session")

    # Verify the response
    assert len(response) == 1
    assert isinstance(response[0], types.TextContent)
    assert "test-session cleaned up successfully" in response[0].text


@pytest.mark.asyncio
async def test_handle_call_tool_unknown_tool():
    """Test handle_call_tool with an unknown tool."""
    # Our implementation now catches exceptions and returns them as text content
    result = await handle_call_tool("unknown-tool", {"param": "value"})
    assert len(result) == 1
    assert result[0].type == "text"
    assert "Error executing unknown-tool: Unknown tool: unknown-tool" in result[0].text


def test_format_execution_result_transient():
    """Test _format_execution_result with transient execution result."""
    result = {
        "__stdout__": "Hello, world!",
        "__stderr__": "Warning: deprecated feature",
        "__error__": None,
        "value": 42,
    }

    formatted = _format_execution_result(result)
    assert "Execution Result:" in formatted
    assert "Hello, world!" in formatted
    assert "Warning: deprecated feature" in formatted
    assert "Error: " not in formatted


def test_format_execution_result_transient_with_error():
    """Test _format_execution_result with transient execution result containing an error."""
    result = {
        "__stdout__": "Partial output",
        "__stderr__": "",
        "__error__": "NameError: name 'undefined_var' is not defined",
        "value": None,
    }

    formatted = _format_execution_result(result)
    assert "Execution Result:" in formatted
    assert "Partial output" in formatted
    assert "Error: NameError" in formatted


def test_format_execution_result_persistent():
    """Test _format_execution_result with persistent execution result."""
    # Update test to match new format which doesn't take a second session_id argument
    result = {"__stdout__": "Result from persistent container", "__stderr__": "", "__error__": None, "result": 42}

    formatted = _format_execution_result(result)
    assert "Result from persistent container" in formatted


def test_format_execution_result_persistent_with_error():
    """Test _format_execution_result with persistent execution result containing an error."""
    # Update test to match new format which doesn't take a second session_id argument
    result = {"__stdout__": "Partial output", "__stderr__": "", "__error__": "SyntaxError: invalid syntax", "result": None}

    formatted = _format_execution_result(result)
    assert "Partial output" in formatted
    assert "Error:" in formatted
    assert "SyntaxError: invalid syntax" in formatted
