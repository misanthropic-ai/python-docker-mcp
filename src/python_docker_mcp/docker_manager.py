"""Module for managing Docker containers to execute Python code securely."""

import asyncio
import json
import logging
from typing import Any, Dict, Optional

import docker

from .config import Configuration, load_config

# Set up logging
logger = logging.getLogger(__name__)


class DockerExecutionError(Exception):
    """Exception raised when Docker execution encounters an error."""

    pass


class DockerManager:
    """Manages Docker containers for executing Python code."""

    def __init__(self, config: Optional[Configuration] = None):
        """Initialize the Docker manager with the given configuration."""
        self.config = config or load_config()
        self.client = docker.from_env()
        self.persistent_containers: Dict[str, str] = {}  # session_id -> container_id

    async def execute_transient(self, code: str, state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Execute code in a new container that doesn't persist state."""
        if state is None:
            state = {}

        # Create a wrapper script with proper output capture and state handling
        wrapped_code = f"""
import json, sys, io
from contextlib import redirect_stdout, redirect_stderr

state = {json.dumps(state)}

stdout_capture = io.StringIO()
stderr_capture = io.StringIO()

def ensure_serializable(obj):
    if isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    elif isinstance(obj, (list, tuple)):
        return [ensure_serializable(item) for item in obj]
    elif isinstance(obj, dict):
        return {{k: ensure_serializable(v) for k, v in obj.items()}}
    return str(obj)

try:
    with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
        exec({repr(code)}, state)
    result = ensure_serializable({{
        "__stdout__": stdout_capture.getvalue(),
        "__stderr__": stderr_capture.getvalue(),
        "__error__": None,
        **state
    }})
except Exception as e:
    result = ensure_serializable({{
        "__stdout__": stdout_capture.getvalue(),
        "__stderr__": stderr_capture.getvalue(),
        "__error__": str(e),
        **state
    }})

result.pop('__builtins__', None)
print("---OUTPUT_START---")
print(json.dumps(result))
print("---OUTPUT_END---")
"""

        try:
            # Run container asynchronously with a timeout
            container = self.client.containers.run(
                image=self.config.docker.image,
                command=["python", "-c", wrapped_code],
                mem_limit=self.config.docker.memory_limit,
                cpu_quota=int(self.config.docker.cpu_limit * 100000),
                network_disabled=self.config.docker.network_disabled,
                read_only=True,
                remove=True,
                detach=True,  # Run in background
            )

            # Wait for completion with a 30-second timeout
            exit_code = await asyncio.wait_for(self._wait_for_container(container.id), timeout=30.0)
            if exit_code != 0:
                raise DockerExecutionError(f"Container exited with code {exit_code}")

            # Get and parse the output
            output = container.logs().decode("utf-8")
            start_marker = "---OUTPUT_START---"
            end_marker = "---OUTPUT_END---"

            start_idx = output.find(start_marker)
            end_idx = output.rfind(end_marker)

            if start_idx >= 0 and end_idx >= 0:
                json_str = output[start_idx + len(start_marker) : end_idx].strip()
                return json.loads(json_str)
            return {"__stdout__": output, "__stderr__": "", "__error__": None, **state}

        except asyncio.TimeoutError:
            container.stop()
            raise DockerExecutionError("Execution timed out after 30 seconds")
        except Exception as e:
            raise DockerExecutionError(f"Error executing code in Docker: {str(e)}")

    async def execute_persistent(self, session_id: str, code: str) -> Dict[str, Any]:
        """Execute code in a persistent container that retains state between calls.

        Args:
            session_id: A unique identifier for the session
            code: The Python code to execute

        Returns:
            The result of the execution
        """
        container_id = self.persistent_containers.get(session_id)

        # Create a new container if it doesn't exist
        if not container_id:
            # Store the desired network state to track later
            should_disable_network = self.config.docker.network_disabled

            # Always create with network initially enabled, we can disable it after setup if needed
            container = self.client.containers.run(
                image=self.config.docker.image,
                command=[
                    "python",
                    "-c",
                    "import time; time.sleep(86400)",
                ],  # Run for 24 hours
                working_dir=self.config.docker.working_dir,
                mem_limit=self.config.docker.memory_limit,
                cpu_quota=int(self.config.docker.cpu_limit * 100000),
                network_disabled=False,  # Initialize with network enabled for setup
                read_only=False,  # Need to be writable for persistent sessions
                detach=True,
                labels={
                    "python_docker_mcp.network_disabled": str(should_disable_network),
                    "python_docker_mcp.session_id": session_id,
                },
            )
            container_id = container.id
            self.persistent_containers[session_id] = container_id

            # After container is created and set up, disable network if that was the config setting
            if should_disable_network:
                try:
                    # Refresh the container object to get updated network info
                    container = self.client.containers.get(container_id)

                    # Disconnect from all networks if network should be disabled
                    for network_name in container.attrs.get("NetworkSettings", {}).get("Networks", {}):
                        try:
                            self.client.networks.get(network_name).disconnect(container)
                            logger.info(f"Disabled network {network_name} for container {container_id}")
                        except Exception as e:
                            logger.warning(f"Could not disable network {network_name}: {e}")
                except Exception as e:
                    logger.warning(f"Could not apply network settings to container {container_id}: {e}")

        # Execute the code in the container
        try:
            container = self.client.containers.get(container_id)

            # Instead of using a temporary file + docker cp, create the file directly in the container
            wrapped_code = self._create_execute_persist_script(code)

            # Create script directly in container using a shell command with echo
            # Escape the script for shell safety
            escaped_code = wrapped_code.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$")

            # Write the script directly to /app using echo
            write_cmd = f'echo "{escaped_code}" > /app/execute_script.py'
            exec_result = container.exec_run(
                cmd=["bash", "-c", write_cmd],
                workdir=self.config.docker.working_dir,
            )

            if exec_result.exit_code != 0:
                output = exec_result.output.decode("utf-8").strip()
                raise DockerExecutionError(f"Failed to create script in container: {output}")

            # Make the script executable
            chmod_cmd = "chmod 755 /app/execute_script.py"
            exec_result = container.exec_run(
                cmd=["bash", "-c", chmod_cmd],
                workdir=self.config.docker.working_dir,
            )

            if exec_result.exit_code != 0:
                output = exec_result.output.decode("utf-8").strip()
                raise DockerExecutionError(f"Failed to make script executable: {output}")

            # Execute the script in the container
            exec_result = container.exec_run(
                cmd=["python", "/app/execute_script.py"],
                workdir=self.config.docker.working_dir,
            )

            # Process results
            output = exec_result.output.decode("utf-8").strip()
            if exec_result.exit_code != 0:
                raise DockerExecutionError(f"Execution failed: {output}")

            # Extract the JSON result from the output
            try:
                # Find the JSON output markers
                start_marker = "---OUTPUT_START---"
                end_marker = "---OUTPUT_END---"

                start_idx = output.find(start_marker)
                end_idx = output.rfind(end_marker)

                if start_idx >= 0 and end_idx >= 0:
                    json_str = output[start_idx + len(start_marker) : end_idx].strip()
                    return json.loads(json_str)
                else:
                    return {"output": output, "error": None}
            except json.JSONDecodeError:
                return {"output": output, "error": None}

        except Exception as e:
            if not isinstance(e, DockerExecutionError):
                raise DockerExecutionError(f"Error executing code in persistent container: {str(e)}")
            raise

    async def install_package(self, session_id: Optional[str], package_name: str) -> str:
        """Install a Python package in a container.

        Args:
            session_id: The session ID for persistent containers, or None for transient
            package_name: The name of the package to install

        Returns:
            The output of the installation command
        """
        install_cmd = []
        primary_installer = self.config.package.installer

        # Build the command for the primary installer (uv or pip)
        if primary_installer == "uv":
            # Use uv without --system flag since we're in a virtual env
            install_cmd = ["uv", "pip", "install"]
            if self.config.package.index_url:
                install_cmd.extend(["--index-url", self.config.package.index_url])
            for host in self.config.package.trusted_hosts or []:
                install_cmd.extend(["--trusted-host", host])
            install_cmd.append(package_name)
        else:  # pip
            install_cmd = ["pip", "install"]
            if self.config.package.index_url:
                install_cmd.extend(["--index-url", self.config.package.index_url])
            for host in self.config.package.trusted_hosts or []:
                install_cmd.extend(["--trusted-host", host])
            install_cmd.append(package_name)

        if session_id and session_id in self.persistent_containers:
            # Install in the persistent container
            container_id = self.persistent_containers[session_id]
            container = self.client.containers.get(container_id)

            # Temporarily enable networking for package installation if it was disabled
            # Save the current network settings
            network_was_disabled = False
            if hasattr(container, "attrs") and "NetworkSettings" in container.attrs:
                network_settings = container.attrs["NetworkSettings"]
                network_was_disabled = not bool(network_settings.get("Networks"))

            # If network was disabled, reconnect to the default network
            if network_was_disabled:
                try:
                    self.client.networks.get("bridge").connect(container)
                    logger.info(f"Temporarily enabled network for container {container_id}")
                except Exception as e:
                    logger.warning(f"Could not enable networking for container: {e}")

            # Try the primary installer first
            exec_result = container.exec_run(
                cmd=install_cmd,
                workdir=self.config.docker.working_dir,
                environment={"PATH": "/home/appuser/.venv/bin:$PATH", "VIRTUAL_ENV": "/home/appuser/.venv"},
            )

            # If the primary installer fails and it's uv, fall back to pip
            if exec_result.exit_code != 0 and primary_installer == "uv":
                # Build the fallback pip command
                fallback_cmd = ["pip", "install"]
                if self.config.package.index_url:
                    fallback_cmd.extend(["--index-url", self.config.package.index_url])
                for host in self.config.package.trusted_hosts or []:
                    fallback_cmd.extend(["--trusted-host", host])
                fallback_cmd.append(package_name)

                # Try with pip instead
                exec_result = container.exec_run(
                    cmd=fallback_cmd,
                    workdir=self.config.docker.working_dir,
                    environment={"PATH": "/home/appuser/.venv/bin:$PATH", "VIRTUAL_ENV": "/home/appuser/.venv"},
                )

            # If network was disabled and we enabled it, disconnect it again
            if network_was_disabled:
                try:
                    self.client.networks.get("bridge").disconnect(container)
                    logger.info(f"Restored network settings for container {container_id}")
                except Exception as e:
                    logger.warning(f"Could not restore network settings: {e}")

            return exec_result.output.decode("utf-8")
        else:
            # Create a temporary container just for installation
            try:
                # Use run instead of create+start to wait for completion
                result = self.client.containers.run(
                    image=self.config.docker.image,
                    command=install_cmd,
                    working_dir=self.config.docker.working_dir,
                    network_disabled=False,  # Explicitly enable network for package installation
                    remove=True,
                    detach=False,  # Run in foreground and return output directly
                    environment={"PATH": "/home/appuser/.venv/bin:$PATH", "VIRTUAL_ENV": "/home/appuser/.venv"},
                )

                # Result is already a bytes object, so just decode it
                if isinstance(result, bytes):
                    return result.decode("utf-8")
                else:
                    # If for some reason we get a container back instead of bytes
                    return result.logs().decode("utf-8")

            except Exception as e:
                # If primary installer fails and it's uv, try with pip
                if primary_installer == "uv" and "executable file not found" in str(e):
                    fallback_cmd = ["pip", "install"]
                    if self.config.package.index_url:
                        fallback_cmd.extend(["--index-url", self.config.package.index_url])
                    for host in self.config.package.trusted_hosts or []:
                        fallback_cmd.extend(["--trusted-host", host])
                    fallback_cmd.append(package_name)

                    result = self.client.containers.run(
                        image=self.config.docker.image,
                        command=fallback_cmd,
                        working_dir=self.config.docker.working_dir,
                        network_disabled=False,  # Explicitly enable network for package installation
                        remove=True,
                        detach=False,  # Run in foreground and return output directly
                        environment={"PATH": "/home/appuser/.venv/bin:$PATH", "VIRTUAL_ENV": "/home/appuser/.venv"},
                    )

                    # Result is already a bytes object, so just decode it
                    if isinstance(result, bytes):
                        return result.decode("utf-8")
                    else:
                        # If for some reason we get a container back instead of bytes
                        return result.logs().decode("utf-8")
                raise

    def cleanup_session(self, session_id: str) -> None:
        """Clean up a persistent session by stopping and removing its container."""
        if session_id in self.persistent_containers:
            container_id = self.persistent_containers[session_id]
            try:
                logger.info(f"Cleaning up container {container_id} for session {session_id}")
                container = self.client.containers.get(container_id)

                # Clean up persistence file if it exists
                try:
                    logger.info(f"Removing persistence file in container {container_id}")
                    container.exec_run(cmd=["rm", "-f", "/app/persistent_vars.pkl"], workdir=self.config.docker.working_dir)
                except Exception as e:
                    logger.warning(f"Error removing persistence file: {e}")

                # Check if container is running before stopping
                if container.status == "running":
                    logger.info(f"Stopping container {container_id}")
                    container.stop(timeout=5)

                logger.info(f"Removing container {container_id}")
                container.remove(force=True)  # Force removal in case it's still running
                logger.info(f"Successfully removed container {container_id}")
            except docker.errors.NotFound:
                logger.warning(f"Container {container_id} not found during cleanup")
            except Exception as e:
                logger.error(f"Error cleaning up container {container_id}: {e}")

            # Always remove session from tracking
            del self.persistent_containers[session_id]
            logger.info(f"Removed session {session_id} from tracking")
        else:
            logger.warning(f"Session {session_id} not found during cleanup")

    def cleanup_all_sessions(self) -> None:
        """Clean up all persistent sessions."""
        for session_id in list(self.persistent_containers.keys()):
            self.cleanup_session(session_id)

    async def _wait_for_container(self, container_id: str) -> int:
        """Wait for a container to finish and return its exit code."""
        while True:
            try:
                container = self.client.containers.get(container_id)
                if container.status != "running":
                    return container.attrs["State"]["ExitCode"]
                await asyncio.sleep(0.1)
            except Exception as e:
                logger.error(f"Error waiting for container {container_id}: {e}")
                # If the container is not found, it might have been removed
                # This can happen if the container exits and is set to auto-remove
                return 0  # Assume success if container is gone

    def _create_wrapper_script(self, code: str) -> str:
        """Create a wrapper script for transient execution."""
        return f"""
import json
import sys
import io
import os
import traceback
from contextlib import redirect_stdout, redirect_stderr

print("Docker wrapper script starting...")
print(f"Python version: {{sys.version}}")

# Load state from file
try:
    with open('/app/state.json', 'r') as f:
        state_dict = json.load(f)
    print("Successfully loaded state from /app/state.json")
except Exception as e:
    print(f"Error loading state: {{e}}")
    state_dict = {{}}

# Capture stdout and stderr
stdout_capture = io.StringIO()
stderr_capture = io.StringIO()

# Debug: print environment and current state
print(f"Current directory: {{os.getcwd()}}")
print(f"Directory contents: {{os.listdir('.')}}")
print(f"Environment: {{os.environ}}")

# Make sure state is serializable
def ensure_serializable(obj):
    \"\"\"Ensure all objects in state are JSON serializable.\"\"\"
    if isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    elif isinstance(obj, (list, tuple)):
        return [ensure_serializable(item) for item in obj]
    elif isinstance(obj, dict):
        return {{k: ensure_serializable(v) for k, v in obj.items()}}
    else:
        # For non-serializable objects, convert to string representation
        return str(obj)

# Execute code with state dict as globals
try:
    print("Executing code...")
    with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
        exec_globals = {{'state': state_dict}}
        exec({repr(code)}, exec_globals)

        # Update state with any new or modified variables
        # Only keep serializable values
        for key, value in exec_globals.items():
            if key != 'state' and not key.startswith('__'):
                try:
                    # Test if value is JSON-serializable
                    json.dumps(value)
                    state_dict[key] = value
                except (TypeError, OverflowError):
                    # If not serializable, convert to string
                    state_dict[key] = ensure_serializable(value)

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

# Save updated state
print("Writing output to /app/output.json...")
try:
    # Make one final check to ensure everything is serializable
    serializable_state = ensure_serializable(state_dict)

    with open('/app/output.json', 'w') as f:
        json.dump(serializable_state, f)
    print("Successfully wrote output state")
    # Verify file exists after writing
    print(f"File exists after writing: {{os.path.exists('/app/output.json')}}")
    print(f"File size: {{os.path.getsize('/app/output.json')}}")
except Exception as e:
    error_with_traceback = f"{{e}}\\n{{traceback.format_exc()}}"
    print(f"Error writing output: {{error_with_traceback}}")
    # Try to write at least a minimal output file
    try:
        minimal_state = {{
            '__stdout__': stdout_capture.getvalue(),
            '__stderr__': stderr_capture.getvalue(),
            '__error__': f"Error serializing state: {{error_with_traceback}}"
        }}
        with open('/app/output.json', 'w') as f:
            json.dump(minimal_state, f)
        print("Wrote minimal output state with error message")
    except Exception as nested_e:
        print(f"Failed to write even minimal state: {{nested_e}}")

# Print output summary
print("=== EXECUTION RESULTS ===")
if state_dict.get('__stdout__'):
    print("=== STDOUT ===")
    print(state_dict['__stdout__'])
if state_dict.get('__stderr__'):
    print("=== STDERR ===")
    print(state_dict['__stderr__'])
if state_dict.get('__error__'):
    print("=== ERROR ===")
    print(state_dict['__error__'])

print("Docker wrapper script completed.")
"""

    def _create_execute_persist_script(self, code: str) -> str:
        """Create a script for persistent execution."""
        return f"""
import json
import sys
import io
import os
import traceback
import pickle
from contextlib import redirect_stdout, redirect_stderr

print("Docker persistent execution script starting...")
print(f"Python version: {{sys.version}}")
print(f"Current directory: {{os.getcwd()}}")
print(f"Directory contents: {{os.listdir('.')}}")

# Capture stdout and stderr
stdout_capture = io.StringIO()
stderr_capture = io.StringIO()

# Path to store persisted variables
PERSISTENCE_FILE = '/app/persistent_vars.pkl'

# Load previously saved variables if they exist
if os.path.exists(PERSISTENCE_FILE):
    try:
        with open(PERSISTENCE_FILE, 'rb') as f:
            loaded_vars = pickle.load(f)
            # Add loaded variables to globals
            for var_name, var_value in loaded_vars.items():
                globals()[var_name] = var_value
        print(f"Loaded persistent variables from {{PERSISTENCE_FILE}}")
    except Exception as e:
        print(f"Error loading persistent variables: {{e}}")

# Make sure state is serializable
def ensure_serializable(obj):
    \"\"\"Ensure all objects in state are JSON serializable.\"\"\"
    if isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    elif isinstance(obj, (list, tuple)):
        return [ensure_serializable(item) for item in obj]
    elif isinstance(obj, dict):
        return {{k: ensure_serializable(v) for k, v in obj.items()}}
    else:
        # For non-serializable objects, convert to string representation
        return str(obj)

# Execute code in the global namespace to preserve variables between executions
try:
    print("Executing code...")
    with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
        # Execute directly in the global namespace so variables persist
        exec({repr(code)}, globals())

        # Save variables for persistence - filter out modules, functions, and special variables
        vars_to_save = {{}}
        for key, value in list(globals().items()):
            if (not key.startswith('__') and
                not callable(value) and
                not key in ('ensure_serializable', 'stdout_capture', 'stderr_capture',
                           'json', 'sys', 'io', 'os', 'traceback', 'redirect_stdout',
                           'redirect_stderr', 'pickle', 'PERSISTENCE_FILE', 'vars_to_save')):
                try:
                    # Try pickling to verify if it can be persisted
                    pickle.dumps(value)
                    vars_to_save[key] = value
                except:
                    # Skip values that can't be pickled
                    pass

        # Save variables to file
        try:
            with open(PERSISTENCE_FILE, 'wb') as f:
                pickle.dump(vars_to_save, f)
            print(f"Saved {{len(vars_to_save)}} variables to {{PERSISTENCE_FILE}}")
        except Exception as e:
            print(f"Error saving persistent variables: {{e}}")

        # Prepare a state dictionary of all variables in the global namespace for JSON response
        state_dict = {{}}
        for key, value in vars_to_save.items():
            try:
                # Try serializing to check if JSON-serializable
                json.dumps(value)
                state_dict[key] = value
            except (TypeError, OverflowError):
                # If not serializable, use string representation
                state_dict[key] = ensure_serializable(value)

        result = {{
            "output": stdout_capture.getvalue(),
            "error": None,
            "state": state_dict
        }}
except Exception as e:
    error_with_traceback = f"{{e}}\\n{{traceback.format_exc()}}"
    result = {{
        "output": stdout_capture.getvalue(),
        "error": error_with_traceback,
        "state": {{}}
    }}
    print(f"Error during execution: {{error_with_traceback}}")

# Output the result as JSON
print("---OUTPUT_START---")
print(json.dumps(result))
print("---OUTPUT_END---")

print("Docker persistent execution script completed.")
"""
