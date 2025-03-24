FROM python:3.12.2-slim

# Install uv for package management
RUN pip install uv

# Set up working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install commonly used packages globally
RUN uv pip install --system numpy pandas scipy matplotlib scikit-learn sympy

# Set Python to not write bytecode and to flush stdout/stderr immediately
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Create non-root user for security
RUN useradd -m -u 1000 appuser

# Create a virtual environment for package installations
RUN mkdir -p /home/appuser/.venv && \
    chown -R appuser:appuser /home/appuser/.venv && \
    python -m venv /home/appuser/.venv && \
    chown -R appuser:appuser /home/appuser/.venv

# Give appuser write permissions to the /app directory
RUN mkdir -p /app && chown -R appuser:appuser /app

# Switch to appuser
USER appuser

# Set up the virtual environment in the user's PATH
ENV PATH="/home/appuser/.venv/bin:$PATH" \
    VIRTUAL_ENV="/home/appuser/.venv"

# Default command (will be overridden when running the container)
CMD ["python", "-c", "import time; time.sleep(86400)"]
