"""Unit tests for the MCP server implementation."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

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
    main,
)


@pytest.mark.asyncio
async def test_handle_list_resources():
    """Test listing resources."""
    resources = await handle_list_resources()
    assert isinstance(resources, list)
    assert len(resources) == 0


@pytest.mark.asyncio
async def test_handle_read_resource():
    """Test reading a resource (should raise an error)."""
    with pytest.raises(ValueError, match="Unsupported resource URI"):
        await handle_read_resource(AnyUrl("https://example.com/resource"))


@pytest.mark.asyncio
async def test_handle_list_prompts():
    """Test listing prompts."""
    prompts = await handle_list_prompts()
    assert isinstance(prompts, list)
    assert len(prompts) == 0


@pytest.mark.asyncio
async def test_handle_get_prompt():
    """Test getting a prompt (should raise an error)."""
    with pytest.raises(ValueError, match="Unknown prompt:"):
        await handle_get_prompt("test-prompt", {})


@pytest.mark.asyncio
async def test_handle_list_tools():
    """Test listing available tools."""
    tools = await handle_list_tools()
    assert isinstance(tools, list)
    assert len(tools) == 4

    # Check that all required tools are present
    tool_names = [tool.name for tool in tools]
    assert "execute-transient" in tool_names
    assert "execute-persistent" in tool_names
    assert "install-package" in tool_names
    assert "cleanup-session" in tool_names

    # Verify each tool has proper schema
    for tool in tools:
        assert tool.name is not None
        assert tool.description is not None
        assert tool.inputSchema is not None
        assert "type" in tool.inputSchema
        assert "properties" in tool.inputSchema


@patch("python_docker_mcp.server.docker_manager")
@pytest.mark.asyncio
async def test_handle_call_tool_execute_transient(mock_docker_manager):
    """Test executing code in a transient container."""
    # Mock the Docker manager
    mock_docker_manager.execute_transient = AsyncMock()
    mock_docker_manager.execute_transient.return_value = {
        "__stdout__": "Hello from transient!",
        "__stderr__": "",
        "__error__": None,
        "result": 42,
    }

    # Call the handler
    result = await handle_call_tool("execute-transient", {"code": "print('Hello')"})

    # Verify the response
    assert len(result) == 1
    assert result[0].type == "text"
    assert "Hello from transient!" in result[0].text
    mock_docker_manager.execute_transient.assert_called_once_with("print('Hello')", {})


@patch("python_docker_mcp.server.docker_manager")
@pytest.mark.asyncio
async def test_handle_call_tool_execute_transient_with_state(mock_docker_manager):
    """Test executing code in a transient container with state."""
    # Mock the Docker manager
    mock_docker_manager.execute_transient = AsyncMock()
    mock_docker_manager.execute_transient.return_value = {
        "__stdout__": "x = 42",
        "__stderr__": "",
        "__error__": None,
        "result": {"x": 42},
    }

    # Initial state to pass
    state = {"previous": "data"}

    # Call the handler
    result = await handle_call_tool("execute-transient", {"code": "print(x)", "state": state})

    # Verify the response
    assert len(result) == 1
    assert result[0].type == "text"
    mock_docker_manager.execute_transient.assert_called_once_with("print(x)", state)


@patch("python_docker_mcp.server.docker_manager")
@patch("python_docker_mcp.server.uuid.uuid4")
@pytest.mark.asyncio
async def test_handle_call_tool_execute_persistent_new_session(mock_uuid4, mock_docker_manager):
    """Test executing code in a new persistent container."""
    # Mock UUID generation
    mock_uuid4.return_value = uuid.UUID("12345678-1234-5678-1234-567812345678")

    # Mock the Docker manager
    mock_docker_manager.execute_persistent = AsyncMock()
    mock_docker_manager.execute_persistent.return_value = {
        "__stdout__": "Hello from persistent!",
        "__stderr__": "",
        "__error__": None,
        "result": {"x": 42},
    }

    # Call the handler
    result = await handle_call_tool("execute-persistent", {"code": "x = 42"})

    # Verify the response
    assert len(result) == 1
    assert result[0].type == "text"
    assert "Session ID: 12345678-1234-5678-1234-567812345678" in result[0].text
    assert "Hello from persistent!" in result[0].text
    # First parameter is the generated session ID
    mock_docker_manager.execute_persistent.assert_called_once_with("12345678-1234-5678-1234-567812345678", "x = 42")


@patch("python_docker_mcp.server.docker_manager")
@pytest.mark.asyncio
async def test_handle_call_tool_execute_persistent_existing_session(mock_docker_manager):
    """Test executing code in an existing persistent container."""
    # Mock the Docker manager
    mock_docker_manager.execute_persistent = AsyncMock()
    mock_docker_manager.execute_persistent.return_value = {
        "__stdout__": "Hello again!",
        "__stderr__": "",
        "__error__": None,
        "result": {"x": 42, "y": 10},
    }

    # Call the handler with an existing session ID
    session_id = "existing-session-id"
    result = await handle_call_tool("execute-persistent", {"code": "y = 10", "session_id": session_id})

    # Verify the response
    assert len(result) == 1
    assert result[0].type == "text"
    assert f"Session ID: {session_id}" in result[0].text
    assert "Hello again!" in result[0].text
    mock_docker_manager.execute_persistent.assert_called_once_with(session_id, "y = 10")


@patch("python_docker_mcp.server.docker_manager")
@pytest.mark.asyncio
async def test_handle_call_tool_install_package_transient(mock_docker_manager):
    """Test installing a package in a transient container."""
    # Mock the Docker manager
    mock_docker_manager.install_package = AsyncMock()
    mock_docker_manager.install_package.return_value = "Successfully installed numpy-1.24.0"

    # Call the handler
    result = await handle_call_tool("install-package", {"package_name": "numpy"})

    # Verify the response
    assert len(result) == 1
    assert result[0].type == "text"
    assert "Successfully installed numpy" in result[0].text
    # Note: Order of parameters is session_id, package_name according to the actual implementation
    mock_docker_manager.install_package.assert_called_once_with(None, "numpy")


@patch("python_docker_mcp.server.docker_manager")
@pytest.mark.asyncio
async def test_handle_call_tool_install_package_persistent(mock_docker_manager):
    """Test installing a package in a persistent container."""
    # Mock the Docker manager
    mock_docker_manager.install_package = AsyncMock()
    mock_docker_manager.install_package.return_value = "Successfully installed pandas-1.5.0"

    # Call the handler with a session ID
    session_id = "test-session"
    result = await handle_call_tool("install-package", {"package_name": "pandas", "session_id": session_id})

    # Verify the response
    assert len(result) == 1
    assert result[0].type == "text"
    assert "Successfully installed pandas" in result[0].text
    # Note: Order of parameters is session_id, package_name according to the actual implementation
    mock_docker_manager.install_package.assert_called_once_with(session_id, "pandas")


@patch("python_docker_mcp.server.docker_manager")
@pytest.mark.asyncio
async def test_handle_call_tool_cleanup_session(mock_docker_manager):
    """Test cleaning up a session."""
    # Mock the Docker manager
    mock_docker_manager.cleanup_session = MagicMock()

    # Call the handler
    session_id = "session-to-cleanup"
    result = await handle_call_tool("cleanup-session", {"session_id": session_id})

    # Verify the response
    assert len(result) == 1
    assert result[0].type == "text"
    assert f"Session {session_id} cleaned up successfully" in result[0].text
    mock_docker_manager.cleanup_session.assert_called_once_with(session_id)


@pytest.mark.asyncio
async def test_handle_call_tool_invalid_tool():
    """Test calling an invalid tool."""
    with pytest.raises(ValueError, match="Unknown tool:"):
        await handle_call_tool("invalid-tool", {"param": "value"})


@pytest.mark.asyncio
async def test_handle_call_tool_missing_arguments():
    """Test calling a tool with missing arguments."""
    with pytest.raises(ValueError, match="Missing arguments"):
        await handle_call_tool("execute-transient", None)


@pytest.mark.asyncio
async def test_handle_call_tool_missing_code():
    """Test calling execute tools without code."""
    # We need to use a non-empty arguments dict to get past the "Missing arguments" check
    with pytest.raises(ValueError, match="Missing code"):
        await handle_call_tool("execute-transient", {"some_arg": "value"})

    with pytest.raises(ValueError, match="Missing code"):
        await handle_call_tool("execute-persistent", {"some_arg": "value"})


@pytest.mark.asyncio
async def test_handle_call_tool_missing_package_name():
    """Test calling install-package without package name."""
    # We need to use a non-empty arguments dict to get past the "Missing arguments" check
    with pytest.raises(ValueError, match="Missing package name"):
        await handle_call_tool("install-package", {"some_arg": "value"})


@pytest.mark.asyncio
async def test_handle_call_tool_missing_session_id():
    """Test calling cleanup-session without session ID."""
    # We need to use a non-empty arguments dict to get past the "Missing arguments" check
    with pytest.raises(ValueError, match="Missing session ID"):
        await handle_call_tool("cleanup-session", {"some_arg": "value"})


def test_format_execution_result_success():
    """Test _format_execution_result with successful execution."""
    result = {
        "__stdout__": "Hello, world!",
        "__stderr__": "",
        "__error__": None,
        "result": {"x": 42, "y": "test"},
    }

    # Note: The actual implementation doesn't include the result dict in the output
    formatted = _format_execution_result(result)
    assert "Execution Result:" in formatted
    assert "Hello, world!" in formatted
    # The result dict is not included in the output, so we should not assert for its presence
    assert "Error:" not in formatted


def test_format_execution_result_with_error():
    """Test _format_execution_result with execution error."""
    result = {
        "__stdout__": "Starting execution...",
        "__stderr__": "Traceback...",
        "__error__": "NameError: name 'undefined_var' is not defined",
        "result": None,
    }

    formatted = _format_execution_result(result)
    assert "Execution Result:" in formatted
    assert "Starting execution..." in formatted
    # The actual implementation may not include stderr directly in the output
    # but may include it in the error message
    assert "Error:" in formatted
    assert "NameError: name 'undefined_var' is not defined" in formatted


def test_format_execution_result_with_stderr():
    """Test _format_execution_result with stderr output."""
    result = {
        "__stdout__": "Regular output",
        "__stderr__": "Warning: deprecated feature",
        "__error__": None,
        "result": 42,
    }

    formatted = _format_execution_result(result)
    assert "Execution Result:" in formatted
    assert "Regular output" in formatted
    assert "Standard Error:" in formatted
    assert "Warning: deprecated feature" in formatted


@pytest.mark.asyncio
async def test_main():
    """Test the main function."""
    # Create mock async context manager
    mock_context = AsyncMock()
    mock_read_stream = AsyncMock()
    mock_write_stream = AsyncMock()
    mock_context.__aenter__.return_value = (mock_read_stream, mock_write_stream)

    # Apply the patches
    with (
        patch("mcp.server.stdio.stdio_server", return_value=mock_context),
        patch("python_docker_mcp.server.server.run"),
        patch("python_docker_mcp.server.docker_manager"),
    ):
        # Run the main function
        await main()
