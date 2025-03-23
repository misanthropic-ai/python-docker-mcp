# /// script
# dependencies = [
#   "docker",
# ]
# ///

"""
Docker test script for python-docker-mcp.

This script tests the Docker functionality directly without going through
the MCP protocol layer, to help debug any Docker-specific issues.
"""

import asyncio
import json
import os
import tempfile
import time

import docker
from docker.errors import DockerException

# Configuration similar to what's used in the MCP server
DOCKER_CONFIG = {
    "image": "python:3.12.2-slim",
    "working_dir": "/app",
    "memory_limit": "256m",
    "cpu_limit": 0.5,  # This gets converted to 50000 in cpu_quota
    "timeout": 30,  # seconds
    "network_disabled": False,  # Set to False for debugging
    "read_only": False,  # Set to False to allow writing
}


def create_wrapper_script(code):
    """Create a wrapper script for execution in Docker."""
    return f"""
#!/usr/bin/env python3
import json
import sys
import io
import os
import traceback
from contextlib import redirect_stdout, redirect_stderr

print("Starting execution wrapper...")
print(f"Python version: {{sys.version}}")

# Create empty state dict
state_dict = {{}}

# Capture stdout and stderr
stdout_capture = io.StringIO()
stderr_capture = io.StringIO()

# Debug: print environment and current state
print(f"Environment: {{os.environ}}")
print(f"Current directory: {{os.getcwd()}}")
print(f"Directory contents: {{os.listdir('.')}}")
print(f"User: {{os.getuid() if hasattr(os, 'getuid') else 'N/A'}}")

# Execute code
try:
    print("Executing code...")
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
    error_with_traceback = f"{{e}}\\n{{traceback.format_exc()}}"
    state_dict['__stdout__'] = stdout_capture.getvalue()
    state_dict['__stderr__'] = stderr_capture.getvalue()
    state_dict['__error__'] = error_with_traceback
    print(f"Error during execution: {{error_with_traceback}}")

# Save state
output_path = '/app/output.json'
print(f"Writing output to: {{output_path}}")
try:
    with open(output_path, 'w') as f:
        json.dump(state_dict, f)
    print(f"Successfully wrote to {{output_path}}")
    # Verify file exists after writing
    print(f"File exists after writing: {{os.path.exists(output_path)}}")
    print(f"File size: {{os.path.getsize(output_path)}}")
    print(f"Directory contents after writing: {{os.listdir('.')}}")
except Exception as e:
    error_with_traceback = f"{{e}}\\n{{traceback.format_exc()}}"
    print(f"Error writing output: {{error_with_traceback}}")
    # Try writing to a different location
    try:
        alt_path = './output.json'
        print(f"Trying alternative path: {{alt_path}}")
        with open(alt_path, 'w') as f:
            json.dump(state_dict, f)
        print(f"Successfully wrote to {{alt_path}}")
    except Exception as alt_e:
        print(f"Alternative path also failed: {{alt_e}}")

# Also print output for visibility
print("=== STDOUT ===")
print(state_dict['__stdout__'])
if state_dict['__stderr__']:
    print("=== STDERR ===")
    print(state_dict['__stderr__'])
if state_dict['__error__']:
    print("=== ERROR ===")
    print(state_dict['__error__'])

print("Wrapper script completed.")
"""


async def test_docker_execution():
    """Test basic Docker execution."""
    print("=== Testing Docker Execution ===")
    
    # Connect to Docker
    print("Connecting to Docker...")
    try:
        client = docker.from_env()
        print(f"Docker version: {client.version()}")
    except DockerException as e:
        print(f"ERROR: Failed to connect to Docker: {e}")
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
        print(f"Absolute path: {os.path.abspath(temp_dir)}")
        
        # Create Python script file with the code
        script_path = os.path.join(temp_dir, "script.py")
        output_path = os.path.join(temp_dir, "output.json")
        
        # Create the wrapper script
        with open(script_path, "w") as f:
            f.write(create_wrapper_script(test_code))
        os.chmod(script_path, 0o755)  # Make script executable
        
        print("Created wrapper script")
        
        # Ensure the temp directory has proper permissions
        try:
            os.chmod(temp_dir, 0o777)  # Give full permissions to the temp directory
            print(f"Set permissions on {temp_dir} to 0o777")
        except Exception as e:
            print(f"Warning: Failed to set permissions: {e}")
        
        # Start container
        print("\nStarting Docker container...")
        container = None
        try:
            container = client.containers.run(
                image=DOCKER_CONFIG["image"],
                command=["python", "/app/script.py"],
                volumes={os.path.abspath(temp_dir): {"bind": "/app", "mode": "rw"}},
                working_dir=DOCKER_CONFIG["working_dir"],
                mem_limit=DOCKER_CONFIG["memory_limit"],
                cpu_quota=int(DOCKER_CONFIG["cpu_limit"] * 100000),
                network_disabled=DOCKER_CONFIG["network_disabled"],
                read_only=DOCKER_CONFIG["read_only"],
                detach=True,
            )
            
            print(f"Container started with ID: {container.id}")
            
            # Wait for the container to finish
            print("\nWaiting for container to finish...")
            start_time = time.time()
            
            while True:
                container.reload()  # Refresh container info
                
                if container.status != "running":
                    print(f"Container status changed to: {container.status}")
                    break
                
                if time.time() - start_time > DOCKER_CONFIG["timeout"]:
                    print(f"Timeout after {DOCKER_CONFIG['timeout']} seconds. Stopping container.")
                    try:
                        container.stop(timeout=2)
                    except Exception as e:
                        print(f"Error stopping container: {e}")
                    break
                
                # Wait a bit before checking again
                await asyncio.sleep(1)
            
            # Print container logs
            print("\nContainer logs:")
            logs = container.logs().decode()
            print(logs)
            
            # Get exit code
            container.reload()  # Refresh container info again
            exit_code = container.attrs["State"]["ExitCode"]
            print(f"Container exited with code: {exit_code}")
            
            # List directory contents to debug
            print(f"\nTemporary directory contents: {os.listdir(temp_dir)}")
            
            # Check output.json
            print("\nChecking output file...")
            if os.path.exists(output_path):
                print(f"Output file found at: {output_path}")
                print(f"File size: {os.path.getsize(output_path)}")
                try:
                    with open(output_path, "r") as f:
                        output = json.load(f)
                    
                    print("Output state:")
                    print(json.dumps(output, indent=2))
                except json.JSONDecodeError as e:
                    print(f"Error decoding JSON: {e}")
                    with open(output_path, "r") as f:
                        print("Raw file content:")
                        print(f.read())
            else:
                print(f"No output file found at: {output_path}")
            
        except DockerException as e:
            print(f"Docker error: {e}")
        except Exception as e:
            print(f"Error: {e}")
        finally:
            # Clean up container
            if container:
                print("\nCleaning up container...")
                try:
                    container.stop(timeout=2)
                except:
                    pass  # Container might already be stopped
                
                try:
                    container.remove()
                    print("Container removed successfully")
                except Exception as e:
                    print(f"Error removing container: {e}")


async def main():
    """Run the Docker test."""
    print("==== Docker Functionality Test ====")
    
    try:
        await test_docker_execution()
    except Exception as e:
        print(f"Error during test: {e}")
    
    print("\n==== Docker test completed ====")


if __name__ == "__main__":
    asyncio.run(main()) 