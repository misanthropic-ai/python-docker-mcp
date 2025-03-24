"""Python Docker MCP package for running Python code in isolated Docker containers.

This package provides a server that accepts Python code execution requests and runs
them in isolated Docker containers for security.
"""

import asyncio
import logging
import subprocess
from typing import Optional

from . import config, docker_manager, server
from .build_docker_image import build_docker_image

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("python-docker-mcp")


def check_docker_image_exists(image_name: str) -> bool:
    """Check if a Docker image exists locally."""
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", image_name],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return result.returncode == 0
    except Exception as e:
        logger.error(f"Error checking Docker image: {e}")
        return False


def ensure_docker_image(image_name: Optional[str] = None) -> None:
    """Ensure the Docker image exists, building it if necessary."""
    if image_name is None:
        # Load configuration to get the default image name
        config_obj = config.load_config()
        image_name = config_obj.docker.image

    # Check if the image exists
    if not check_docker_image_exists(image_name):
        logger.info(f"Docker image {image_name} not found. Building it now...")

        # First attempt to build without debug output
        build_success = build_docker_image(tag=image_name)

        # If that fails, try once more with debug output
        if not build_success:
            logger.warning("First build attempt failed. Retrying with debug output...")
            build_success = build_docker_image(tag=image_name, debug=True)

        if build_success:
            logger.info(f"Successfully built Docker image: {image_name}")
        else:
            logger.warning(f"Failed to build Docker image: {image_name}. Package installation may not work correctly.")
            logger.warning("To manually build the image, run: python -m python_docker_mcp.build_docker_image --debug")


def main() -> None:
    """Main entry point for the package."""
    try:
        # Ensure the Docker image exists before starting the server
        ensure_docker_image()

        # Run the server
        asyncio.run(server.main())
    except Exception as e:
        logger.error(f"Error in main: {e}", exc_info=True)
        raise


# Expose important items at package level
__all__ = ["main", "server", "config", "docker_manager", "build_docker_image"]
