"""Module for managing Docker containers to execute Python code securely."""

import asyncio
import json
import os
import tempfile
from typing import Any, Dict, Optional

import docker

from .config import Configuration, load_config


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
        """
        Execute code in a new container that doesn't persist state.

        Args:
            code: The Python code to execute
            state: Optional state dictionary to pass to the execution environment

        Returns:
            The updated state dictionary after execution
        """
        if state is None:
            state = {}

        try:
            # Create temporary directory to mount inside the container
            with tempfile.TemporaryDirectory() as temp_dir:
                # Create Python script file with the code
                script_path = os.path.join(temp_dir, "script.py")
                state_path = os.path.join(temp_dir, "state.json")
                output_path = os.path.join(temp_dir, "output.json")

                # Write state to a JSON file
                with open(state_path, "w") as f:
                    json.dump(state, f)

                # Create a wrapper script that loads the state, executes the code, and saves the state
                with open(script_path, "w") as f:
                    f.write(self._create_wrapper_script(code))

                # Run container with the script
                container = self.client.containers.run(
                    image=self.config.docker.image,
                    command=["python", "/app/script.py"],
                    volumes={temp_dir: {"bind": "/app", "mode": "rw"}},
                    working_dir=self.config.docker.working_dir,
                    mem_limit=self.config.docker.memory_limit,
                    cpu_quota=int(self.config.docker.cpu_limit * 100000),  # Docker CPU quota in microseconds
                    network_disabled=self.config.docker.network_disabled,
                    read_only=self.config.docker.read_only,
                    remove=True,
                    detach=True,
                )

                # Wait for the container to finish or timeout
                try:
                    exit_code = await asyncio.wait_for(
                        self._wait_for_container(container.id),
                        timeout=self.config.docker.timeout,
                    )

                    # Check if the container exited with an error
                    if exit_code != 0:
                        logs = container.logs().decode("utf-8")
                        raise DockerExecutionError(f"Container exited with code {exit_code}: {logs}")

                    # Load output state
                    if os.path.exists(output_path):
                        with open(output_path, "r") as f:
                            return json.load(f)
                    else:
                        raise DockerExecutionError("Execution failed to produce output state")

                except asyncio.TimeoutError:
                    # Force stop the container if it times out
                    try:
                        container.stop(timeout=1)
                    except Exception:
                        pass
                    raise DockerExecutionError(f"Execution timed out after {self.config.docker.timeout} seconds")

        except Exception as e:
            if not isinstance(e, DockerExecutionError):
                raise DockerExecutionError(f"Error executing code in Docker: {str(e)}")
            raise

    async def execute_persistent(self, session_id: str, code: str) -> Dict[str, Any]:
        """
        Execute code in a persistent container that retains state between calls.

        Args:
            session_id: A unique identifier for the session
            code: The Python code to execute

        Returns:
            The result of the execution
        """
        container_id = self.persistent_containers.get(session_id)

        # Create a new container if it doesn't exist
        if not container_id:
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
                network_disabled=self.config.docker.network_disabled,
                read_only=False,  # Need to be writable for persistent sessions
                detach=True,
            )
            container_id = container.id
            self.persistent_containers[session_id] = container_id

        # Execute the code in the container
        try:
            # Create a temporary file with the code
            with tempfile.NamedTemporaryFile(suffix=".py", mode="w") as f:
                wrapped_code = self._create_execute_persist_script(code)
                f.write(wrapped_code)
                f.flush()

                # Copy the script to the container
                os.system(f"docker cp {f.name} {container_id}:/app/execute_script.py")

            # Execute the script in the container
            exec_result = self.client.containers.get(container_id).exec_run(
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
        """
        Install a Python package in a container.

        Args:
            session_id: The session ID for persistent containers, or None for transient
            package_name: The name of the package to install

        Returns:
            The output of the installation command
        """
        install_cmd = []
        if self.config.package.installer == "uv":
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
            exec_result = self.client.containers.get(container_id).exec_run(
                cmd=install_cmd,
                workdir=self.config.docker.working_dir,
            )
            return exec_result.output.decode("utf-8")
        else:
            # Create a temporary container just for installation
            container = self.client.containers.run(
                image=self.config.docker.image,
                command=install_cmd,
                working_dir=self.config.docker.working_dir,
                network_disabled=False,  # Need network for package installation
                remove=True,
            )
            return container.logs().decode("utf-8")

    def cleanup_session(self, session_id: str) -> None:
        """
        Clean up a persistent session by stopping and removing its container.
        """
        if session_id in self.persistent_containers:
            container_id = self.persistent_containers[session_id]
            try:
                container = self.client.containers.get(container_id)
                container.stop()
                container.remove()
            except Exception:
                pass  # Ignore errors during cleanup

            del self.persistent_containers[session_id]

    def cleanup_all_sessions(self) -> None:
        """
        Clean up all persistent sessions.
        """
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
                print(f"Error waiting for container {container_id}: {e}")
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

# Execute code with state dict as globals
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

# Save updated state
print("Writing output to /app/output.json...")
try:
    with open('/app/output.json', 'w') as f:
        json.dump(state_dict, f)
    print("Successfully wrote output state")
    # Verify file exists after writing
    print(f"File exists after writing: {{os.path.exists('/app/output.json')}}")
    print(f"File size: {{os.path.getsize('/app/output.json')}}")
except Exception as e:
    error_with_traceback = f"{{e}}\\n{{traceback.format_exc()}}"
    print(f"Error writing output: {{error_with_traceback}}")

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
from contextlib import redirect_stdout, redirect_stderr

print("Docker persistent execution script starting...")
print(f"Python version: {{sys.version}}")
print(f"Current directory: {{os.getcwd()}}")
print(f"Directory contents: {{os.listdir('.')}}")

# Capture stdout and stderr
stdout_capture = io.StringIO()
stderr_capture = io.StringIO()

# Execute code
try:
    print("Executing code...")
    with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
        exec({repr(code)})
        result = {{
            "output": stdout_capture.getvalue(),
            "error": None
        }}
except Exception as e:
    error_with_traceback = f"{{e}}\\n{{traceback.format_exc()}}"
    result = {{
        "output": stdout_capture.getvalue(),
        "error": error_with_traceback
    }}
    print(f"Error during execution: {{error_with_traceback}}")

# Output the result as JSON
print("---OUTPUT_START---")
print(json.dumps(result))
print("---OUTPUT_END---")

print("Docker persistent execution script completed.")
"""
