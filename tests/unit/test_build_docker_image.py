"""Unit tests for the build_docker_image module."""

import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from python_docker_mcp.build_docker_image import (
    build_docker_image,
    get_dockerfile_path,
    main,
)


def test_get_dockerfile_path():
    """Test getting the Dockerfile path."""
    with patch("pkg_resources.resource_filename") as mock_resource_filename:
        mock_resource_filename.return_value = "/package/path/Dockerfile"
        path = get_dockerfile_path()
        assert path == "/package/path/Dockerfile"


def test_get_dockerfile_path_fallback():
    """Test getting the Dockerfile path with fallback."""
    with patch("pkg_resources.resource_filename") as mock_resource_filename:
        mock_resource_filename.side_effect = Exception("Resource not found")
        with patch("os.path.dirname") as mock_dirname:
            mock_dirname.return_value = "/local/path"
            path = get_dockerfile_path()
            assert path == "/local/path/Dockerfile"


@patch("subprocess.run")
@patch("os.path.exists", return_value=True)
def test_build_docker_image_success(mock_exists, mock_run):
    """Test successful Docker image build."""
    # Setup mock
    mock_run.return_value = MagicMock(
        check=True,
        returncode=0,
        stdout="Successfully built test-image",
        stderr="",
    )
    
    # Test function
    result = build_docker_image("test-image:latest", "/path/to/Dockerfile")
    
    # Verify results
    assert result is True
    mock_run.assert_called_once()
    
    # Verify Docker build command
    cmd = mock_run.call_args[0][0]
    assert "docker" in cmd
    assert "build" in cmd
    assert "-t" in cmd
    assert "test-image:latest" in cmd


@patch("subprocess.run")
@patch("os.path.exists", return_value=True)
def test_build_docker_image_with_build_args(mock_exists, mock_run):
    """Test Docker image build with build arguments."""
    # Setup mock
    mock_run.return_value = MagicMock(
        check=True,
        returncode=0,
        stdout="Successfully built test-image",
        stderr="",
    )
    
    # Test function with build args
    build_args = {"PYTHON_VERSION": "3.12", "INSTALL_DEV": "true"}
    result = build_docker_image("test-image:latest", "/path/to/Dockerfile", build_args)
    
    # Verify results
    assert result is True
    mock_run.assert_called_once()
    
    # Verify build args were passed
    cmd = mock_run.call_args[0][0]
    assert "--build-arg" in cmd
    assert "PYTHON_VERSION=3.12" in cmd
    assert "--build-arg" in cmd
    assert "INSTALL_DEV=true" in cmd


@patch("subprocess.run")
@patch("os.path.exists", return_value=True)
def test_build_docker_image_failure(mock_exists, mock_run):
    """Test Docker image build failure."""
    # Setup mock
    mock_run.side_effect = Exception("Build failed")
    
    # Test function
    result = build_docker_image("test-image:latest", "/path/to/Dockerfile")
    
    # Verify results
    assert result is False


@patch("os.path.exists", return_value=False)
def test_build_docker_image_missing_dockerfile(mock_exists):
    """Test Docker image build with missing Dockerfile."""
    # Test function
    result = build_docker_image("test-image:latest", "/path/to/nonexistent/Dockerfile")
    
    # Verify results
    assert result is False


@patch("python_docker_mcp.build_docker_image.build_docker_image")
def test_main_success(mock_build):
    """Test main function success."""
    # Setup mock
    mock_build.return_value = True
    
    # Test function with args
    with patch("sys.argv", ["build_docker_image.py", "--tag", "test-image:latest"]):
        exit_code = main()
    
    # Verify results
    assert exit_code == 0
    mock_build.assert_called_once_with("test-image:latest", None, {})


@patch("python_docker_mcp.build_docker_image.build_docker_image")
def test_main_with_custom_dockerfile(mock_build):
    """Test main function with custom Dockerfile."""
    # Create a temporary Dockerfile
    with tempfile.NamedTemporaryFile(suffix=".Dockerfile") as f:
        # Setup mock
        mock_build.return_value = True
        
        # Test function with custom Dockerfile
        with patch("sys.argv", ["build_docker_image.py", "--dockerfile", f.name]):
            exit_code = main()
        
        # Verify results
        assert exit_code == 0
        mock_build.assert_called_once_with("python-docker-mcp:latest", f.name, {})


@patch("python_docker_mcp.build_docker_image.build_docker_image")
def test_main_with_build_args(mock_build):
    """Test main function with build args."""
    # Setup mock
    mock_build.return_value = True
    
    # Test function with build args
    with patch("sys.argv", [
        "build_docker_image.py",
        "--build-arg", "PYTHON_VERSION=3.12",
        "--build-arg", "DEBUG=true"
    ]):
        exit_code = main()
    
    # Verify results
    assert exit_code == 0
    mock_build.assert_called_once_with(
        "python-docker-mcp:latest",
        None,
        {"PYTHON_VERSION": "3.12", "DEBUG": "true"}
    )


@patch("python_docker_mcp.build_docker_image.build_docker_image")
def test_main_failure(mock_build):
    """Test main function failure."""
    # Setup mock
    mock_build.return_value = False
    
    # Test function
    with patch("sys.argv", ["build_docker_image.py"]):
        exit_code = main()
    
    # Verify results
    assert exit_code == 1 