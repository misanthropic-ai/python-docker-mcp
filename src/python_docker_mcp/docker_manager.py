"""Module for managing Docker containers to execute Python code securely."""

import asyncio
import logging
import os
import re
import tempfile
import time
from typing import Any, Dict, List, Optional, Set, Tuple

import docker
from docker.errors import ImageNotFound, NotFound

from .build_docker_image import build_docker_image, get_dockerfile_path
from .config import Configuration, load_config

# Set up logging
logger = logging.getLogger(__name__)


class DockerExecutionError(Exception):
    """Exception raised when Docker execution encounters an error."""

    pass


class PythonValidationError(Exception):
    """Exception raised when Python code validation fails."""

    pass


class PythonExecutionError(Exception):
    """Exception raised when Python code fails to execute.

    This provides more structured information about Python-specific errors.
    """

    def __init__(self, message: str, error_type: str = "unknown", line: Optional[int] = None, column: Optional[int] = None):
        """Initialize the error.

        Args:
            message: The error message
            error_type: The type of Python error (e.g., "syntax_error", "runtime_error")
            line: Optional line number where the error occurred
            column: Optional column number where the error occurred
        """
        self.error_type = error_type
        self.line = line
        self.column = column
        self.message = message
        super().__init__(message)

    def to_dict(self) -> Dict[str, Any]:
        """Convert the error to a dictionary for JSON serialization."""
        return {
            "error_type": self.error_type,
            "message": self.message,
            "line": self.line,
            "column": self.column,
        }


class PythonCodeValidator:
    """Validates Python code for security and safety."""

    def __init__(self, config: Configuration):
        """Initialize the validator with configuration.

        Args:
            config: The configuration for validation
        """
        self.config = config
        self._compile_regex_patterns()

    def _compile_regex_patterns(self) -> None:
        """Compile regex patterns for detecting unsafe imports and operations."""
        # Build regex patterns for allowed and blocked imports
        # allowed_patterns = [re.escape(imp) for imp in self.config.allowed_modules]
        # blocked_patterns = [re.escape(imp) for imp in self.config.blocked_modules]

        # Pattern for finding all imports
        self.import_pattern = re.compile(r"import\s+([A-Za-z0-9_.]+)")

        # Pattern for finding potentially unsafe operations
        self.unsafe_pattern = re.compile(r"(os\.|subprocess\.|shutil\.|pathlib\.)")

    def validate(self, code: str) -> Tuple[bool, Optional[str]]:
        """Validate Python code for safety.

        Args:
            code: The Python code to validate

        Returns:
            A tuple of (is_valid, error_message)
        """
        # Find all imports in the code
        imports = self.import_pattern.findall(code)

        # Check for blocked imports
        for import_name in imports:
            if import_name in self.config.blocked_modules:
                return False, f"Import '{import_name}' is blocked for security reasons"

        # Check if all imports are in the allowed list
        if self.config.allowed_modules:
            for import_name in imports:
                if import_name not in self.config.allowed_modules:
                    return False, f"Import '{import_name}' is not in the allowed list"

        # Check for potentially unsafe operations
        if self.unsafe_pattern.search(code):
            return False, "Potentially unsafe operation detected"

        return True, None

    def parse_python_error(self, output: str) -> Optional[PythonExecutionError]:
        """Parse Python execution error output and convert to structured error.

        Args:
            output: The error output from Python

        Returns:
            A PythonExecutionError or None if no error could be parsed
        """
        if not output or "error:" not in output.lower():
            return None

        # Common Python error patterns
        # Example: File "script.py", line 10, in <module>
        error_pattern = re.compile(r'File\s+"[^"]+",\s+line\s+(\d+),\s+in\s+<module>')

        for line in output.splitlines():
            match = error_pattern.match(line)
            if match:
                line_num = int(match.group(1))

                # Determine error type based on message content
                error_type = "unknown"
                if "SyntaxError" in output:
                    error_type = "syntax_error"
                elif "NameError" in output:
                    error_type = "name_error"
                elif "TypeError" in output:
                    error_type = "type_error"
                elif "ImportError" in output:
                    error_type = "import_error"
                elif "RuntimeError" in output:
                    error_type = "runtime_error"

                return PythonExecutionError(message=output.split("\n")[-1].strip(), error_type=error_type, line=line_num)

        # If we couldn't parse a specific error, return a generic one
        return PythonExecutionError(message="Python execution error: " + output.split("\n")[0], error_type="execution_error")


