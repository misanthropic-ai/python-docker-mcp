"""Module for managing Docker containers to execute Python code securely."""

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional, Set

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

        # Container pooling functionality
        self.container_pool: List[str] = []  # List of available container IDs
        self.in_use_containers: Set[str] = set()  # Set of container IDs currently in use
        self.pool_lock = asyncio.Lock()  # Lock for thread safety when accessing the pool
        self.container_creation_timestamps: Dict[str, float] = {}  # container_id -> creation_timestamp

        # Pool configuration
        try:
            self.pool_size = self.config.docker.pool_size
            self.pool_max_age = self.config.docker.pool_max_age
            self.max_concurrent_creations = self.config.docker.max_concurrent_creations
            self.pool_enabled = self.config.docker.pool_enabled

            # Disable pooling for now until we can verify basic functionality
            try:
                logger.info("Container pooling configuration loaded")
                logger.info(f"Pool size: {self.pool_size}, Max age: {self.pool_max_age}s, " f"Max concurrent creations: {self.max_concurrent_creations}")
            except Exception as e:
                logger.error(f"Error configuring container pooling: {e}")
        except AttributeError:
            # If we hit any AttributeError, disable pooling
            logger.warning("Error accessing pooling configuration attributes, disabling container pooling")
            self.pool_size = 0
            self.pool_max_age = 300
            self.max_concurrent_creations = 5
            self.pool_enabled = False

        # Container acquisition semaphore to limit concurrent container creations
        self.container_semaphore = asyncio.Semaphore(self.max_concurrent_creations)

    async def initialize_pool(self) -> None:
        """Initialize the container pool with preloaded containers."""
        if not self.pool_enabled:
            logger.info("Container pooling is disabled, skipping pool initialization")
            return

        logger.info(f"Initializing container pool with size {self.pool_size}")

        async with self.pool_lock:
            tasks = []
            for _ in range(min(self.pool_size, self.max_concurrent_creations)):
                tasks.append(self._create_pooled_container())

            if tasks:
                results: list[str | BaseException] = await asyncio.gather(*tasks, return_exceptions=True)
                # Filter out exceptions and add only successful container creations to the pool
                for result in results:
                    if isinstance(result, str) and result:  # Ensure result is a non-empty string
                        self.container_pool.append(result)
                        self.container_creation_timestamps[result] = time.time()

            logger.info(f"Container pool initialized with {len(self.container_pool)} containers")

    async def _create_pooled_container(self) -> str:
        """Create a new container for the pool."""
        try:
            async with self.container_semaphore:
                # Create a container in a paused state that we can use later
                container = self.client.containers.run(
                    image=self.config.docker.image,
                    command=["sleep", "3600"],  # Sleep for 1 hour
                    detach=True,
                    mem_limit=self.config.docker.memory_limit,
                    cpu_quota=int(self.config.docker.cpu_limit * 100000),
                    network_disabled=self.config.docker.network_disabled,
                    read_only=False,  # Need to be writable for Python code execution
                    labels={"python_docker_mcp.pooled": "true", "python_docker_mcp.created": str(time.time())},
                )
                logger.info(f"Created pooled container {container.id[:12]}")
                return container.id
        except Exception as e:
            logger.error(f"Error creating pooled container: {str(e)}")
            raise DockerExecutionError(f"Failed to create container for pool: {str(e)}")

    async def _get_container_from_pool(self) -> str:
        """Get a container from the pool or create a new one if needed."""
        container_id = None

        async with self.pool_lock:
            # Clean up old containers in the pool
            current_time = time.time()
            removed_count = 0

            for container_id in list(self.container_pool):
                if container_id in self.container_creation_timestamps:
                    age = current_time - self.container_creation_timestamps[container_id]
                    if age > self.pool_max_age:
                        self.container_pool.remove(container_id)
                        try:
                            container = self.client.containers.get(container_id)
                            container.remove(force=True)
                            del self.container_creation_timestamps[container_id]
                            removed_count += 1
                        except Exception as e:
                            logger.warning(f"Error removing old container {container_id[:12]}: {str(e)}")

            if removed_count > 0:
                logger.info(f"Removed {removed_count} aged-out containers from pool")

            # Get a container from the pool
            if self.container_pool:
                container_id = self.container_pool.pop()
                self.in_use_containers.add(container_id)

        # If no container available in pool, create a new one
        if not container_id:
            logger.info("No containers available in pool, creating new one")
            container_id = await self._create_pooled_container()
            async with self.pool_lock:
                self.in_use_containers.add(container_id)
                self.container_creation_timestamps[container_id] = time.time()

        return container_id

    async def _return_container_to_pool(self, container_id: str) -> None:
        """Return a container to the pool for reuse or clean it up if the pool is full."""
        async with self.pool_lock:
            # Remove from in-use set
            if container_id in self.in_use_containers:
                self.in_use_containers.remove(container_id)

            try:
                # Check container still exists and is healthy
                container = self.client.containers.get(container_id)

                # Reset container state to ensure isolation between executions
                try:
                    # Kill any running processes
                    container.exec_run("pkill -9 python", user="root")
                    # Clean up /app directory
                    container.exec_run("rm -rf /app/*", user="root")
                except Exception as e:
                    logger.warning(f"Error resetting container state: {str(e)}")

                # If pool isn't full, add it back to the pool
                if len(self.container_pool) < self.pool_size:
                    self.container_pool.append(container_id)
                    # Reset the creation timestamp to extend lifetime
                    self.container_creation_timestamps[container_id] = time.time()
                    logger.debug(f"Returned container {container_id[:12]} to pool")
                else:
                    # Pool is full, remove this container
                    container.remove(force=True)
                    if container_id in self.container_creation_timestamps:
                        del self.container_creation_timestamps[container_id]
                    logger.debug(f"Pool is full, removed container {container_id[:12]}")
            except Exception as e:
                logger.warning(f"Error returning container {container_id[:12]} to pool: {str(e)}")
                # Try to force remove if there's an issue
                try:
                    self.client.containers.get(container_id).remove(force=True)
                except Exception:
                    pass

                if container_id in self.container_creation_timestamps:
                    del self.container_creation_timestamps[container_id]

    async def execute_transient(self, code: str, state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Execute code in a new container that doesn't persist state."""
        if state is None:
            state = {}

        # Check if pooling is enabled and use the pooled version if it is
        if self.pool_enabled:
            try:
                return await self._execute_transient_pooled(code, state)
            except Exception as e:
                logger.warning(f"Pooled execution failed: {str(e)}, falling back to standard execution")
                # Fall back to standard execution if pooled execution fails

        # Standard execution (non-pooled)
        return await self._execute_transient_standard(code, state)

    async def _execute_transient_pooled(self, code: str, state: Dict[str, Any]) -> Dict[str, Any]:
        """Execute code using a container from the pool."""
        container_id = None
        try:
            # Get a container from the pool
            container_id = await self._get_container_from_pool()
            container = self.client.containers.get(container_id)

            # Create the Python script with the code and state
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

            # Write the script to the container
            escaped_code = wrapped_code.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$")
            write_cmd = f'echo "{escaped_code}" > /app/execute_script.py'

            exec_result = container.exec_run(cmd=["bash", "-c", write_cmd], workdir=self.config.docker.working_dir)

            if exec_result.exit_code != 0:
                raise DockerExecutionError(f"Failed to create script in container: {exec_result.output.decode('utf-8')}")

            # Execute the script
            exec_result = container.exec_run(cmd=["python", "/app/execute_script.py"], workdir=self.config.docker.working_dir)

            # Parse the output
            output = exec_result.output.decode("utf-8")
            start_marker = "---OUTPUT_START---"
            end_marker = "---OUTPUT_END---"

            start_idx = output.find(start_marker)
            end_idx = output.rfind(end_marker)

            if start_idx >= 0 and end_idx >= 0:
                json_str = output[start_idx + len(start_marker) : end_idx].strip()
                return json.loads(json_str)

            # If output parsing fails, return a simple result
            return {"__stdout__": output, "__stderr__": "", "__error__": None, **state}

        except Exception as e:
            raise DockerExecutionError(f"Error executing code in pooled container: {str(e)}")

        finally:
            # Return the container to the pool if we got one
            if container_id:
                await self._return_container_to_pool(container_id)

    async def _execute_transient_standard(self, code: str, state: Dict[str, Any]) -> Dict[str, Any]:
        """Execute code in a new container without using the pool."""
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
        logger.info("Executing transient with detach=False")
        try:
            # Run synchronously to avoid race condition
            container_output = self.client.containers.run(
                image=self.config.docker.image,
                command=["python", "-c", wrapped_code],
                mem_limit=self.config.docker.memory_limit,
                cpu_quota=int(self.config.docker.cpu_limit * 100000),
                network_disabled=self.config.docker.network_disabled,
                read_only=True,
                remove=True,
                detach=False,  # Run synchronously
            )

            # Decode and parse the output
            output = container_output.decode("utf-8")
            start_marker = "---OUTPUT_START---"
            end_marker = "---OUTPUT_END---"

            start_idx = output.find(start_marker)
            end_idx = output.rfind(end_marker)

            if start_idx >= 0 and end_idx >= 0:
                json_str = output[start_idx + len(start_marker) : end_idx].strip()
                return json.loads(json_str)
            return {"__stdout__": output, "__stderr__": "", "__error__": None, **state}

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

    async def cleanup_pool(self) -> None:
        """Clean up all containers in the pool."""
        if not self.pool_enabled:
            return

        logger.info("Cleaning up container pool")
        async with self.pool_lock:
            # Clean up containers in the pool
            for container_id in list(self.container_pool):
                try:
                    container = self.client.containers.get(container_id)
                    logger.info(f"Removing pooled container {container_id[:12]}")
                    container.remove(force=True)
                except Exception as e:
                    logger.warning(f"Error removing container {container_id[:12]}: {str(e)}")

            # Clean up containers that are in use but not in sessions
            for container_id in list(self.in_use_containers):
                try:
                    # Skip containers that are part of a session
                    if container_id in self.persistent_containers.values():
                        continue

                    container = self.client.containers.get(container_id)
                    logger.info(f"Removing in-use container {container_id[:12]}")
                    container.remove(force=True)
                except Exception as e:
                    logger.warning(f"Error removing container {container_id[:12]}: {str(e)}")

            # Clear pool data structures
            self.container_pool.clear()
            self.in_use_containers.clear()
            self.container_creation_timestamps.clear()

        logger.info("Container pool cleanup complete")

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
