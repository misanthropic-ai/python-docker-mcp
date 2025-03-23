#!/usr/bin/env python3
"""
Direct Docker testing script for python-docker-mcp.

This script tests the Docker functionality directly without going through
the MCP protocol layer, to help debug any Docker-specific issues.
"""

import asyncio
import json
import os
import tempfile
import time
from typing import Dict, Any, Optional

import docker
from docker.errors import DockerException

# Configuration similar to what's used in the MCP server
DOCKER_CONFIG = {
    "image": "python:3.12.2-slim",
    "working_dir": "/app",
    "memory_limit": "256m",
    "cpu_limit": 0.5,  # This gets converted to 50000 in cpu_quota
    "timeout": 30,  # seconds
    "network_disabled": True,
    "read_only": True,
}


def create_wrapper_script(code: str) -> str:
    """Create a wrapper script for execution in Docker."""
    return f"""
import json
import sys
import io
from contextlib import redirect_stdout, redirect_stderr

# Create empty state dict
state_dict = {{}}

# Capture stdout and stderr
stdout_capture = io.StringIO()
stderr_capture = io.StringIO()

# Execute code
try:
    with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
        exec_globals = {{'state': state_dict}}
        exec({repr(code)}, exec_globals)

        # Update state with any new or modified variables
        for key, value in exec_globals.items():
            if key != 'state' and not key.startswith('__'):
                state_dict[key] = value

        # Add stdout and stderr to state
        state_dict['__stdout__'] = stdout_capture.getvalue()
        state_dict['__stderr__'] = stderr_capture.getvalue()
        state_dict['__error__'] = None

except Exception as e:
    state_dict['__stdout__'] = stdout_capture.getvalue()
    state_dict['__stderr__'] = stderr_capture.getvalue()
    state_dict['__error__'] = str(e)

# Save state
with open('/app/output.json', 'w') as f:
    json.dump(state_dict, f)

# Also print output for visibility
print("=== STDOUT ===")
print(state_dict['__stdout__'])
if state_dict['__stderr__']:
    print("=== STDERR ===")
    print(state_dict['__stderr__'])
if state_dict['__error__']:
    print("=== ERROR ===")
    print(state_dict['__error__'])
"""


async def test_docker_execution():
    """Test basic Docker execution."""
    print("=== Testing Direct Docker Execution ===")
    
    # Connect to Docker
    print("Connecting to Docker...")
    try:
        client = docker.from_env()
        print(f"Docker version: {client.version()}")
    except DockerException as e:
        print(f"Failed to connect to Docker: {e}")
        print("Make sure Docker is running and you have permission to access it.")
        return
    
    # Test pulling the image if it doesn't exist
    print(f"\nPulling image: {DOCKER_CONFIG['image']}")
    try:
        client.images.pull(DOCKER_CONFIG['image'])
        print("Image pulled successfully")
    except DockerException as e:
        print(f"Failed to pull image: {e}")
        return
    
    # Create test code
    test_code = """
print("Hello from Docker container!")
x = 42
print(f"The answer is {x}")
result = x * 2
print(f"Twice the answer is {result}")
"""
    
    # Create temporary directory for mounting
    with tempfile.TemporaryDirectory() as temp_dir:
        print(f"\nUsing temporary directory: {temp_dir}")
        
        # Create Python script file with the code
        script_path = os.path.join(temp_dir, "script.py")
        output_path = os.path.join(temp_dir, "output.json")
        
        # Create the wrapper script
        with open(script_path, "w") as f:
            f.write(create_wrapper_script(test_code))
        
        print("Created wrapper script")
        
        # Start container
        print("\nStarting Docker container...")
        try:
            container = client.containers.run(
                image=DOCKER_CONFIG["image"],
                command=["python", "/app/script.py"],
                volumes={temp_dir: {"bind": "/app", "mode": "rw"}},
                working_dir=DOCKER_CONFIG["working_dir"],
                mem_limit=DOCKER_CONFIG["memory_limit"],
                cpu_quota=int(DOCKER_CONFIG["cpu_limit"] * 100000),
                network_disabled=DOCKER_CONFIG["network_disabled"],
                read_only=DOCKER_CONFIG["read_only"],
                remove=True,
                detach=True,
            )
            
            print(f"Container started with ID: {container.id}")
            
            # Wait for the container to finish
            print("\nWaiting for container to finish...")
            start_time = time.time()
            status = container.status
            
            while status == "running":
                if time.time() - start_time > DOCKER_CONFIG["timeout"]:
                    print(f"Timeout after {DOCKER_CONFIG['timeout']} seconds. Stopping container.")
                    container.stop(timeout=1)
                    break
                
                # Wait a bit before checking again
                await asyncio.sleep(0.5)
                
                # Refresh status
                container.reload()
                status = container.status
            
            # Print container logs
            print("\nContainer logs:")
            print(container.logs().decode())
            
            # Check exit code
            if hasattr(container, "attrs") and "State" in container.attrs:
                exit_code = container.attrs["State"].get("ExitCode")
                print(f"Container exited with code: {exit_code}")
            
            # Check output.json
            print("\nChecking output file...")
            if os.path.exists(output_path):
                with open(output_path, "r") as f:
                    output = json.load(f)
                
                print("Output state:")
                print(json.dumps(output, indent=2))
            else:
                print("No output file found!")
            
        except DockerException as e:
            print(f"Docker error: {e}")
        except Exception as e:
            print(f"Error: {e}")


