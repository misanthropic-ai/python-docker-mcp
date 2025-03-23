"""Unit tests for the docker_manager module."""

import asyncio
import json
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from python_docker_mcp.docker_manager import DockerExecutionError, DockerManager


@pytest.mark.asyncio
async def test_execute_transient_success(docker_manager, mock_docker_client, mock_container):
    """Test successful execution in a transient container."""
    # Setup mock container behavior
    mock_container.attrs["State"]["ExitCode"] = 0
    
    # Create a mocked output.json file that the container would normally write
    with tempfile.TemporaryDirectory() as temp_dir:
        output_file = os.path.join(temp_dir, "output.json")
        with open(output_file, "w") as f:
            json.dump({
                "__stdout__": "Hello, world!",
                "__stderr__": "",
                "__error__": None,
                "result": 42
            }, f)
            
        # Patch os.path.exists and open to use our temporary file
        with patch("os.path.exists", return_value=True), \
             patch("builtins.open", return_value=open(output_file, "r")):
            result = await docker_manager.execute_transient("print('Hello, world!')")
            
            # Verify the result
            assert result["__stdout__"] == "Hello, world!"
            assert result["__error__"] is None
            assert result["result"] == 42


@pytest.mark.asyncio
async def test_execute_transient_error(docker_manager, mock_docker_client, mock_container):
    """Test handling of container execution errors."""
    # Setup container to return an error
    mock_container.attrs["State"]["ExitCode"] = 1
    mock_container.logs.return_value = b"Error: Python execution failed"
    
    # Test that the error is properly propagated
    with pytest.raises(DockerExecutionError) as exc_info:
        await docker_manager.execute_transient("invalid python code")
    
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
    """Test executing code in a new persistent container."""
    # Make sure the persistent container doesn't exist yet
    docker_manager.persistent_containers = {}
    
    # Execute code in a persistent container
    result = await docker_manager.execute_persistent("session-1", "print('Hello from persistent container')")
    
    # Verify container creation
    mock_docker_client.containers.run.assert_called_once()
    assert "session-1" in docker_manager.persistent_containers
    
    # Verify result
    assert result["output"] == "Test output"
    assert result["error"] is None


@pytest.mark.asyncio
async def test_execute_persistent_existing_container(docker_manager, mock_docker_client, mock_container):
    """Test executing code in an existing persistent container."""
    # Setup existing persistent container
    docker_manager.persistent_containers = {"session-1": "test-container-id"}
    
    # Execute code in the existing container
    result = await docker_manager.execute_persistent("session-1", "print('Hello again')")
    
    # Verify we reused the container
    mock_docker_client.containers.run.assert_not_called()
    mock_docker_client.containers.get.assert_called_with("test-container-id")
    
    # Verify the exec_run call
    container = mock_docker_client.containers.get.return_value
    container.exec_run.assert_called_once()
    
    # Verify result
    assert result["output"] == "Test output"
    assert result["error"] is None


@pytest.mark.asyncio
async def test_execute_persistent_json_parsing_error(docker_manager, mock_docker_client, mock_container):
    """Test handling of JSON parsing errors in persistent container output."""
    # Setup container to return invalid JSON
    mock_container.exec_run.return_value = MagicMock(
        exit_code=0, 
        output=b"---OUTPUT_START---\nNot valid JSON\n---OUTPUT_END---"
    )
    
    # Setup existing persistent container
    docker_manager.persistent_containers = {"session-1": "test-container-id"}
    
    # Execute code and expect fallback to raw output
    result = await docker_manager.execute_persistent("session-1", "print('Invalid JSON')")
    
    # Verify result contains raw output
    assert result["output"] == "---OUTPUT_START---\nNot valid JSON\n---OUTPUT_END---"
    assert result["error"] is None


@pytest.mark.asyncio
async def test_execute_persistent_execution_error(docker_manager, mock_docker_client, mock_container):
    """Test handling of execution errors in persistent container."""
    # Setup container to return an error code
    mock_container.exec_run.return_value = MagicMock(
        exit_code=1, 
        output=b"SyntaxError: invalid syntax"
    )
    
    # Setup existing persistent container
    docker_manager.persistent_containers = {"session-1": "test-container-id"}
    
    # Execute code and expect DockerExecutionError
    with pytest.raises(DockerExecutionError) as exc_info:
        await docker_manager.execute_persistent("session-1", "invalid python")
    
    assert "Execution failed" in str(exc_info.value)
    assert "SyntaxError" in str(exc_info.value)


@pytest.mark.asyncio
async def test_install_package_persistent(docker_manager, mock_docker_client, mock_container):
    """Test installing a package in a persistent container."""
    # Setup existing persistent container
    docker_manager.persistent_containers = {"session-1": "test-container-id"}
    
    # Set up container exec_run to return success for package installation
    mock_container.exec_run.return_value = MagicMock(
        exit_code=0,
        output=b"Successfully installed numpy-1.24.0"
    )
    
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
        "session-2": "container-id-2"
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