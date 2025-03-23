# Python Docker MCP Client

The `PythonDockerClient` is a client module for interacting with the MCP (Multi-Context Python) server. It provides a simple, yet powerful interface for executing Python code inside Docker containers, both in transient (one-time execution) and persistent (session-based) modes.

## Installation

The client is part of the `python-docker-mcp` package. You can install it using pip:

```bash
pip install python-docker-mcp
```

## Basic Usage

Here's a simple example of how to use the client:

```python
import asyncio
from python_docker_mcp.client import PythonDockerClient

async def main():
    # Create a client instance
    client = PythonDockerClient()

    try:
        # Connect to the server
        await client.connect_to_server()

        # Execute code in a transient container
        result = await client.execute_transient("print('Hello, World!')")
        print(result["output"])  # Output: Hello, World!

    finally:
        # Always close the connection when done
        if client.session:
            await client.close()

if __name__ == "__main__":
    asyncio.run(main())
```

## API Reference

### `PythonDockerClient`

The main client class for interacting with the Python Docker MCP server.

#### Constructor

```python
client = PythonDockerClient()
```

Creates a new client instance. No connection is established until `connect_to_server()` is called.

#### Methods

##### `connect_to_server(server_script_path=None)`

Connects to the MCP server.

- **Parameters:**
  - `server_script_path` (str, optional): Path to the server script. If not provided, the default server script will be used.
- **Returns:** None
- **Raises:**
  - `ValueError`: If the script path has an unsupported extension.
  - `Exception`: If connection fails.

##### `list_tools()`

Lists the available tools on the server.

- **Returns:** List of dictionaries containing tool information.
- **Raises:** `RuntimeError` if not connected.

##### `execute_transient(code, state=None)`

Executes Python code in a transient container and returns the results.

- **Parameters:**
  - `code` (str): The Python code to execute.
  - `state` (dict, optional): Dictionary of variables to inject into the code's namespace.
- **Returns:** A dictionary containing:
  - `raw_output` (str): The raw output from the container.
  - `output` (str): The parsed output (if available).
  - `error` (str or None): Error message if execution failed.
- **Raises:** `RuntimeError` if not connected.

##### `execute_persistent(code, session_id=None)`

Executes Python code in a persistent container. If no session ID is provided, a new session is created.

- **Parameters:**
  - `code` (str): The Python code to execute.
  - `session_id` (str, optional): Session ID for an existing container.
- **Returns:** A tuple (result, session_id) where:
  - `result` is a dictionary containing `raw_output`, `output`, and `error` (similar to `execute_transient`).
  - `session_id` is the ID of the session, which can be used for subsequent calls.
- **Raises:** `RuntimeError` if not connected.

##### `install_package(package_name, session_id=None)`

Installs a Python package in a container.

- **Parameters:**
  - `package_name` (str): The name of the package to install.
  - `session_id` (str, optional): Session ID for an existing container.
- **Returns:** A dictionary containing:
  - `package_name` (str): The installed package name.
  - `success` (bool): Whether installation was successful.
  - `message` (str): Installation message or error.
- **Raises:** `RuntimeError` if not connected.

##### `cleanup_session(session_id)`

Cleans up a persistent session.

- **Parameters:**
  - `session_id` (str): The ID of the session to clean up.
- **Returns:** A boolean indicating success.
- **Raises:** `RuntimeError` if not connected.

##### `close()`

Closes the connection to the server.

- **Returns:** None

## Advanced Usage

### Using Persistent Sessions

Persistent sessions allow you to maintain state between code executions:

```python
async def persistent_example(client):
    # Start a new session
    code1 = "x = 10\nprint(f'x = {x}')"
    result1, session_id = await client.execute_persistent(code1)
    print(result1["output"])  # Output: x = 10

    # Continue the session with another piece of code
    code2 = "x += 5\nprint(f'x now equals {x}')"
    result2, session_id = await client.execute_persistent(code2, session_id)
    print(result2["output"])  # Output: x now equals 15

    # Always clean up the session when done
    await client.cleanup_session(session_id)
```

### Installing Packages

You can install Python packages in persistent containers:

```python
async def install_package_example(client):
    # Start a session
    _, session_id = await client.execute_persistent("print('Session started')")

    # Install numpy
    result = await client.install_package("numpy", session_id)
    if result["success"]:
        print(f"Successfully installed {result['package_name']}")

    # Use the installed package
    code = """
    import numpy as np
    arr = np.array([1, 2, 3, 4, 5])
    print(f'Mean: {np.mean(arr)}')
    """
    result, _ = await client.execute_persistent(code, session_id)
    print(result["output"])  # Output: Mean: 3.0

    # Clean up
    await client.cleanup_session(session_id)
```

### Error Handling

The client provides information about errors that occur during code execution:

```python
async def error_handling_example(client):
    # Execute code with an error
    result = await client.execute_transient("print(undefined_variable)")

    if result["error"]:
        print(f"Error occurred: {result['error']}")
    else:
        print(f"Output: {result['output']}")
```

## Custom Server Script

You can use a custom server script by specifying its path:

```python
await client.connect_to_server("/path/to/custom_server.py")
```

The client automatically detects the script type based on its extension and will use the appropriate interpreter (Python or Node.js for `.js` files).

## Complete Example

For a complete example demonstrating all the features, see the [client_example.py](../examples/client_example.py) file included in the package.