class DockerManager:
    """Manages Docker containers for executing Python code."""

    def __init__(self, config: Optional[Configuration] = None):
        """Initialize the Docker manager with the given configuration."""
        self.config = config or load_config()
        self.docker_available = False

        # Handle the case where Docker is not available gracefully
        try:
            self.client = docker.from_env()
            self.docker_available = True
            logger.info("Docker connection established successfully")

            # Ensure the configured Docker image exists locally; build it from the local Dockerfile if missing
            if self.docker_available:
                try:
                    self.client.images.get(self.config.docker.image)
                except ImageNotFound:
                    logger.info(f"Docker image {self.config.docker.image} not found locally. Building from local Dockerfile.")
                    try:
                        dockerfile_path = get_dockerfile_path()
                        build_success = build_docker_image(tag=self.config.docker.image, dockerfile=dockerfile_path)
                        if not build_success:
                            logger.warning(f"Failed to build Docker image: {self.config.docker.image}. Continuing, but execution may fail.")
                    except Exception as build_err:
                        logger.error(f"Error building Docker image {self.config.docker.image}: {build_err}")
        except Exception as e:
            logger.error(f"Docker is not available: {e}")
            logger.warning("Running with Docker unavailable - tool calls will return errors")
            self.client = None

        self.persistent_containers: Dict[str, str] = {}  # session_id -> container_id
        self.validator = PythonCodeValidator(self.config)

        # Container pooling functionality
        self.container_pool: List[str] = []  # List of available container IDs
        self.in_use_containers: Set[str] = set()  # Set of container IDs currently in use
        self.pool_lock = asyncio.Lock()  # Lock for thread safety when accessing the pool

        # Pool configuration - add reasonable defaults if not in config
        try:
            self.pool_size = getattr(self.config.docker, "pool_size", 32)
            self.pool_max_age = getattr(self.config.docker, "pool_max_age", 300)  # 5 minutes
            self.max_concurrent_creations = getattr(self.config.docker, "max_concurrent_creations", 5)
            self.pool_enabled = getattr(self.config.docker, "pool_enabled", True)
        except AttributeError:
            # If we hit any AttributeError, disable pooling
            logger.warning("Error accessing pooling configuration attributes, disabling container pooling")
            self.pool_size = 0
            self.pool_max_age = 300
            self.max_concurrent_creations = 5
            self.pool_enabled = False

        self.container_creation_timestamps: Dict[str, float] = {}  # container_id -> creation_timestamp

        # Container acquisition semaphore to limit concurrent container creations
        self.container_semaphore = asyncio.Semaphore(self.max_concurrent_creations)

    async def initialize_pool(self) -> None:
        """Initialize the container pool."""
        if not self.pool_enabled:
            logger.info("Container pooling is disabled, skipping initialization")
            return

        logger.info(f"Initializing container pool with size {self.pool_size}")

        async with self.pool_lock:
            # Clear any existing pool state
            self.container_pool.clear()
            self.in_use_containers.clear()
            self.container_creation_timestamps.clear()

            # Create initial pool containers
            tasks = []
            for _ in range(self.pool_size):
                tasks.append(self._create_pooled_container())

            if tasks:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                successful_creations = 0

                for result in results:
                    if isinstance(result, Exception):
                        logger.error(f"Error creating pooled container: {str(result)}")
                    elif isinstance(result, str):  # Ensure result is a string
                        self.container_pool.append(result)
                        self.container_creation_timestamps[result] = time.time()
                        successful_creations += 1

                logger.info(f"Container pool initialized with {successful_creations} containers")

                if successful_creations < self.pool_size:
                    logger.warning(f"Only created {successful_creations} out of {self.pool_size} requested containers")

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
                    read_only=False,  # Allow writing to /app
                    labels={"python_docker_mcp.pooled": "true", "python_docker_mcp.created": str(time.time())},
                )
                logger.debug(f"Created pooled python container {container.id[:12]}")
                return container.id
        except Exception as e:
            logger.error(f"Error creating pooled python container: {str(e)}")
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
                logger.debug(f"Retrieved container {container_id[:12]} from pool")

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

                # Reset container state if needed (stop running processes, clean temporary files)
                try:
                    container.exec_run("pkill -9 python", user="root")
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
                    # Pool is full, find the oldest container to replace
                    oldest_container_id = None
                    oldest_timestamp = float("inf")

                    for pool_container_id in list(self.container_pool):
                        if pool_container_id in self.container_creation_timestamps:
                            timestamp = self.container_creation_timestamps[pool_container_id]
                            if timestamp < oldest_timestamp:
                                oldest_timestamp = timestamp
                                oldest_container_id = pool_container_id

                    if oldest_container_id:
                        # Remove the oldest container from the pool
                        self.container_pool.remove(oldest_container_id)

                        try:
                            # Get and remove the container
                            oldest_container = self.client.containers.get(oldest_container_id)
                            oldest_container.remove(force=True)
                            logger.debug(f"Removed oldest container {oldest_container_id[:12]} from pool to make room")
                        except Exception as e:
                            logger.warning(f"Error removing oldest container {oldest_container_id[:12]}: {str(e)}")

                        # Remove timestamp for the removed container
                        if oldest_container_id in self.container_creation_timestamps:
                            del self.container_creation_timestamps[oldest_container_id]

                        # Add the current container to the pool
                        self.container_pool.append(container_id)
                        self.container_creation_timestamps[container_id] = time.time()
                        logger.debug(f"Added container {container_id[:12]} to pool, replacing oldest container")
                    else:
                        # No containers with timestamps found in the pool (shouldn't happen)
                        container.remove(force=True)
                        if container_id in self.container_creation_timestamps:
                            del self.container_creation_timestamps[container_id]
                        logger.debug(f"Pool is full but no containers with timestamps found, removed {container_id[:12]}")
            except Exception as e:
                logger.warning(f"Error returning container {container_id[:12]} to pool: {str(e)}")
                # Try to force remove if there's an issue
                try:
                    self.client.containers.get(container_id).remove(force=True)
                except Exception as e:
                    logger.warning(f"Error removing container {container_id[:12]}: {str(e)}")

                if container_id in self.container_creation_timestamps:
                    del self.container_creation_timestamps[container_id]

    async def execute_transient(self, code: str, state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Execute Python code in a new container that doesn't persist state."""
        try:
            # Validate the code first
            is_valid, error_message = self.validator.validate(code)
            if not is_valid:
                return {
                    "stdout": "",
                    "error": f"Validation error: {error_message}",
                    "error_type": "validation_error",
                    "status": "error",
                }

            # If Docker is not available, return a clear error
            if not self.docker_available:
                return {
                    "stdout": "",
                    "error": "Docker is not available. Please make sure Docker is running and restart the server.",
                    "error_type": "docker_unavailable",
                    "status": "error",
                }

            # Use pooled execution if enabled
            if self.pool_enabled:
                return await self._execute_transient_pooled(code, state)
            else:
                return await self._execute_transient_original(code, state)

        except Exception as e:
            if not isinstance(e, DockerExecutionError):
                raise DockerExecutionError(f"Error executing code in Docker: {str(e)}")
            raise

    async def _execute_transient_pooled(self, code: str, state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Execute Python code using a container from the pool."""
        container_id = None
        try:
            # Get a container from the pool
            container_id = await self._get_container_from_pool()
            container = self.client.containers.get(container_id)

            # Create temporary directory to mount inside the container
            with tempfile.TemporaryDirectory() as temp_dir:
                # Create Python file with the code
                script_path = os.path.join(temp_dir, "script.py")

                # Write the Python code to a file
                with open(script_path, "w") as f:
                    f.write(code)

                # Copy script to container
                import subprocess

                cp_script = subprocess.run(["docker", "cp", script_path, f"{container.id}:/app/script.py"], capture_output=True)

                if cp_script.returncode != 0:
                    raise DockerExecutionError(f"Failed to copy script to container: {cp_script.stderr.decode('utf-8')}")

                # Run the Python code directly
                exec_result = container.exec_run(
                    cmd=["python", "/app/script.py"],
                    workdir="/app",
                )

                # Clean up the script
                container.exec_run(
                    cmd=["rm", "-f", "/app/script.py"],
                )

                # Decode the output
                output = exec_result.output.decode("utf-8")
                exit_code = exec_result.exit_code

                # Check for Python-specific errors and parse them if present
                is_success = exit_code == 0 and "error:" not in output.lower()

                result = {
                    "stdout": output,
                    "exit_code": exit_code,
                    "status": "success" if is_success else "error",
                }

                # If there was an error, add more detailed error information
                if not is_success:
                    python_error = self.validator.parse_python_error(output)
                    if python_error:
                        result["error"] = python_error.message
                        result["error_info"] = python_error.to_dict()
                    else:
                        result["error"] = "Python execution error" if exit_code != 0 else "Unknown error in Python output"

                return result

        except Exception as e:
            logger.error(f"Error in pooled execution: {str(e)}")
            raise DockerExecutionError(f"Error executing Python code in pooled container: {str(e)}")

        finally:
            # Return the container to the pool if we got one
            if container_id:
                await self._return_container_to_pool(container_id)

    async def _execute_transient_original(self, code: str, state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Original implementation of transient execution without pooling."""
        # Create temporary directory to mount inside the container
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create Python file with the code
            script_path = os.path.join(temp_dir, "script.py")

            # Create a wrapper script to capture output and errors
            python_runner_path = os.path.join(temp_dir, "run_python.sh")

            # Write the Python code to a file
            with open(script_path, "w") as f:
                f.write(code)

            # Create a wrapper script to run Python and capture different streams
            with open(python_runner_path, "w") as f:
                script_content = """#!/bin/bash
# Wrapper script to execute Python and capture output streams
echo "Running Python in $(pwd)"
echo "Python version: $(python --version)"
echo "Content of script.py:"
cat /app/script.py
echo "---"

# Run Python with the script
python_output=$(python /app/script.py 2>&1)
exit_code=$?

# Write structured result with clear markers for parsing
echo "---PYTHON_OUTPUT_START---"
echo "$python_output"
echo "---PYTHON_OUTPUT_END---"
echo "---PYTHON_EXIT_CODE_START---"
echo "$exit_code"
echo "---PYTHON_EXIT_CODE_END---"
exit $exit_code
"""
                f.write(script_content)

            # Make the wrapper script executable
            os.chmod(python_runner_path, 0o755)

            # Run container synchronously with the script
            container_output = self.client.containers.run(
                image=self.config.docker.image,
                command=["timeout", str(self.config.docker.timeout), "/app/run_python.sh"],
                volumes={temp_dir: {"bind": "/app", "mode": "rw"}},
                working_dir="/app",  # Execute in the mounted volume
                mem_limit=self.config.docker.memory_limit,
                cpu_quota=int(self.config.docker.cpu_limit * 100000),
                network_disabled=self.config.docker.network_disabled,
                remove=True,
                detach=False,  # Run synchronously
            )

            # Decode the output
            output = container_output.decode("utf-8")

            # Parse the structured output
            python_output = ""
            exit_code = -1

            # Extract the Python output
            output_start = output.find("---PYTHON_OUTPUT_START---")
            output_end = output.find("---PYTHON_OUTPUT_END---")
            if output_start >= 0 and output_end >= 0:
                python_output = output[output_start + len("---PYTHON_OUTPUT_START---") : output_end].strip()

            # Extract the exit code
            exit_code_start = output.find("---PYTHON_EXIT_CODE_START---")
            exit_code_end = output.find("---PYTHON_EXIT_CODE_END---")
            if exit_code_start >= 0 and exit_code_end >= 0:
                exit_code_str = output[exit_code_start + len("---PYTHON_EXIT_CODE_START---") : exit_code_end].strip()
                try:
                    exit_code = int(exit_code_str)
                except ValueError:
                    exit_code = -1

            # Check for Python-specific errors and parse them if present
            is_success = exit_code == 0 and "error:" not in python_output.lower()

            result = {
                "stdout": python_output,
                "exit_code": exit_code,
                "status": "success" if is_success else "error",
            }

            # If there was an error, add more detailed error information
            if not is_success:
                python_error = self.validator.parse_python_error(python_output)
                if python_error:
                    result["error"] = python_error.message
                    result["error_info"] = python_error.to_dict()
                else:
                    result["error"] = "Python execution error" if exit_code != 0 else "Unknown error in Python output"

            return result

    async def execute_persistent(self, session_id: str, code: str) -> Dict[str, Any]:
        """Execute Python code in a persistent container that retains state between calls.

        Args:
            session_id: A unique identifier for the session
            code: The Python code to execute

        Returns:
            A dictionary containing the execution results with stdout, error information and status
        """
        # Validate the code first
        is_valid, error_message = self.validator.validate(code)
        if not is_valid:
            return {
                "stdout": "",
                "error": f"Validation error: {error_message}",
                "error_type": "validation_error",
                "status": "error",
            }

        # If Docker is not available, return a clear error
        if not self.docker_available:
            return {
                "stdout": "",
                "error": "Docker is not available. Please make sure Docker is running and restart the server.",
                "error_type": "docker_unavailable",
                "status": "error",
                "session_id": session_id,
            }

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

            # Create a temporary file with the code
            exec_id = os.urandom(8).hex()
            script_filename = f"script_{exec_id}.py"
            wrapper_filename = f"run_python_{exec_id}.sh"

            # Escape single quotes for shell command
            safe_code = code.replace("'", "'\"'\"'")

            # Create the Python file
            cmd = f"echo '{safe_code}' > /app/{script_filename}"
            script_create_cmd = container.exec_run(
                cmd=["sh", "-c", cmd],
            )

            if script_create_cmd.exit_code != 0:
                raise DockerExecutionError(f"Failed to create script file: {script_create_cmd.output.decode('utf-8')}")

            # Create a wrapper script to capture output
            wrapper_script = f"""#!/bin/bash
# Wrapper script to execute Python and capture output streams
echo "Running Python in $(pwd)"
echo "Python version: $(python --version)"
echo "Content of {script_filename}:"
cat /app/{script_filename}
echo "---"

# Run Python with the script
python_output=$(python /app/{script_filename} 2>&1)
exit_code=$?

# Write structured result with clear markers for parsing
echo "---PYTHON_OUTPUT_START---"
echo "$python_output"
echo "---PYTHON_OUTPUT_END---"
echo "---PYTHON_EXIT_CODE_START---"
echo "$exit_code"
echo "---PYTHON_EXIT_CODE_END---"

# Clean up the script file
rm -f /app/{script_filename}

exit $exit_code
"""
            # Escape single quotes for shell command
            safe_wrapper = wrapper_script.replace("'", "'\"'\"'")
            cmd = f"echo '{safe_wrapper}' > /app/{wrapper_filename} && chmod +x /app/{wrapper_filename}"

            wrapper_create_cmd = container.exec_run(
                cmd=["sh", "-c", cmd],
            )

            if wrapper_create_cmd.exit_code != 0:
                raise DockerExecutionError(f"Failed to create wrapper script: {wrapper_create_cmd.output.decode('utf-8')}")

            # Execute the wrapper script
            exec_result = container.exec_run(
                cmd=[f"/app/{wrapper_filename}"],
                workdir="/app",
            )

            # Capture the output
            output = exec_result.output.decode("utf-8")
            exit_code = exec_result.exit_code

            # Clean up the wrapper script
            container.exec_run(
                cmd=["rm", f"/app/{wrapper_filename}"],
            )

            # Parse the structured output
            python_output = ""
            parsed_exit_code = exit_code  # Default to the exit code from exec_run

            # Extract the Python output
            output_start = output.find("---PYTHON_OUTPUT_START---")
            output_end = output.find("---PYTHON_OUTPUT_END---")
            if output_start >= 0 and output_end >= 0:
                python_output = output[output_start + len("---PYTHON_OUTPUT_START---") : output_end].strip()

            # Extract the exit code from the output
            exit_code_start = output.find("---PYTHON_EXIT_CODE_START---")
            exit_code_end = output.find("---PYTHON_EXIT_CODE_END---")
            if exit_code_start >= 0 and exit_code_end >= 0:
                exit_code_str = output[exit_code_start + len("---PYTHON_EXIT_CODE_START---") : exit_code_end].strip()
                try:
                    parsed_exit_code = int(exit_code_str)
                except ValueError:
                    parsed_exit_code = exit_code  # Fall back to the original exit code

            # Check for Python-specific errors and parse them if present
            is_success = parsed_exit_code == 0 and "error:" not in python_output.lower()

            result = {
                "stdout": python_output,
                "exit_code": parsed_exit_code,
                "status": "success" if is_success else "error",
                "session_id": session_id,  # Include the session ID in the response
            }

            # If there was an error, add more detailed error information
            if not is_success:
                python_error = self.validator.parse_python_error(python_output)
                if python_error:
                    result["error"] = python_error.message
                    result["error_info"] = python_error.to_dict()
                else:
                    result["error"] = "Python execution error" if parsed_exit_code != 0 else "Unknown error in Python output"

            return result

        except Exception as e:
            if isinstance(e, NotFound):
                # Container no longer exists, remove from tracked containers
                if session_id in self.persistent_containers:
                    del self.persistent_containers[session_id]
                raise DockerExecutionError(f"Session {session_id} has expired or was deleted")
            else:
                raise DockerExecutionError(f"Error executing Python code: {str(e)}")

    async def install_package(self, session_id: Optional[str], package_name: str) -> str:
        """Install a Python package in a Docker container.

        Args:
            session_id: Optional session ID for persistent installation
            package_name: The name of the package to install

        Returns:
            The output from the package installation
        """
        if not self.docker_available:
            raise DockerExecutionError("Docker is not available")

        try:
            # Validate package name for security
            if not re.match(r"^[a-zA-Z0-9_.-]+$", package_name):
                raise ValueError(f"Invalid package name: {package_name}")

            # Prepare the pip install command
            install_cmd = f"pip install {package_name}"

            if session_id:
                # Install in a persistent container
                if session_id not in self.persistent_containers:
                    raise ValueError(f"Session {session_id} not found")

                container_id = self.persistent_containers[session_id]
                container = self.client.containers.get(container_id)

                # Execute the pip install command
                result = container.exec_run(
                    cmd=["sh", "-c", install_cmd],
                    workdir="/app",
                    environment={"PYTHONPATH": "/app"},
                )

                if result.exit_code != 0:
                    raise DockerExecutionError(f"Failed to install package: {result.output.decode()}")

                return result.output.decode()
            else:
                # Install in a transient container
                container = self.client.containers.run(
                    image=self.config.docker.image,
                    command=["sh", "-c", f"{install_cmd} && pip list"],
                    detach=False,
                    mem_limit=self.config.docker.memory_limit,
                    cpu_quota=int(self.config.docker.cpu_limit * 100000),
                    network_disabled=self.config.docker.network_disabled,
                    remove=True,
                )

                return container.decode()

        except docker.errors.NotFound:
            raise DockerExecutionError("Container not found")
        except docker.errors.APIError as e:
            raise DockerExecutionError(f"Docker API error: {str(e)}")
        except Exception as e:
            raise DockerExecutionError(f"Error installing package: {str(e)}")

    async def cleanup_session(self, session_id: str) -> Dict[str, Any]:
        """Clean up a persistent session.

        Args:
            session_id: The session ID to clean up

        Returns:
            A dictionary indicating success or failure
        """
        # If Docker is not available, return a clear error
        if not self.docker_available:
            return {"status": "error", "message": "Docker is not available. Please make sure Docker is running and restart the server."}

        container_id = self.persistent_containers.get(session_id)
        if not container_id:
            return {"status": "not_found", "message": f"No session found with ID {session_id}"}

        try:
            container = self.client.containers.get(container_id)
            container.stop()
            container.remove()
            del self.persistent_containers[session_id]
            return {"status": "success", "message": f"Session {session_id} cleaned up successfully"}
        except NotFound:
            # Container already gone, just remove the reference
            if session_id in self.persistent_containers:
                del self.persistent_containers[session_id]
            return {"status": "not_found", "message": f"Session {session_id} not found, may have already been cleaned up"}
        except Exception as e:
            return {"status": "error", "message": f"Error cleaning up session {session_id}: {str(e)}"}

    async def _wait_for_container(self, container_id: str) -> int:
        """Wait for a container to finish and return its exit code."""
        client = docker.APIClient()
        poll_interval = 0.1  # 100ms between polls
        max_polls = int(self.config.docker.timeout / poll_interval)

        for _ in range(max_polls):  # Poll 10 times per second
            try:
                container_info = client.inspect_container(container_id)
                if not container_info["State"]["Running"]:
                    return container_info["State"]["ExitCode"]
            except docker.errors.NotFound:
                # Container removed, assume success
                return 0
            except Exception as e:
                logger.warning(f"Error checking container state: {e}")
                # Continue waiting despite the error
            await asyncio.sleep(poll_interval)

        # If we got here, container is still running after timeout period
        logger.warning(f"Container {container_id} timed out after {self.config.docker.timeout} seconds")
        return -1  # Indicate timeout
