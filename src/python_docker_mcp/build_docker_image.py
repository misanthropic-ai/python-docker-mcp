#!/usr/bin/env python3
"""Utility script to build a custom Docker image for python-docker-mcp.

This can be used to create a custom image with pre-installed packages.
"""

import argparse
import os
import shutil
import subprocess
import tempfile
from typing import Dict, Optional

import pkg_resources


def get_dockerfile_path() -> str:
    """Get the path to the Dockerfile within the package."""
    try:
        # Try to get the Dockerfile from the installed package
        return pkg_resources.resource_filename("python_docker_mcp", "Dockerfile")
    except (pkg_resources.DistributionNotFound, FileNotFoundError):
        # Fall back to local path for development
        current_dir = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(current_dir, "Dockerfile")


def build_docker_image(
    tag: str = "python-docker-mcp:latest", dockerfile: Optional[str] = None, build_args: Optional[Dict[str, str]] = None, debug: bool = False
) -> bool:
    """Build a Docker image for the Python execution environment.

    Args:
        tag: Tag for the Docker image
        dockerfile: Path to a custom Dockerfile (defaults to the one included with the package)
        build_args: Dictionary of build arguments to pass to docker build
        debug: Whether to enable verbose debugging output

    Returns:
        True if the build was successful, False otherwise
    """
    if dockerfile is None:
        dockerfile = get_dockerfile_path()

    if not os.path.exists(dockerfile):
        print(f"Error: Dockerfile not found at {dockerfile}")
        return False

    # Print Dockerfile contents for debugging
    if debug:
        print("=== Dockerfile contents ===")
        with open(dockerfile, "r") as f:
            print(f.read())
        print("==========================")

    # Create a build context directory
    with tempfile.TemporaryDirectory() as temp_dir:
        # Copy the Dockerfile to the build context
        dockerfile_dest = os.path.join(temp_dir, "Dockerfile")
        shutil.copy2(dockerfile, dockerfile_dest)

        # Build the command
        cmd = ["docker", "build", "-t", tag, "."]

        # Add build arguments if specified
        if build_args:
            for arg_name, arg_value in build_args.items():
                cmd.extend(["--build-arg", f"{arg_name}={arg_value}"])

        # Run the build command
        try:
            print(f"Building Docker image {tag}...")
            print(f"Command: {' '.join(cmd)}")
            print(f"Build context: {temp_dir}")

            result = subprocess.run(
                cmd,
                cwd=temp_dir,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
            )
            if debug or result.stdout:
                print(result.stdout)
            print(f"Successfully built Docker image: {tag}")
            return True
        except subprocess.CalledProcessError as e:
            print(f"Error building Docker image: {e}")
            print("=== Command output (stderr) ===")
            print(e.stderr)
            print("===============================")
            return False


def main() -> int:
    """Command-line entry point for building Docker images."""
    parser = argparse.ArgumentParser(description="Build a Docker image for python-docker-mcp")
    parser.add_argument(
        "--tag",
        default="python-docker-mcp:latest",
        help="Tag for the Docker image (default: python-docker-mcp:latest)",
    )
    parser.add_argument("--dockerfile", help="Path to a custom Dockerfile")
    parser.add_argument(
        "--build-arg",
        action="append",
        dest="build_args",
        help="Build arguments to pass to docker build (format: NAME=VALUE)",
    )
    parser.add_argument("--debug", action="store_true", help="Enable verbose debugging output")

    args = parser.parse_args()

    # Process build arguments
    build_args_dict = {}
    if args.build_args:
        for arg in args.build_args:
            parts = arg.split("=", 1)
            if len(parts) == 2:
                build_args_dict[parts[0]] = parts[1]
            else:
                print(f"Warning: Ignoring malformed build argument: {arg}")

    # Build the Docker image
    success = build_docker_image(args.tag, args.dockerfile, build_args_dict, args.debug)

    # Exit with appropriate status code
    return 0 if success else 1


if __name__ == "__main__":
    exit(main())
