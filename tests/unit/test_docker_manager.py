"""Unit tests for the docker_manager module."""

import asyncio
import json
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import docker

from python_docker_mcp.docker_manager import DockerExecutionError, DockerManager


@pytest.mark.asyncio
async def test_execute_transient_success(docker_manager, mock_docker_client, mock_container):
    """Test successful execution in a transient container."""
    # Setup mock container behavior
    mock_container.attrs["State"]["ExitCode"] = 0
    
    # Create expected output data
    expected_output = {
        "__stdout__": "Hello, world!",
        "__stderr__": "",
        "__error__": None,
        "result": 42,
    }
    
    # Setup proper mocking with JSON return value
    mock_open = MagicMock()
    mock_file = MagicMock()
    mock_open.return_value.__enter__.return_value = mock_file
    
    # Mock json.load to return our expected data
    with patch("os.path.exists", return_value=True), \
         patch("builtins.open", mock_open), \
         patch("json.load", return_value=expected_output):
         
        # Execute the code
        result = await docker_manager.execute_transient("print('Hello, world!')")
        
        # Verify the result
        assert result["__stdout__"] == "Hello, world!"
        assert result["__error__"] is None
        assert result["result"] == 42


@pytest.mark.asyncio
async def test_execute_transient_error(docker_manager, mock_docker_client, mock_container):
    """Test error handling in transient container execution."""
    # Setup mock container behavior
    mock_container.attrs["State"]["ExitCode"] = 1
    mock_container.logs.return_value = b"Error: Python execution failed"
    
    # We don't need to mock json.load since the function will raise an error
    # when checking the exit code before reaching the json loading
    
    # Should raise DockerExecutionError
    with pytest.raises(DockerExecutionError) as exc_info:
        await docker_manager.execute_transient("print(undefined_var)")
    
    # Check the error message
    assert "Container exited with code 1" in str(exc_info.value)
    assert "Error: Python execution failed" in str(exc_info.value)


@pytest.mark.asyncio
async def test_execute_transient_timeout(docker_manager, mock_docker_client, mock_container):
    """Test handling of container execution timeout."""
    # Mock _wait_for_container to raise a timeout error
    docker_manager._wait_for_container = AsyncMock(side_effect=asyncio.TimeoutError())

    # Test that the timeout is properly handled
    with pytest.raises(DockerExecutionError) as exc_info:
        await docker_manager.execute_transient("while True: pass")  # Infinite loop

    assert "Execution timed out" in str(exc_info.value)


@pytest.mark.asyncio
async def test_execute_persistent_new_container(docker_manager, mock_docker_client, mock_container):
    """Test execution in a new persistent container."""
    # Configure mock container executor
    exec_mock = MagicMock()
    exec_mock.exit_code = 0
    exec_mock.output = b"---OUTPUT_START---\n{\"output\": \"Hello\", \"error\": null}\n---OUTPUT_END---"
    mock_container.exec_run.return_value = exec_mock
    
    # Call the function - use a test session ID
    session_id = "test-session-new"
    result = await docker_manager.execute_persistent(session_id, "print('Hello')")
    
    # Verify the result
    assert result["output"] == "Hello"
    assert result["error"] is None
    assert session_id in docker_manager.persistent_containers


@pytest.mark.asyncio
async def test_execute_persistent_existing_container(docker_manager, mock_docker_client, mock_container):
    """Test execution in an existing persistent container."""
    # Add a test session to the manager
    session_id = "test-session"
    docker_manager.persistent_containers[session_id] = "test-container-id"
    
    # Configure mock container executor
    exec_mock = MagicMock()
    exec_mock.exit_code = 0
    exec_mock.output = b"---OUTPUT_START---\n{\"output\": \"Hello again\", \"error\": null}\n---OUTPUT_END---"
    mock_container.exec_run.return_value = exec_mock
    
    # Call the function with existing session
    result = await docker_manager.execute_persistent(session_id, "print('Hello again')")
    
    # Verify the result
    assert result["output"] == "Hello again"
    assert result["error"] is None


@pytest.mark.asyncio
async def test_execute_persistent_execution_error(docker_manager, mock_docker_client, mock_container):
    """Test error handling in persistent container execution."""
    # Configure mock container executor to return an error
    exec_mock = MagicMock()
    exec_mock.exit_code = 1
    exec_mock.output = b"Error: Python execution failed"
    mock_container.exec_run.return_value = exec_mock
    
    # Expected to raise an error - use a test session ID
    session_id = "test-session-error"
    with pytest.raises(DockerExecutionError) as exc_info:
        await docker_manager.execute_persistent(session_id, "invalid python")
    
    assert "Execution failed" in str(exc_info.value)


