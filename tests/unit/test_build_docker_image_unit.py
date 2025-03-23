"""Unit tests for build_docker_image.py."""

import os
import shutil
import subprocess
import tempfile
from unittest.mock import MagicMock, call, mock_open, patch

import pytest

from python_docker_mcp.build_docker_image import (
    build_docker_image,
    get_dockerfile_path,
    main,
)


@patch("pkg_resources.resource_filename")
def test_get_dockerfile_path_package(mock_resource_filename):
    """Test getting the Dockerfile path from the package."""
    mock_resource_filename.return_value = "/path/to/package/Dockerfile"
    path = get_dockerfile_path()
    assert path == "/path/to/package/Dockerfile"
    mock_resource_filename.assert_called_once_with("python_docker_mcp", "Dockerfile")


@patch("os.path.dirname")
@patch("pkg_resources.resource_filename")
def test_get_dockerfile_path_fallback(mock_resource_filename, mock_dirname):
    """Test fallback when resource_filename raises an exception."""
    # Make resource_filename raise an exception
    mock_resource_filename.side_effect = Exception("Resource not found")
    
    # Set up the fallback path
    mock_dirname.return_value = "/path/to/module"
    expected_path = os.path.join("/path/to/module", "Dockerfile")
    
    # Call the function
    path = get_dockerfile_path()
    
    # Verify the result
    assert path == expected_path
    mock_resource_filename.assert_called_once_with("python_docker_mcp", "Dockerfile")
    mock_dirname.assert_called_once()


@patch("shutil.copy2")
@patch("tempfile.TemporaryDirectory")
@patch("subprocess.run")
@patch("os.path.exists")
def test_build_docker_image_success(mock_exists, mock_run, mock_temp_dir, mock_copy2):
    """Test successful Docker image build."""
    # Setup mocks
    mock_exists.return_value = True
    mock_temp_dir.return_value.__enter__.return_value = "/tmp/tempdir"
    mock_run.return_value = subprocess.CompletedProcess(
        args=["docker", "build"], returncode=0, stdout=b"", stderr=b""
    )
    
    # Call the function
    result = build_docker_image("test-image:latest", "/path/to/Dockerfile")
    
    # Verify the result
    assert result is True
    mock_exists.assert_called_once_with("/path/to/Dockerfile")
    mock_copy2.assert_called_once_with("/path/to/Dockerfile", "/tmp/tempdir/Dockerfile")
    mock_run.assert_called_once()
    # Verify build command arguments
    cmd_args = mock_run.call_args[0][0]
    assert "docker" in cmd_args
    assert "build" in cmd_args
    assert "-t" in cmd_args
    assert "test-image:latest" in cmd_args


@patch("shutil.copy2")
@patch("tempfile.TemporaryDirectory")
@patch("subprocess.run")
@patch("os.path.exists")
def test_build_docker_image_with_build_args(mock_exists, mock_run, mock_temp_dir, mock_copy2):
    """Test Docker image build with build arguments."""
    # Setup mocks
    mock_exists.return_value = True
    mock_temp_dir.return_value.__enter__.return_value = "/tmp/tempdir"
    mock_run.return_value = subprocess.CompletedProcess(
        args=["docker", "build"], returncode=0, stdout=b"", stderr=b""
    )
    
    # Build args to test
    build_args = {"PYTHON_VERSION": "3.11", "DEBUG": "true"}
    
    # Call the function
    result = build_docker_image("test-image:latest", "/path/to/Dockerfile", build_args)
    
    # Verify the result
    assert result is True
    mock_copy2.assert_called_once_with("/path/to/Dockerfile", "/tmp/tempdir/Dockerfile")
    
    # Verify build args were included in the command
    cmd_args = mock_run.call_args[0][0]
    assert "--build-arg" in cmd_args
    assert "PYTHON_VERSION=3.11" in cmd_args
    assert "--build-arg" in cmd_args
    assert "DEBUG=true" in cmd_args


