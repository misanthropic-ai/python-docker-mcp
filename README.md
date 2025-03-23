# python-docker-mcp

Dockerized Python execution environment for AI agents.

## Overview

This MCP server provides a safe, sandboxed Python execution environment for LLM-powered agents. It allows agents to:

- Execute Python code in isolated Docker containers
- Choose between transient or persistent execution environments
- Install packages as needed for specific tasks
- Maintain state between execution steps

## Components

### Docker Execution Environment

The server implements two types of execution environments:

1. **Transient Environment**
   - Each execution is isolated in a fresh container
   - State must be explicitly passed and returned between calls
   - Safer for one-off code execution

2. **Persistent Environment**
   - Maintains state between executions
   - Variables defined in one execution are available in subsequent executions
   - Suitable for interactive, stateful REPL-like sessions

### Tools

The server provides the following tools:

- **execute-transient**: Run Python code in a transient Docker container
  - Takes `code` (required) and `state` (optional) parameters
  - Returns execution results and updated state

- **execute-persistent**: Run Python code in a persistent Docker container
  - Takes `code` (required) and `session_id` (optional) parameters
  - Returns execution results
  - Maintains state between calls

- **install-package**: Install Python packages in a container
  - Takes `package_name` (required) and `session_id` (optional) parameters
  - Uses `uv` for efficient package installation
  - Returns installation output

- **cleanup-session**: Clean up a persistent session
  - Takes `session_id` (required) parameter
  - Stops and removes the associated Docker container

## Configuration

The server can be configured via a YAML configuration file. By default, it looks for a file at `~/.python-docker-mcp/config.yaml`.

Example configuration:

```yaml
docker:
  image: python:3.12.2-slim
  working_dir: /app
  memory_limit: 256m
  cpu_limit: 0.5
  timeout: 30
  network_disabled: true
  read_only: true

package:
  installer: uv
  index_url: null
  trusted_hosts: []

allowed_modules:
  - math
  - datetime
  - random
  - json
  - re
  - collections

blocked_modules:
  - os
  - sys
  - subprocess
  - shutil
  - pathlib
```

## Quickstart

### Install

#### Claude Desktop

On MacOS: `~/Library/Application\ Support/Claude/claude_desktop_config.json`
On Windows: `%APPDATA%/Claude/claude_desktop_config.json`

<details>
  <summary>Development/Unpublished Servers Configuration</summary>
  ```
  "mcpServers": {
    "python-docker-mcp": {
      "command": "uv",
      "args": [
        "--directory",
        "/Users/shannon/Workspace/artivus/python-docker-mcp",
        "run",
        "python-docker-mcp"
      ]
    }
  }
  ```
</details>

<details>
  <summary>Published Servers Configuration</summary>
  ```
  "mcpServers": {
    "python-docker-mcp": {
      "command": "uvx",
      "args": [
        "python-docker-mcp"
      ]
    }
  }
  ```
</details>

## Development

### Requirements

- Docker must be installed and running on the host system
- Python 3.11 or later
- `uv` for package management

### Building and Publishing

To prepare the package for distribution:

1. Sync dependencies and update lockfile:
```bash
uv sync
```

2. Build package distributions:
```bash
uv build
```

3. Publish to PyPI:
```bash
uv publish
```

### Debugging

Since MCP servers run over stdio, debugging can be challenging. For the best debugging
experience, we strongly recommend using the [MCP Inspector](https://github.com/modelcontextprotocol/inspector).

You can launch the MCP Inspector via [`npm`](https://docs.npmjs.com/downloading-and-installing-node-js-and-npm) with this command:

```bash
npx @modelcontextprotocol/inspector uv --directory /path/to/python-docker-mcp run python-docker-mcp
```

## Example Usage

### Transient Execution

```
# Calculate the factorial of 5
result = await call_tool("execute-transient", {
  "code": "def factorial(n):\n    return 1 if n <= 1 else n * factorial(n-1)\n\nresult = factorial(5)\nprint(f'The factorial of 5 is {result}')"
})
```

### Persistent Session

```
# Create a persistent session and define a function
result = await call_tool("execute-persistent", {
  "code": "def add(a, b):\n    return a + b\n\nprint('Function defined')"
})

# Use the function in a subsequent call with the same session
result = await call_tool("execute-persistent", {
  "session_id": "previous_session_id",
  "code": "result = add(10, 20)\nprint(f'10 + 20 = {result}')"
})
```

### Installing Packages

```
# Install NumPy in a persistent session
result = await call_tool("install-package", {
  "session_id": "my_math_session",
  "package_name": "numpy"
})

# Use NumPy in the session
result = await call_tool("execute-persistent", {
  "session_id": "my_math_session",
  "code": "import numpy as np\narr = np.array([1, 2, 3, 4, 5])\nprint(f'Mean: {np.mean(arr)}')"
})
```