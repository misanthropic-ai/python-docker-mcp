"""Unit tests for build_docker_image.py."""

import subprocess
from unittest.mock import ANY, patch

import pkg_resources

from python_docker_mcp.build_docker_image import build_docker_image, get_dockerfile_path, main


@patch("pkg_resources.resource_filename")
def test_get_dockerfile_path_package(mock_resource_filename):
    """Test get_dockerfile_path returns the right path when package is available."""
    mock_resource_filename.return_value = "/path/to/package/Dockerfile"
    assert get_dockerfile_path() == "/path/to/package/Dockerfile"
    mock_resource_filename.assert_called_once_with("python_docker_mcp", "Dockerfile")


@patch("os.path.dirname")
@patch("pkg_resources.resource_filename")
def test_get_dockerfile_path_fallback(mock_resource_filename, mock_dirname):
    """Test get_dockerfile_path falls back to local path when package not found."""
    # Make resource_filename raise a DistributionNotFound exception
    mock_resource_filename.side_effect = pkg_resources.DistributionNotFound("Resource not found")

    # Setup mock for directory path
    mock_dirname.return_value = "/local/path"

    # We need to add a mock for os.path.abspath as well
    with patch("os.path.abspath") as mock_abspath:
        mock_abspath.return_value = "/local/path/__file__"

        # Call the function
        result = get_dockerfile_path()

        # Verify the result
        assert result == "/local/path/Dockerfile"


@patch("shutil.copy2")
@patch("tempfile.TemporaryDirectory")
@patch("subprocess.run")
@patch("os.path.exists")
def test_build_docker_image_success(mock_exists, mock_run, mock_temp_dir, mock_copy2):
    """Test successful Docker image build."""
    # Setup mocks
    mock_exists.return_value = True
    mock_temp_dir.return_value.__enter__.return_value = "/tmp/build_context"
    mock_run.return_value.returncode = 0

    # Call the function
    result = build_docker_image("test:latest")

    # Verify results
    assert result is True
    mock_run.assert_called_once_with(
        ["docker", "build", "-t", "test:latest", "."],
        cwd="/tmp/build_context",
        check=True,
        stdout=ANY,
        stderr=ANY,
        universal_newlines=True,
    )


@patch("shutil.copy2")
@patch("tempfile.TemporaryDirectory")
@patch("subprocess.run")
@patch("os.path.exists")
def test_build_docker_image_with_build_args(mock_exists, mock_run, mock_temp_dir, mock_copy2):
    """Test Docker image build with build arguments."""
    # Setup mocks
    mock_exists.return_value = True
    mock_temp_dir.return_value.__enter__.return_value = "/tmp/build_context"
    mock_run.return_value.returncode = 0

    # Call the function with build args
    build_args = {"VERSION": "1.0", "DEBUG": "true"}
    result = build_docker_image("test:latest", build_args=build_args)

    # Verify results
    assert result is True
    mock_run.assert_called_once_with(
        ["docker", "build", "-t", "test:latest", ".", "--build-arg", "VERSION=1.0", "--build-arg", "DEBUG=true"],
        cwd="/tmp/build_context",
        check=True,
        stdout=ANY,
        stderr=ANY,
        universal_newlines=True,
    )


@patch("shutil.copy2")
@patch("tempfile.TemporaryDirectory")
@patch("subprocess.run")
@patch("os.path.exists")
def test_build_docker_image_failure(mock_exists, mock_run, mock_temp_dir, mock_copy2):
    """Test Docker image build failure."""
    # Setup mocks
    mock_exists.return_value = True
    mock_temp_dir.return_value.__enter__.return_value = "/tmp/build_context"
    mock_run.side_effect = subprocess.CalledProcessError(1, "docker build", stderr="Build failed")

    # Call the function
    result = build_docker_image("test:latest")

    # Verify results
    assert result is False


@patch("os.path.exists")
def test_build_docker_image_dockerfile_not_found(mock_exists):
    """Test error handling when Dockerfile is not found."""
    mock_exists.return_value = False

    # Call the function
    result = build_docker_image(dockerfile="/nonexistent/Dockerfile")

    # Verify results
    assert result is False


@patch("python_docker_mcp.build_docker_image.build_docker_image")
def test_main_default_args(mock_build_docker_image):
    """Test main function with default arguments."""
    # Setup mock
    mock_build_docker_image.return_value = True

    # Mock sys.argv
    with patch("sys.argv", ["build_docker_image.py"]):
        # Call the function
        exit_code = main()

        # Verify the build function was called
        mock_build_docker_image.assert_called_once()
        args, kwargs = mock_build_docker_image.call_args
        assert kwargs.get("tag") == "python-docker-mcp:latest" or args[0] == "python-docker-mcp:latest"

        # Verify exit code
        assert exit_code == 0


@patch("python_docker_mcp.build_docker_image.build_docker_image")
def test_main_custom_args(mock_build_docker_image):
    """Test main function with custom arguments."""
    # Setup mock
    mock_build_docker_image.return_value = True

    # Mock sys.argv
    with patch(
        "sys.argv",
        [
            "build_docker_image.py",
            "--tag",
            "custom-image:1.0",
            "--dockerfile",
            "/custom/Dockerfile",
            "--build-arg",
            "VERSION=1.0",
            "--build-arg",
            "DEBUG=true",
            "--debug",
        ],
    ):
        # Call the function
        exit_code = main()

        # Verify the build function was called
        mock_build_docker_image.assert_called_once()
        args, kwargs = mock_build_docker_image.call_args

        # Check positional args - args[0] is tag, args[1] is dockerfile, args[2] is build_args
        assert args[0] == "custom-image:1.0"
        assert args[1] == "/custom/Dockerfile"

        # Verify build_args and debug are present
        build_args = args[2]
        assert "VERSION" in build_args
        assert build_args["VERSION"] == "1.0"
        assert "DEBUG" in build_args
        assert build_args["DEBUG"] == "true"

        # Verify debug flag (positional arg 3)
        assert args[3] is True

        # Verify exit code
        assert exit_code == 0


@patch("python_docker_mcp.build_docker_image.build_docker_image")
def test_main_build_success(mock_build_docker_image):
    """Test main function with successful build."""
    # Setup mock
    mock_build_docker_image.return_value = True

    # Mock sys.argv
    with patch("sys.argv", ["build_docker_image.py"]):
        # Call the function
        exit_code = main()

        # Verify exit code
        assert exit_code == 0


@patch("python_docker_mcp.build_docker_image.build_docker_image")
def test_main_build_failure(mock_build_docker_image):
    """Test main function with failed build."""
    # Setup mock
    mock_build_docker_image.return_value = False

    # Mock sys.argv
    with patch("sys.argv", ["build_docker_image.py"]):
        # Call the function
        exit_code = main()

        # Verify exit code
        assert exit_code == 1
