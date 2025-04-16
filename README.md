# python-docker-mcp

Dockerized Python execution environment for AI agents.

## Overview

This MCP server provides a safe, sandboxed Python execution environment for LLM-powered agents. It allows agents to:

- Execute Python code in isolated Docker containers
- Choose between transient or persistent execution environments
- Install packages as needed for specific tasks
- Maintain state between execution steps

## Installation

### Requirements

- Docker must be installed and running on the host system
- Python 3.11 or later
- `uv` for package management (recommended)

### Install from PyPI

```bash
# Using uv (recommended)
uv pip install python-docker-mcp

# Using pip
pip install python-docker-mcp
```

### Install from Source

```bash
# Clone the repository
git clone https://github.com/artivus/python-docker-mcp.git
cd python-docker-mcp

# Install with uv
uv pip install -e .

# Or with pip
pip install -e .
```

## Quick Start

### Running the Server

The python-docker-mcp server can be started directly using the module:

```bash
python -m python_docker_mcp
```

This will start the MCP server and listen for JSONRPC requests on stdin/stdout.

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

### Preinstalled Packages

The Docker containers come with several common scientific and data analysis libraries preinstalled:

- **NumPy**: For numerical computing
- **Pandas**: For data manipulation and analysis
- **SciPy**: For scientific computing and technical computing
- **Matplotlib**: For creating visualizations
- **scikit-learn**: For machine learning
- **SymPy**: For symbolic mathematics

These packages can be imported directly without installation, making it easier to perform common data science tasks.

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

### Configuration File Structure

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
  installer: uv  # or pip
  index_url: null  # Set to your PyPI mirror if needed
  trusted_hosts: []  # List of trusted hosts for pip/uv

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

### Docker Configuration Options

| Option | Description | Default |
|--------|-------------|---------|
| `image` | Docker image to use for execution | `python:3.12.2-slim` |
| `working_dir` | Working directory inside container | `/app` |
| `memory_limit` | Memory limit for container | `256m` |
| `cpu_limit` | CPU limit (0.0-1.0) | `0.5` |
| `timeout` | Execution timeout in seconds | `30` |
| `network_disabled` | Disable network access | `true` |
| `read_only` | Run container in read-only mode | `true` |

### Container Pooling Options

The server supports container pooling to improve performance by reusing containers. These settings can be configured via environment variables:

| Environment Variable | Description | Default |
|---------------------|-------------|---------|
| `PYTHON_DOCKER_MCP_POOL_ENABLED` | Enable container pooling | `true` |
| `PYTHON_DOCKER_MCP_POOL_SIZE` | Maximum number of containers in the pool | `32` |
| `PYTHON_DOCKER_MCP_POOL_MAX_AGE` | Maximum container lifetime in seconds | `300` |
| `PYTHON_DOCKER_MCP_MAX_CONCURRENT_CREATIONS` | Maximum number of containers that can be created simultaneously | `5` |
| `PYTHON_DOCKER_MCP_MEMORY_LIMIT` | Memory limit for each container | `256m` |
| `PYTHON_DOCKER_MCP_CPU_LIMIT` | CPU limit for each container (0.0-1.0) | `0.5` |

### Package Installation Options

| Option | Description | Default |
|--------|-------------|---------|
| `installer` | Package installer to use (`uv` or `pip`) | `uv` |
| `index_url` | Custom PyPI index URL | `null` |
| `trusted_hosts` | Trusted hosts for package installation | `[]` |

## Integration with Claude and Anthropic Products

### Claude Desktop

On MacOS: `~/Library/Application\ Support/Claude/claude_desktop_config.json`
On Windows: `%APPDATA%/Claude/claude_desktop_config.json`

<details>
  <summary>Development/Unpublished Servers Configuration</summary>

  ```json
  "mcpServers": {
    "python-docker-mcp": {
      "command": "uv",
      "args": [
        "--directory",
        "/path/to/python-docker-mcp",
        "run",
        "python-docker-mcp"
      ]
    }
  }
  ```
</details>

<details>
  <summary>Published Servers Configuration</summary>

  ```json
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

## Example MCP Usage

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

## Development

### Development Setup

1. Clone the repository:
```bash
git clone https://github.com/artivus/python-docker-mcp.git
cd python-docker-mcp
```

2. Set up development environment:
```bash
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
uv pip install -e ".[dev]"
```

3. Install pre-commit hooks:
```bash
pre-commit install
```

### Running Tests

```bash
# Run all tests
pytest

# Run tests with coverage
pytest --cov=src/python_docker_mcp

# Run specific test categories
pytest tests/unit/
pytest tests/integration/
```

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

## License

[License information]

## Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.
