#!/usr/bin/env python3
"""
MCP Inspector launcher for python-docker-mcp.

This script helps to launch the MCP Inspector with the appropriate configuration
to debug and test the python-docker-mcp server.

Requirements:
- Node.js and npm must be installed
- The python-docker-mcp project must be installed or in development mode

Usage:
    python test_mcp_inspector.py [--dev]
    
    --dev  : Run in development mode (use the current directory)
    
The script will start the MCP Inspector connected to the python-docker-mcp server.
"""

import argparse
import os
import subprocess
import sys
import textwrap
from pathlib import Path


def check_requirements():
    """Check if Node.js and npm are installed."""
    try:
        subprocess.run(["node", "--version"], capture_output=True, check=True)
        subprocess.run(["npm", "--version"], capture_output=True, check=True)
        return True
    except (subprocess.SubprocessError, FileNotFoundError):
        print("ERROR: Node.js and npm are required to run MCP Inspector.")
        print("Please install them from https://nodejs.org/")
        return False


def launch_inspector(dev_mode=False):
    """Launch the MCP Inspector with the python-docker-mcp server."""
    # Get the current project path
    project_path = Path(os.path.abspath("."))
    
    # Prepare the command
    if dev_mode:
        cmd = [
            "npx", "@modelcontextprotocol/inspector",
            "uv", "--directory", str(project_path),
            "run", "python-docker-mcp"
        ]
    else:
        cmd = [
            "npx", "@modelcontextprotocol/inspector",
            "uvx", "python-docker-mcp"
        ]
    
    # Print information
    print("=== Launching MCP Inspector ===")
    print(f"Mode: {'Development' if dev_mode else 'Published package'}")
    print(f"Project path: {project_path}")
    print(f"Command: {' '.join(cmd)}")
    print("\nStarting inspector... (press Ctrl+C to exit)")
    print("If successful, a web browser should open to the MCP Inspector UI.")
    
    # Launch the inspector
    try:
        subprocess.run(cmd, check=True)
    except KeyboardInterrupt:
        print("\nMCP Inspector terminated by user.")
    except subprocess.SubprocessError as e:
        print(f"\nERROR: Failed to launch MCP Inspector: {e}")
        print_troubleshooting()


def print_troubleshooting():
    """Print troubleshooting information."""
    print(textwrap.dedent("""
    === Troubleshooting ===
    
    1. Make sure Node.js and npm are installed and in your PATH
       - Install from https://nodejs.org/
    
    2. Make sure python-docker-mcp is installed or in development mode
       - Install with: uv install -e .
    
    3. Check Docker is running
       - The python-docker-mcp server requires Docker
    
    4. Try running the server directly
       - Run: python -m python_docker_mcp
       - If it shows errors, address those first
    
    5. Try installing the MCP Inspector globally
       - Run: npm install -g @modelcontextprotocol/inspector
       - Then try: mcp-inspector uvx python-docker-mcp
    """))


def main():
    """Parse arguments and launch the inspector."""
    parser = argparse.ArgumentParser(description="Launch MCP Inspector for python-docker-mcp")
    parser.add_argument("--dev", action="store_true", help="Run in development mode")
    args = parser.parse_args()
    
    if check_requirements():
        launch_inspector(args.dev)


if __name__ == "__main__":
    main() 