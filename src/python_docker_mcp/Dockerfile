FROM python:3.12.2-slim

# Install uv for package management
RUN pip install uv

# Set up working directory
WORKDIR /app

# Install commonly used packages
RUN uv pip install numpy pandas matplotlib scikit-learn sympy

# Install additional tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Set Python to not write bytecode and to flush stdout/stderr immediately
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Create non-root user for security
RUN useradd -m -u 1000 appuser
USER appuser

# Default command (will be overridden when running the container)
CMD ["python", "-c", "import time; time.sleep(86400)"] 