@pytest.mark.asyncio
async def test_execute_persistent_json_parsing_error(docker_manager, mock_docker_client, mock_container):
    """Test handling of JSON parsing errors in persistent execution."""
    # Configure mock container executor to return invalid JSON
    exec_mock = MagicMock()
    exec_mock.exit_code = 0
    exec_mock.output = b"---OUTPUT_START---\nThis is not valid JSON\n---OUTPUT_END---"
    mock_container.exec_run.return_value = exec_mock
    
    # Should handle the JSON parsing error gracefully - use a test session ID
    session_id = "test-session-json"
    result = await docker_manager.execute_persistent(session_id, "print('Invalid JSON')")
    
    # Should return the raw output
    assert "output" in result
    assert "This is not valid JSON" in result["output"]


@pytest.mark.asyncio
async def test_install_package_transient(docker_manager, mock_docker_client, mock_container):
    """Test installing a package in a transient container."""
    # Configure mock container
    mock_container.logs.return_value = b"Successfully installed numpy"
    
    # Test installing a package
    result = await docker_manager.install_package(None, "numpy")
    
    # Verify the result
    assert "Successfully installed numpy" in result


@pytest.mark.asyncio
async def test_install_package_persistent(docker_manager, mock_docker_client, mock_container):
    """Test installing a package in a persistent container."""
    # Add a test session to the manager
    session_id = "test-session"
    docker_manager.persistent_containers[session_id] = "test-container-id"
    
    # Configure mock container executor
    exec_mock = MagicMock()
    exec_mock.exit_code = 0
    exec_mock.output = b"Successfully installed pandas"
    mock_container.exec_run.return_value = exec_mock
    
    # Test installing a package in the persistent container
    result = await docker_manager.install_package(session_id, "pandas")
    
    # Verify the result
    assert "Successfully installed pandas" in result


def test_cleanup_session(docker_manager, mock_docker_client, mock_container):
    """Test cleaning up a session."""
    # Setup existing persistent container
    docker_manager.persistent_containers = {"session-1": "test-container-id"}

    # Clean up the session
    docker_manager.cleanup_session("session-1")

    # Verify container stop and remove were called
    container = mock_docker_client.containers.get.return_value
    container.stop.assert_called_once()
    container.remove.assert_called_once()

    # Verify the session was removed from tracking
    assert "session-1" not in docker_manager.persistent_containers


def test_cleanup_all_sessions(docker_manager, mock_docker_client, mock_container):
    """Test cleaning up all sessions."""
    # Setup multiple existing persistent containers
    docker_manager.persistent_containers = {
        "session-1": "container-id-1",
        "session-2": "container-id-2",
    }

    # Clean up all sessions
    docker_manager.cleanup_all_sessions()

    # Verify all sessions were removed
    assert len(docker_manager.persistent_containers) == 0


def test_create_wrapper_script(docker_manager):
    """Test creation of wrapper script for transient execution."""
    code = "x = 1 + 1\nprint(x)"
    script = docker_manager._create_wrapper_script(code)

    # Check that the script contains the expected elements
    assert "import json" in script
    assert "import sys" in script
    assert "import io" in script
    assert "with open('/app/state.json', 'r') as f:" in script
    assert "exec_globals = {'state': state_dict}" in script
    assert repr(code) in script
    assert "with open('/app/output.json', 'w') as f:" in script


def test_create_execute_persist_script(docker_manager):
    """Test creation of execution script for persistent container."""
    code = "y = 2 * 2\nprint(y)"
    script = docker_manager._create_execute_persist_script(code)

    # Check that the script contains the expected elements
    assert "import json" in script
    assert "import sys" in script
    assert "import io" in script
    assert "stdout_capture = io.StringIO()" in script
    assert repr(code) in script
    assert "---OUTPUT_START---" in script
    assert "---OUTPUT_END---" in script


@pytest.mark.asyncio
async def test_wait_for_container_not_found(docker_manager, mock_docker_client, mock_container):
    """Test handling of container not found during wait."""
    # Mock get method to raise an exception
    mock_docker_client.containers.get.side_effect = docker.errors.NotFound("Container not found")
    
    # Test that the method gracefully handles the error
    exit_code = await docker_manager._wait_for_container("nonexistent-container")
    
    # Should return 0 (success) rather than propagating the error
    assert exit_code == 0
    mock_docker_client.containers.get.assert_called_with("nonexistent-container")


