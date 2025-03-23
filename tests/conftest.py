"""Test configuration and fixtures for python-docker-mcp."""

import asyncio
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import docker
import pytest
import yaml

from python_docker_mcp.config import Configuration, DockerConfig, PackageConfig
from python_docker_mcp.docker_manager import DockerManager


@pytest.fixture
def sample_config():
    """Return a sample configuration object."""
    return Configuration(
        docker=DockerConfig(
            image="python:3.12.2-slim",
            working_dir="/app",
            memory_limit="256m",
            cpu_limit=0.5,
            timeout=10,
            network_disabled=True,
            read_only=True,
        ),
        package=PackageConfig(installer="uv", index_url=None, trusted_hosts=[]),
        allowed_modules=["math", "datetime", "random", "json"],
        blocked_modules=["os", "sys", "subprocess"],
    )


@pytest.fixture
def mock_container():
    """Return a mock Docker container."""
    container = MagicMock()
    container.id = "test-container-id"
    container.status = "exited"
    container.attrs = {"State": {"ExitCode": 0}}
    container.logs.return_value = b"Container logs"
    container.exec_run.return_value = MagicMock(
        exit_code=0,
        output=b'---OUTPUT_START---\n{"output": "Test output", "error": null}\n---OUTPUT_END---',
    )
    return container


@pytest.fixture
def mock_docker_client(mock_container):
    """Return a mock Docker client."""
    client = MagicMock()
    client.containers.run.return_value = mock_container
    client.containers.get.return_value = mock_container
    return client


@pytest.fixture
def docker_manager(sample_config, mock_docker_client):
    """Return a DockerManager instance with a mock Docker client."""
    with patch("docker.from_env", return_value=mock_docker_client):
        manager = DockerManager(config=sample_config)
        yield manager


@pytest.fixture
def temp_config_file():
    """Create a temporary configuration file."""
    with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w+", delete=False) as f:
        config = {
            "docker": {
                "image": "python:3.12.2-slim",
                "working_dir": "/app",
                "memory_limit": "256m",
                "cpu_limit": 0.5,
                "timeout": 10,
                "network_disabled": True,
                "read_only": True,
            },
            "package": {
                "installer": "uv",
                "index_url": None,
                "trusted_hosts": [],
            },
            "allowed_modules": ["math", "datetime", "random", "json"],
            "blocked_modules": ["os", "sys", "subprocess"],
        }
        yaml.dump(config, f)
        path = f.name

    yield path

    # Cleanup
    if os.path.exists(path):
        os.unlink(path)


@pytest.fixture
def mcp_server_mock():
    """Create a mock MCP server."""
    server = MagicMock()
    server.list_tools = AsyncMock()
    server.call_tool = AsyncMock()
    server.list_prompts = AsyncMock()
    server.get_prompt = AsyncMock()
    server.list_resources = AsyncMock()
    server.read_resource = AsyncMock()
    return server


class MockAsyncIterator:
    """Mock async iterator for testing."""

    def __init__(self, items):
        """Initialize with items to yield."""
        self.items = items
        self.index = 0

    def __aiter__(self):
        """Return self as async iterator."""
        return self

    async def __anext__(self):
        """Return next item or raise StopAsyncIteration."""
        if self.index >= len(self.items):
            raise StopAsyncIteration
        item = self.items[self.index]
        self.index += 1
        return item


@pytest.fixture
def mcp_client_mock():
    """Create a mock MCP client."""
    client = MagicMock()
    client.list_tools = AsyncMock()
    client.call_tool = AsyncMock()

    # Configure default responses
    tool1 = MagicMock(
        name="execute-transient",
        description="Execute Python code in a transient container",
    )
    tool2 = MagicMock(
        name="execute-persistent",
        description="Execute Python code in a persistent container",
    )
    tool3 = MagicMock(name="install-package", description="Install a Python package")
    tool4 = MagicMock(name="cleanup-session", description="Clean up a persistent session")

    response = MagicMock()
    response.tools = [tool1, tool2, tool3, tool4]
    client.list_tools.return_value = response

    # Mock call_tool
    call_result = MagicMock()
    call_result.content = [MagicMock(type="text", text="Result of tool execution")]
    client.call_tool.return_value = call_result

    return client