@patch("shutil.copy2")
@patch("tempfile.TemporaryDirectory")
@patch("subprocess.run")
@patch("os.path.exists")
def test_build_docker_image_failure(mock_exists, mock_run, mock_temp_dir, mock_copy2):
    """Test Docker image build failure."""
    # Setup mocks
    mock_exists.return_value = True
    mock_temp_dir.return_value.__enter__.return_value = "/tmp/tempdir"
    mock_run.side_effect = subprocess.CalledProcessError(1, "docker build")
    
    # Call the function
    result = build_docker_image("test-image:latest", "/path/to/Dockerfile")
    
    # Verify the result
    assert result is False
    mock_exists.assert_called_once_with("/path/to/Dockerfile")
    mock_copy2.assert_called_once_with("/path/to/Dockerfile", "/tmp/tempdir/Dockerfile")


@patch("os.path.exists")
def test_build_docker_image_dockerfile_not_found(mock_exists):
    """Test Docker image build with missing Dockerfile."""
    # Setup mocks
    mock_exists.return_value = False
    
    # Call the function
    result = build_docker_image("test-image:latest", "/path/to/nonexistent/Dockerfile")
    
    # Verify the result
    assert result is False
    mock_exists.assert_called_once_with("/path/to/nonexistent/Dockerfile")


@patch("argparse.ArgumentParser.parse_args")
@patch("python_docker_mcp.build_docker_image.build_docker_image")
def test_main_default_args(mock_build_docker_image, mock_parse_args):
    """Test main function with default arguments."""
    # Setup mock arguments
    args = MagicMock()
    args.tag = "python-docker-mcp:latest"
    args.dockerfile = None
    args.build_arg = []
    mock_parse_args.return_value = args
    
    # Call the function
    main()
    
    # Verify the build function was called with the right arguments
    mock_build_docker_image.assert_called_once_with(
        tag="python-docker-mcp:latest", dockerfile=None, build_args={}
    )


@patch("argparse.ArgumentParser.parse_args")
@patch("python_docker_mcp.build_docker_image.build_docker_image")
def test_main_custom_args(mock_build_docker_image, mock_parse_args):
    """Test main function with custom arguments."""
    # Setup mock arguments
    args = MagicMock()
    args.tag = "custom-image:1.0"
    args.dockerfile = "/custom/Dockerfile"
    args.build_arg = ["VERSION=1.0", "DEBUG=true"]
    mock_parse_args.return_value = args
    
    # Call the function
    main()
    
    # Verify the build function was called with the right arguments
    expected_build_args = {"VERSION": "1.0", "DEBUG": "true"}
    mock_build_docker_image.assert_called_once_with(
        tag="custom-image:1.0", dockerfile="/custom/Dockerfile", build_args=expected_build_args
    )


@patch("argparse.ArgumentParser.parse_args")
@patch("python_docker_mcp.build_docker_image.build_docker_image")
def test_main_build_success(mock_build_docker_image, mock_parse_args):
    """Test main function with successful build."""
    # Setup mock arguments
    args = MagicMock()
    args.tag = "python-docker-mcp:latest"
    args.dockerfile = None
    args.build_arg = []
    mock_parse_args.return_value = args
    
    # Setup build result
    mock_build_docker_image.return_value = True
    
    # Call the function
    with patch("sys.exit") as mock_exit:
        main()
        mock_exit.assert_called_once_with(0)


@patch("argparse.ArgumentParser.parse_args")
@patch("python_docker_mcp.build_docker_image.build_docker_image")
def test_main_build_failure(mock_build_docker_image, mock_parse_args):
    """Test main function with failed build."""
    # Setup mock arguments
    args = MagicMock()
    args.tag = "python-docker-mcp:latest"
    args.dockerfile = None
    args.build_arg = []
    mock_parse_args.return_value = args
    
    # Setup build result
    mock_build_docker_image.return_value = False
    
    # Call the function
    with patch("sys.exit") as mock_exit:
        main()
        mock_exit.assert_called_once_with(1) 