@pytest.mark.asyncio
async def test_wait_for_container_api_error(docker_manager, mock_docker_client, mock_container):
    """Test handling of API errors during container wait."""
    # First call succeeds, second fails
    mock_docker_client.containers.get.side_effect = [
        mock_container,  # First call returns container
        docker.errors.APIError("API Error")  # Second call raises error
    ]
    
    # Set the container to running for the first check
    mock_container.status = "running"
    
    # Test that the method gracefully handles the error
    exit_code = await docker_manager._wait_for_container("test-container")
    
    # Should return 0 (success) rather than propagating the error
    assert exit_code == 0
    assert mock_docker_client.containers.get.call_count == 2


@pytest.mark.asyncio
async def test_execute_transient_with_none_state(docker_manager, mock_docker_client, mock_container):
    """Test executing transient code with None state."""
    # Setup mock container behavior
    mock_container.attrs["State"]["ExitCode"] = 0
    
    # Create expected output data
    expected_output = {
        "__stdout__": "Test output",
        "__stderr__": "",
        "__error__": None,
        "result": 42,
    }
    
    # Setup proper mocking with JSON return value
    mock_open = MagicMock()
    mock_file = MagicMock()
    mock_open.return_value.__enter__.return_value = mock_file
    
    # Mock json.load to return our expected data
    with patch("os.path.exists", return_value=True), \
         patch("builtins.open", mock_open), \
         patch("json.load", return_value=expected_output):
         
        # Execute with explicit None state
        result = await docker_manager.execute_transient("print('test')", None)
        
        # Verify the result
        assert result["result"] == 42
        assert result["__stdout__"] == "Test output"


@pytest.mark.asyncio
async def test_execute_persistent_success(docker_manager, mock_docker_client, mock_container):
    """Test successful execution in a persistent container."""
    # Setup mock container behavior for creating a new container
    mock_container.attrs["State"]["ExitCode"] = 0
    
    # Configure mock container executor for the exec_run call
    exec_mock = MagicMock()
    exec_mock.exit_code = 0
    exec_mock.output = b"""---OUTPUT_START---
{
    "__stdout__": "Hello from persistent!",
    "__stderr__": "",
    "__error__": null,
    "result": {"x": 10, "y": 20},
    "output": "Success"
}
---OUTPUT_END---"""
    mock_container.exec_run.return_value = exec_mock
    
    # Setup proper mocking with JSON return value
    with patch("os.system", return_value=0):  # Mock the docker cp command
        # Test execution in new persistent container
        session_id = "test-session-success"
        result = await docker_manager.execute_persistent(
            session_id, "x = 10; y = 20; print('Hello from persistent!')"
        )
        
        # Verify the result
        assert "output" in result
        assert "Success" in result.get("output", "")


@pytest.mark.asyncio
async def test_execute_persistent_existing(docker_manager, mock_docker_client, mock_container):
    """Test execution in an existing persistent container."""
    # Add a test session to the manager
    session_id = "test-session-existing"
    docker_manager.persistent_containers[session_id] = "test-container-id"
    
    # Configure mock container executor
    exec_mock = MagicMock()
    exec_mock.exit_code = 0
    exec_mock.output = b"""---OUTPUT_START---
{
    "__stdout__": "Hello again!",
    "__stderr__": "",
    "__error__": null,
    "result": {"x": 10, "y": 30},
    "output": "Success again"
}
---OUTPUT_END---"""
    mock_container.exec_run.return_value = exec_mock
    
    # Setup proper mocking
    with patch("os.system", return_value=0):  # Mock the docker cp command
        # Test execution in existing container
        result = await docker_manager.execute_persistent(
            session_id, "y = 30; print('Hello again!')"
        )
        
        # Verify the result
        assert "output" in result
        assert "Success again" in result.get("output", "")


