import asyncio

from . import config, docker_manager, server
from .build_docker_image import build_docker_image


def main():
    """Main entry point for the package."""
    asyncio.run(server.main())


# Expose important items at package level
__all__ = ["main", "server", "config", "docker_manager", "build_docker_image"]
