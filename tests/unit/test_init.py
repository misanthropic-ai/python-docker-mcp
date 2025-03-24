"""Unit tests for the package __init__.py module."""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from python_docker_mcp import check_docker_image_exists, ensure_docker_image, main


def test_check_docker_image_exists_true():
    """Test check_docker_image_exists when image exists."""
    with patch("subprocess.run") as mock_run:
        # Setup mock
        mock_run.return_value = MagicMock(returncode=0)

        # Test function
        result = check_docker_image_exists("test-image:latest")

        # Verify result
        assert result is True
        mock_run.assert_called_once_with(["docker", "image", "inspect", "test-image:latest"], check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def test_check_docker_image_exists_false():
    """Test check_docker_image_exists when image does not exist."""
    with patch("subprocess.run") as mock_run:
        # Setup mock
        mock_run.return_value = MagicMock(returncode=1)

        # Test function
        result = check_docker_image_exists("nonexistent-image:latest")

        # Verify result
        assert result is False


def test_check_docker_image_exists_exception():
    """Test check_docker_image_exists handles exceptions."""
    with patch("subprocess.run") as mock_run:
        # Setup mock
        mock_run.side_effect = Exception("Docker error")

        # Test function
        result = check_docker_image_exists("test-image:latest")

        # Verify result
        assert result is False


def test_ensure_docker_image_exists():
    """Test ensure_docker_image when the image already exists."""
    with (
        patch("python_docker_mcp.check_docker_image_exists") as mock_check,
        patch("python_docker_mcp.config.load_config") as mock_load_config,
        patch("python_docker_mcp.build_docker_image") as mock_build,
    ):

        # Setup mocks
        mock_check.return_value = True
        mock_config = MagicMock()
        mock_config.docker.image = "default-image:latest"
        mock_load_config.return_value = mock_config

        # Test function
        ensure_docker_image()

        # Verify the image was not built
        mock_check.assert_called_once_with("default-image:latest")
        mock_build.assert_not_called()


def test_ensure_docker_image_build_success():
    """Test ensure_docker_image when the image needs to be built (success)."""
    with patch("python_docker_mcp.check_docker_image_exists") as mock_check, patch("python_docker_mcp.build_docker_image") as mock_build:

        # Setup mocks
        mock_check.return_value = False
        mock_build.return_value = True

        # Test function with explicit image name
        ensure_docker_image("custom-image:latest")

        # Verify the image was built
        mock_check.assert_called_once_with("custom-image:latest")
        mock_build.assert_called_once_with(tag="custom-image:latest")


def test_ensure_docker_image_build_fail_retry():
    """Test ensure_docker_image when first build fails, retry succeeds."""
    with patch("python_docker_mcp.check_docker_image_exists") as mock_check, patch("python_docker_mcp.build_docker_image") as mock_build:

        # Setup mocks
        mock_check.return_value = False
        # First call fails, second call succeeds
        mock_build.side_effect = [False, True]

        # Test function
        ensure_docker_image("test-image:latest")

        # Verify the image was built twice
        assert mock_build.call_count == 2
        # First without debug
        mock_build.assert_any_call(tag="test-image:latest")
        # Second with debug
        mock_build.assert_any_call(tag="test-image:latest", debug=True)


def test_ensure_docker_image_build_fail_both():
    """Test ensure_docker_image when both build attempts fail."""
    with patch("python_docker_mcp.check_docker_image_exists") as mock_check, patch("python_docker_mcp.build_docker_image") as mock_build:

        # Setup mocks
        mock_check.return_value = False
        mock_build.return_value = False

        # Test function
        ensure_docker_image("test-image:latest")

        # Verify the image was built twice
        assert mock_build.call_count == 2
        # First without debug
        mock_build.assert_any_call(tag="test-image:latest")
        # Second with debug
        mock_build.assert_any_call(tag="test-image:latest", debug=True)


@patch("asyncio.run")
@patch("python_docker_mcp.ensure_docker_image")
@patch("python_docker_mcp.server.main")
def test_main(mock_server_main, mock_ensure_docker, mock_asyncio_run):
    """Test the main function."""
    # Call the function
    main()

    # Verify the calls
    mock_ensure_docker.assert_called_once()
    # Just verify asyncio.run was called (don't check the exact coroutine)
    assert mock_asyncio_run.call_count == 1


@patch("asyncio.run")
@patch("python_docker_mcp.ensure_docker_image")
@patch("python_docker_mcp.server.main")
def test_main_exception(mock_server_main, mock_ensure_docker, mock_asyncio_run):
    """Test the main function when an exception occurs."""
    # Setup mocks to raise an exception
    mock_ensure_docker.side_effect = Exception("Test error")

    # Call the function - should raise the exception
    with pytest.raises(Exception) as exc_info:
        main()

    # Verify the exception
    assert "Test error" in str(exc_info.value)
