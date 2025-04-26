"""Configuration module for the Python Docker MCP server."""

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, cast

import pkg_resources
import yaml


@dataclass
class DockerConfig:
    """Configuration for the Docker execution environment."""

    image: str = "python:3.12.2-slim"
    working_dir: str = "/app"
    memory_limit: str = "256m"
    cpu_limit: float = 0.5
    timeout: int = 30  # seconds
    network_disabled: bool = True
    read_only: bool = True
    # Container pooling settings
    pool_enabled: bool = True  # Set to True to enable container pooling
    pool_size: int = 32  # Maximum number of containers in the pool
    pool_max_age: int = 300  # Maximum container lifetime in seconds (5 minutes)
    max_concurrent_creations: int = 5  # Limit concurrent container creation


@dataclass
class PackageConfig:
    """Configuration for package management."""

    installer: Literal["uv", "pip"] = "uv"
    index_url: Optional[str] = None
    trusted_hosts: List[str] = field(default_factory=list)


@dataclass
class Configuration:
    """Main configuration for the Python Docker MCP server."""

    docker: DockerConfig = field(default_factory=DockerConfig)
    package: PackageConfig = field(default_factory=PackageConfig)
    allowed_modules: List[str] = field(
        default_factory=lambda: [
            "math",
            "datetime",
            "random",
            "json",
            "re",
            "collections",
        ]
    )
    blocked_modules: List[str] = field(default_factory=lambda: ["os", "sys", "subprocess", "shutil", "pathlib"])


def get_default_config() -> Dict[str, Any]:
    """Load the default configuration from the package's default_config.yaml file.

    Returns:
        Dictionary containing the default configuration values
    """
    try:
        default_config_path = pkg_resources.resource_filename("python_docker_mcp", "default_config.yaml")
        with open(default_config_path, "r") as f:
            config = yaml.safe_load(f)
            return config if config else {}
    except (pkg_resources.DistributionNotFound, FileNotFoundError):
        # Fall back to local path for development
        current_dir = os.path.dirname(os.path.abspath(__file__))
        default_config_path = os.path.join(current_dir, "default_config.yaml")
        try:
            with open(default_config_path, "r") as f:
                config = yaml.safe_load(f)
                return config if config else {}
        except FileNotFoundError:
            # Return empty dict if default config file not found
            return {}


def load_config(config_path: Optional[str] = None) -> Configuration:
    """Load configuration from a YAML file, with fallback to default values.

    Args:
        config_path: Optional path to a custom configuration file

    Returns:
        Configuration object with applied settings
    """
    # Load default configuration
    default_config_data = get_default_config()

    # Create default configuration object
    docker_config = DockerConfig()
    package_config = PackageConfig()

    # Apply default config data if available
    if default_config_data:
        if "docker" in default_config_data:
            docker = default_config_data["docker"]
            for key, value in docker.items():
                if hasattr(docker_config, key):
                    setattr(docker_config, key, value)

        if "package" in default_config_data:
            package = default_config_data["package"]
            for key, value in package.items():
                if hasattr(package_config, key):
                    setattr(package_config, key, value)

    # Get allowed and blocked modules with proper type handling
    allowed_modules: List[str] = default_config_data.get("allowed_modules", [])
    blocked_modules: List[str] = default_config_data.get("blocked_modules", [])

    # Ensure allowed_modules and blocked_modules are always lists
    if allowed_modules is None:
        allowed_modules = []
    if blocked_modules is None:
        blocked_modules = []

    default_config = Configuration(
        docker=docker_config,
        package=package_config,
        allowed_modules=allowed_modules,
        blocked_modules=blocked_modules,
    )

    # If no custom config path provided, look in standard locations
    if not config_path:
        # Check environment variable
        config_path = os.environ.get("PYTHON_DOCKER_MCP_CONFIG")

        # Check user config directory
        if not config_path or not os.path.exists(config_path):
            config_dir = os.path.join(os.path.expanduser("~"), ".python-docker-mcp")
            config_path = os.path.join(config_dir, "config.yaml")

    # If custom config exists, apply it on top of defaults
    if config_path and os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
                config_data = yaml.safe_load(f) or {}

            # Parse docker configuration
            if "docker" in config_data:
                docker = config_data["docker"]
                for key, value in docker.items():
                    if hasattr(default_config.docker, key):
                        setattr(default_config.docker, key, value)

            # Parse package configuration
            if "package" in config_data:
                package = config_data["package"]
                for key, value in package.items():
                    if hasattr(default_config.package, key):
                        setattr(default_config.package, key, value)

            # Apply other settings
            if "allowed_modules" in config_data:
                modules = config_data["allowed_modules"]
                default_config.allowed_modules = [] if modules is None else cast(List[str], modules)

            if "blocked_modules" in config_data:
                modules = config_data["blocked_modules"]
                default_config.blocked_modules = [] if modules is None else cast(List[str], modules)

        except Exception as e:
            print(f"Error loading configuration from {config_path}: {e}")

    # Override configuration with environment variables if provided
    # Docker pool settings
    env = os.environ
    if "PYTHON_DOCKER_MCP_POOL_ENABLED" in env:
        val = env.get("PYTHON_DOCKER_MCP_POOL_ENABLED", "").lower()
        default_config.docker.pool_enabled = val in ("1", "true", "yes")
    if "PYTHON_DOCKER_MCP_POOL_SIZE" in env:
        try:
            default_config.docker.pool_size = int(env.get("PYTHON_DOCKER_MCP_POOL_SIZE", default_config.docker.pool_size))
        except ValueError:
            pass
    if "PYTHON_DOCKER_MCP_POOL_MAX_AGE" in env:
        try:
            default_config.docker.pool_max_age = int(env.get("PYTHON_DOCKER_MCP_POOL_MAX_AGE", default_config.docker.pool_max_age))
        except ValueError:
            pass
    if "PYTHON_DOCKER_MCP_MAX_CONCURRENT_CREATIONS" in env:
        try:
            default_config.docker.max_concurrent_creations = int(env.get("PYTHON_DOCKER_MCP_MAX_CONCURRENT_CREATIONS", default_config.docker.max_concurrent_creations))
        except ValueError:
            pass
    # Resource limits
    if "PYTHON_DOCKER_MCP_MEMORY_LIMIT" in env:
        default_config.docker.memory_limit = env.get("PYTHON_DOCKER_MCP_MEMORY_LIMIT", default_config.docker.memory_limit)
    if "PYTHON_DOCKER_MCP_CPU_LIMIT" in env:
        try:
            default_config.docker.cpu_limit = float(env.get("PYTHON_DOCKER_MCP_CPU_LIMIT", default_config.docker.cpu_limit))
        except ValueError:
            pass

    return default_config
