from . import server
from . import config
from . import docker_manager
from .build_docker_image import build_docker_image
import asyncio

def main():
    """Main entry point for the package."""
    asyncio.run(server.main())

# Expose important items at package level
__all__ = ['main', 'server', 'config', 'docker_manager', 'build_docker_image']