async def test_persistent_container():
    """Test a persistent Docker container."""
    print("\n=== Testing Persistent Docker Container ===")
    
    # Connect to Docker
    try:
        client = docker.from_env()
    except DockerException as e:
        print(f"Failed to connect to Docker: {e}")
        return
    
    # Start a long-running container
    print("Starting persistent container...")
    try:
        container = client.containers.run(
            image=DOCKER_CONFIG["image"],
            command=["python", "-c", "import time; print('Container ready'); time.sleep(60)"],
            working_dir=DOCKER_CONFIG["working_dir"],
            mem_limit=DOCKER_CONFIG["memory_limit"],
            cpu_quota=int(DOCKER_CONFIG["cpu_limit"] * 100000),
            network_disabled=DOCKER_CONFIG["network_disabled"],
            read_only=False,  # Need to be writable for persistent container
            detach=True,
        )
        
        print(f"Container started with ID: {container.id}")
        
        # Wait a moment for container to initialize
        await asyncio.sleep(2)
        
        # Execute a command in the container
        print("\nExecuting command in the container...")
        exec_result = container.exec_run(
            cmd=["python", "-c", "print('Hello from exec!'); print('Current directory:', __import__('os').getcwd())"],
            workdir=DOCKER_CONFIG["working_dir"],
        )
        
        print(f"Command exit code: {exec_result.exit_code}")
        print(f"Command output: {exec_result.output.decode()}")
        
        # Another command to test state persistence
        print("\nExecuting another command to test file creation...")
        exec_result2 = container.exec_run(
            cmd=["bash", "-c", "echo 'test data' > /app/test.txt && cat /app/test.txt"],
            workdir=DOCKER_CONFIG["working_dir"],
        )
        
        print(f"Command exit code: {exec_result2.exit_code}")
        print(f"Command output: {exec_result2.output.decode()}")
        
    except DockerException as e:
        print(f"Docker error: {e}")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        # Clean up
        print("\nCleaning up container...")
        try:
            container.stop()
            container.remove()
            print("Container stopped and removed")
        except Exception as e:
            print(f"Cleanup error: {e}")


async def main():
    """Run all the Docker tests."""
    print("==== Direct Docker Testing ====")
    
    try:
        await test_docker_execution()
        await test_persistent_container()
    except Exception as e:
        print(f"Error during tests: {e}")
    
    print("\n==== Docker tests completed ====")


if __name__ == "__main__":
    asyncio.run(main()) 