@pytest.mark.asyncio
async def test_execute_persistent_error(docker_manager, mock_docker_client, mock_container):
    """Test error handling in persistent container execution."""
    # Setup mock container behavior for creating a new container
    mock_container.attrs["State"]["ExitCode"] = 0
    
    # Configure mock container executor with an error
    exec_mock = MagicMock()
    exec_mock.exit_code = 1  # Error exit code
    exec_mock.output = b"ZeroDivisionError: division by zero"
    mock_container.exec_run.return_value = exec_mock
    
    # Setup proper mocking
    with patch("os.system", return_value=0):  # Mock the docker cp command
        # Test execution with error
        session_id = "test-session-div-error"
        with pytest.raises(DockerExecutionError) as exc_info:
            await docker_manager.execute_persistent(session_id, "print(1/0)")
            
        # Verify error handling
        assert "Execution failed" in str(exc_info.value)
        assert "ZeroDivisionError" in str(exc_info.value)


@pytest.mark.asyncio
async def test_execute_persistent_json_error(docker_manager, mock_docker_client, mock_container):
    """Test handling of JSON parsing errors in persistent execution."""
    # Setup mock container behavior for creating a new container
    mock_container.attrs["State"]["ExitCode"] = 0
    
    # Configure mock container executor with invalid JSON
    exec_mock = MagicMock()
    exec_mock.exit_code = 0
    exec_mock.output = b"---OUTPUT_START---\nThis is not valid JSON\n---OUTPUT_END---"
    mock_container.exec_run.return_value = exec_mock
    
    # Setup proper mocking
    with patch("os.system", return_value=0):  # Mock the docker cp command
        # Should handle JSON parsing error
        session_id = "test-session-json-error"
        result = await docker_manager.execute_persistent(
            session_id, "print('This will produce invalid JSON')"
        )
        
        # Verify error is reported correctly
        assert "output" in result
        assert "This is not valid JSON" in result["output"]


@pytest.mark.asyncio
async def test_install_package_persistent(docker_manager, mock_docker_client, mock_container):
    """Test installing a package in a persistent container."""
    # Setup existing persistent container
    docker_manager.persistent_containers = {"session-1": "test-container-id"}

    # Set up container exec_run to return success for package installation
    mock_container.exec_run.return_value = MagicMock(exit_code=0, output=b"Successfully installed numpy-1.24.0")

    # Install package
    output = await docker_manager.install_package("session-1", "numpy")

    # Verify the exec_run call
    container = mock_docker_client.containers.get.return_value
    container.exec_run.assert_called_once()
    assert "Successfully installed numpy-1.24.0" in output


@pytest.mark.asyncio
async def test_install_package_transient(docker_manager, mock_docker_client, mock_container):
    """Test installing a package in a transient container."""
    # Ensure no persistent containers exist
    docker_manager.persistent_containers = {}

    # Set up container logs to return success for package installation
    mock_container.logs.return_value = b"Successfully installed pandas-2.0.0"

    # Install package
    output = await docker_manager.install_package(None, "pandas")

    # Verify the container run call
    mock_docker_client.containers.run.assert_called_once()
    assert "Successfully installed pandas-2.0.0" in output


def test_create_wrapper_script_with_debugging(docker_manager):
    """Test that the wrapper script includes debugging output."""
    code = "x = 42\nprint(x)"
    script = docker_manager._create_wrapper_script(code)
    
    # Check for enhanced debugging functionality
    assert "Docker wrapper script starting" in script
    assert "Python version" in script
    assert "import traceback" in script
    assert "Current directory" in script
    assert "Directory contents" in script
    assert "Environment" in script
    assert "Executing code" in script
    assert "File exists after writing" in script
    assert "File size" in script
    assert "EXECUTION RESULTS" in script


def test_create_execute_persist_script_with_debugging(docker_manager):
    """Test that the persistent execution script includes debugging output."""
    code = "y = 21 * 2\nprint(y)"
    script = docker_manager._create_execute_persist_script(code)
    
    # Check for enhanced debugging functionality
    assert "Docker persistent execution script starting" in script
    assert "Python version" in script
    assert "import traceback" in script
    assert "Current directory" in script
    assert "Directory contents" in script
    assert "Executing code" in script
    assert "Docker persistent execution script completed" in script


@pytest.mark.asyncio
async def test_execute_transient_with_missing_output_file(docker_manager, mock_docker_client, mock_container):
    """Test handling of missing output file."""
    # Setup mock container behavior
    mock_container.attrs["State"]["ExitCode"] = 0
    
    # Setup proper mocking without a file
    with patch("os.path.exists", return_value=False):
        # Should raise an error about missing output file
        with pytest.raises(DockerExecutionError) as exc_info:
            await docker_manager.execute_transient("print('test')")
        
        assert "Execution failed to produce output state" in str(exc_info.value)
