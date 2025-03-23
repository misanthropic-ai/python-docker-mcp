"""Unit tests for the client module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from python_docker_mcp.client import PythonDockerClient


@pytest.fixture
def mock_session():
    """Create a mock MCP client session."""
    session = MagicMock()
    session.initialize = AsyncMock()
    session.list_tools = AsyncMock()
    session.call_tool = AsyncMock()
    session.close = AsyncMock()
    return session


@pytest.fixture
def mock_stdio_client():
    """Create a mock stdio_client context manager."""
    mock_context = AsyncMock()
    mock_context.__aenter__.return_value = (MagicMock(), MagicMock())
    return mock_context


@pytest.fixture
def mock_client_session():
    """Create a mock ClientSession."""
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock()
    session.initialize = AsyncMock()
    session.list_tools = AsyncMock()
    session.call_tool = AsyncMock()
    return session


@pytest.mark.asyncio
@patch("python_docker_mcp.client.stdio_client")
@patch("python_docker_mcp.client.ClientSession")
async def test_connect_to_server_with_path(mock_client_session_cls, mock_stdio_client_patch, mock_session):
    """Test connecting to the server with a script path."""
    # Setup mock
    mock_stdio_client_patch.return_value = mock_stdio_client()
    mock_client_session_cls.return_value = mock_session

    # Create client and connect
    client = PythonDockerClient()
    await client.connect_to_server("/path/to/server.py")

    # Verify the connection
    mock_stdio_client_patch.assert_called_once()
    mock_client_session_cls.assert_called_once()
    mock_session.initialize.assert_called_once()
    assert client.session == mock_session


@pytest.mark.asyncio
@patch("python_docker_mcp.client.stdio_client")
@patch("python_docker_mcp.client.ClientSession")
async def test_connect_to_server_without_path(mock_client_session_cls, mock_stdio_client_patch, mock_session):
    """Test connecting to the server without a script path."""
    # Setup mock
    mock_stdio_client_patch.return_value = mock_stdio_client()
    mock_client_session_cls.return_value = mock_session

    # Create client and connect
    client = PythonDockerClient()
    await client.connect_to_server()

    # Verify the connection
    mock_stdio_client_patch.assert_called_once()
    mock_client_session_cls.assert_called_once()
    mock_session.initialize.assert_called_once()
    assert client.session == mock_session


@pytest.mark.asyncio
async def test_connect_to_server_invalid_path():
    """Test connecting to the server with an invalid script path."""
    client = PythonDockerClient()
    with pytest.raises(ValueError):
        await client.connect_to_server("/path/to/server.invalid")


@pytest.mark.asyncio
async def test_list_tools(mock_session):
    """Test listing tools."""
    # Setup mock
    tool1 = MagicMock(
        name="execute-transient",
        description="Execute Python code in a transient container",
        inputSchema={"type": "object"},
    )
    tool2 = MagicMock(
        name="execute-persistent",
        description="Execute Python code in a persistent container",
        inputSchema={"type": "object"},
    )
    response = MagicMock()
    response.tools = [tool1, tool2]
    mock_session.list_tools.return_value = response

    # Create client and set session
    client = PythonDockerClient()
    client.session = mock_session

    # Call the method
    tools = await client.list_tools()

    # Verify the result
    assert len(tools) == 2
    assert tools[0]["name"] == "execute-transient"
    assert tools[1]["name"] == "execute-persistent"


@pytest.mark.asyncio
async def test_execute_transient(mock_session):
    """Test executing code in a transient container."""
    # Setup mock
    response = MagicMock()
    text_content = MagicMock(type="text", text="Execution Result:\nHello, World!\n")
    response.content = [text_content]
    mock_session.call_tool.return_value = response

    # Create client and set session
    client = PythonDockerClient()
    client.session = mock_session

    # Call the method
    result = await client.execute_transient("print('Hello, World!')")

    # Verify the call
    mock_session.call_tool.assert_called_once_with("execute-transient", {"code": "print('Hello, World!')"})

    # Verify the result
    assert result["raw_output"] == "Execution Result:\nHello, World!\n"
    assert result["error"] is None
    assert result["output"] == "Hello, World!"


@pytest.mark.asyncio
async def test_execute_transient_with_state(mock_session):
    """Test executing code in a transient container with state."""
    # Setup mock
    response = MagicMock()
    text_content = MagicMock(type="text", text="Execution Result:\nThe value is 42\n")
    response.content = [text_content]
    mock_session.call_tool.return_value = response

    # Create client and set session
    client = PythonDockerClient()
    client.session = mock_session

    # Call the method with state
    state = {"value": 42}
    result = await client.execute_transient("print(f'The value is {state[\"value\"]}')", state)

    # Verify the call
    mock_session.call_tool.assert_called_once_with(
        "execute-transient",
        {"code": "print(f'The value is {state[\"value\"]}')", "state": state},
    )

    # Verify the result
    assert result["raw_output"] == "Execution Result:\nThe value is 42\n"
    assert result["error"] is None


@pytest.mark.asyncio
async def test_execute_transient_with_error(mock_session):
    """Test executing code in a transient container that results in an error."""
    # Setup mock
    response = MagicMock()
    text_content = MagicMock(
        type="text",
        text="Execution Result:\n\nError: NameError: name 'undefined' is not defined",
    )
    response.content = [text_content]
    mock_session.call_tool.return_value = response

    # Create client and set session
    client = PythonDockerClient()
    client.session = mock_session

    # Call the method
    result = await client.execute_transient("print(undefined)")

    # Verify the call
    mock_session.call_tool.assert_called_once_with("execute-transient", {"code": "print(undefined)"})

    # Verify the result
    assert result["raw_output"] == "Execution Result:\n\nError: NameError: name 'undefined' is not defined"
    assert "NameError" in result["error"]


@pytest.mark.asyncio
async def test_execute_persistent_new_session(mock_session):
    """Test executing code in a new persistent container."""
    # Setup mock
    response = MagicMock()
    text_content = MagicMock(
        type="text",
        text="Session ID: abc-123\n\nExecution Result:\nHello from persistent container",
    )
    response.content = [text_content]
    mock_session.call_tool.return_value = response

    # Create client and set session
    client = PythonDockerClient()
    client.session = mock_session

    # Call the method without session ID
    result, session_id = await client.execute_persistent("print('Hello from persistent container')")

    # Verify the call
    mock_session.call_tool.assert_called_once_with("execute-persistent", {"code": "print('Hello from persistent container')"})

    # Verify the result
    assert result["raw_output"] == "Session ID: abc-123\n\nExecution Result:\nHello from persistent container"
    assert result["error"] is None
    assert result["output"] == "Hello from persistent container"
    assert session_id == "abc-123"


@pytest.mark.asyncio
async def test_execute_persistent_existing_session(mock_session):
    """Test executing code in an existing persistent container."""
    # Setup mock
    response = MagicMock()
    text_content = MagicMock(
        type="text",
        text="Session ID: abc-123\n\nExecution Result:\nUsing existing session",
    )
    response.content = [text_content]
    mock_session.call_tool.return_value = response

    # Create client and set session
    client = PythonDockerClient()
    client.session = mock_session

    # Call the method with session ID
    result, session_id = await client.execute_persistent("print('Using existing session')", "abc-123")

    # Verify the call
    mock_session.call_tool.assert_called_once_with(
        "execute-persistent",
        {"code": "print('Using existing session')", "session_id": "abc-123"},
    )

    # Verify the result
    assert session_id == "abc-123"


@pytest.mark.asyncio
async def test_install_package(mock_session):
    """Test installing a package."""
    # Setup mock
    response = MagicMock()
    text_content = MagicMock(
        type="text",
        text="Package installation result:\n\nSuccessfully installed numpy-1.24.0",
    )
    response.content = [text_content]
    mock_session.call_tool.return_value = response

    # Create client and set session
    client = PythonDockerClient()
    client.session = mock_session

    # Call the method
    result = await client.install_package("numpy")

    # Verify the call
    mock_session.call_tool.assert_called_once_with("install-package", {"package_name": "numpy"})

    # Verify the result
    assert result["package_name"] == "numpy"
    assert result["success"] is True


@pytest.mark.asyncio
async def test_install_package_with_session(mock_session):
    """Test installing a package in a persistent session."""
    # Setup mock
    response = MagicMock()
    text_content = MagicMock(type="text", text="Package installation result:\n\nSuccessfully installed pandas-2.0.0")
    response.content = [text_content]
    mock_session.call_tool.return_value = response

    # Create client and set session
    client = PythonDockerClient()
    client.session = mock_session

    # Call the method with session ID
    install_result = await client.install_package("pandas", "abc-123")

    # Verify the call
    mock_session.call_tool.assert_called_once_with("install-package", {"package_name": "pandas", "session_id": "abc-123"})

    # Verify that we got a result back
    assert install_result["package_name"] == "pandas"
    assert install_result["success"] is True


@pytest.mark.asyncio
async def test_cleanup_session(mock_session):
    """Test cleaning up a session."""
    # Setup mock
    response = MagicMock()
    text_content = MagicMock(type="text", text="Session abc-123 cleaned up successfully")
    response.content = [text_content]
    mock_session.call_tool.return_value = response

    # Create client and set session
    client = PythonDockerClient()
    client.session = mock_session

    # Call the method
    success = await client.cleanup_session("abc-123")

    # Verify the call
    mock_session.call_tool.assert_called_once_with("cleanup-session", {"session_id": "abc-123"})

    # Verify the result
    assert success is True


@pytest.mark.asyncio
async def test_close(mock_session):
    """Test closing the client."""
    # Create client and set session
    client = PythonDockerClient()
    client.session = mock_session

    # Call the method
    await client.close()

    # Verify the session is cleared
    assert client.session is None


def test_ensure_connected():
    """Test ensuring the client is connected."""
    # Create client without setting session
    client = PythonDockerClient()

    # Call the method
    with pytest.raises(RuntimeError):
        client._ensure_connected()
