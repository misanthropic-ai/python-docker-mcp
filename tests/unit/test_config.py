"""Unit tests for the config module."""

import os
from unittest.mock import patch

import pytest
import yaml

from python_docker_mcp.config import Configuration, DockerConfig, PackageConfig, get_default_config, load_config


def test_docker_config_defaults():
    """Test DockerConfig initializes with default values."""
    config = DockerConfig()
    assert config.image == "python:3.12.2-slim"
    assert config.working_dir == "/app"
    assert config.memory_limit == "256m"
    assert config.cpu_limit == 0.5
    assert config.timeout == 30
    assert config.network_disabled is True
    assert config.read_only is True


def test_package_config_defaults():
    """Test PackageConfig initializes with default values."""
    config = PackageConfig()
    assert config.installer == "uv"
    assert config.index_url is None
    assert config.trusted_hosts == []


def test_configuration_defaults():
    """Test Configuration initializes with default values."""
    config = Configuration()
    assert isinstance(config.docker, DockerConfig)
    assert isinstance(config.package, PackageConfig)
    assert "math" in config.allowed_modules
    assert "datetime" in config.allowed_modules
    assert "os" in config.blocked_modules
    assert "sys" in config.blocked_modules


def test_configuration_custom_values():
    """Test Configuration initializes with custom values."""
    docker_config = DockerConfig(image="custom-image:latest", memory_limit="512m")
    package_config = PackageConfig(installer="pip", index_url="https://pypi.org/simple")
    config = Configuration(
        docker=docker_config,
        package=package_config,
        allowed_modules=["numpy", "pandas"],
        blocked_modules=["socket"],
    )

    assert config.docker.image == "custom-image:latest"
    assert config.docker.memory_limit == "512m"
    assert config.package.installer == "pip"
    assert config.package.index_url == "https://pypi.org/simple"
    assert config.allowed_modules == ["numpy", "pandas"]
    assert config.blocked_modules == ["socket"]


@patch("pkg_resources.resource_filename")
def test_get_default_config_from_package(mock_resource_filename, tmp_path):
    """Test loading default config from package."""
    # Setup mock config file
    config_path = tmp_path / "default_config.yaml"
    mock_config = {
        "docker": {"image": "test-image"},
        "allowed_modules": ["test_module"],
    }
    with open(config_path, "w") as f:
        yaml.dump(mock_config, f)

    mock_resource_filename.return_value = str(config_path)

    # Test function
    config = get_default_config()
    assert config["docker"]["image"] == "test-image"
    assert config["allowed_modules"] == ["test_module"]


@patch("pkg_resources.resource_filename")
def test_get_default_config_fallback(mock_resource_filename, tmp_path):
    """Test fallback when resource_filename raises an exception."""
    # Make resource_filename raise an exception
    mock_resource_filename.side_effect = Exception("Resource not found")

    # Setup mock file in the local path
    with patch("os.path.dirname") as mock_dirname:
        mock_dirname.return_value = str(tmp_path)
        config_path = tmp_path / "default_config.yaml"
        mock_config = {
            "docker": {"image": "local-image"},
            "allowed_modules": ["local_module"],
        }
        with open(config_path, "w") as f:
            yaml.dump(mock_config, f)

        # Test function
        config = get_default_config()
        assert config["docker"]["image"] == "local-image"
        assert config["allowed_modules"] == ["local_module"]


def test_load_config_with_file(temp_config_file):
    """Test loading configuration from a file."""
    config = load_config(temp_config_file)
    assert config.docker.image == "python:3.12.2-slim"
    assert config.docker.timeout == 10
    assert config.allowed_modules == ["math", "datetime", "random", "json"]


def test_load_config_with_env_var(temp_config_file):
    """Test loading configuration from environment variable."""
    with patch.dict(os.environ, {"PYTHON_DOCKER_MCP_CONFIG": temp_config_file}):
        config = load_config()
        assert config.docker.image == "python:3.12.2-slim"
        assert config.docker.timeout == 10


def test_load_config_no_file():
    """Test loading default configuration when no file exists."""
    with patch("os.path.exists", return_value=False):
        config = load_config("/non/existent/path.yaml")
        assert isinstance(config, Configuration)
        assert config.docker.image == "python:3.12.2-slim"


def test_load_config_invalid_file(tmp_path):
    """Test handling of invalid configuration file."""
    # Create an invalid YAML file
    invalid_file = tmp_path / "invalid.yaml"
    with open(invalid_file, "w") as f:
        f.write("this is not valid yaml: :")

    # Should fall back to defaults when file is invalid
    config = load_config(str(invalid_file))
    assert isinstance(config, Configuration)
    assert config.docker.image == "python:3.12.2-slim"
