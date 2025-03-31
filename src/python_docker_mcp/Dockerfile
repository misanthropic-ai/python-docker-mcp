FROM python:3.12.2-slim

# Set up working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install commonly used packages globally
RUN pip install --no-cache-dir numpy pandas scipy matplotlib scikit-learn sympy

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

# Create a script to fix permissions on mounted volumes
RUN echo '#!/bin/bash\n\
if [ -d "/app" ]; then\n\
    chown -R appuser:appuser /app\n\
    chmod -R 755 /app\n\
fi\n\
exec "$@"' > /usr/local/bin/docker-entrypoint.sh && \
    chmod +x /usr/local/bin/docker-entrypoint.sh

# Switch to appuser
USER appuser

# Set up the virtual environment in the user's PATH
ENV PATH="/home/appuser/.venv/bin:$PATH" \
    VIRTUAL_ENV="/home/appuser/.venv"

# Set the entrypoint
ENTRYPOINT ["docker-entrypoint.sh"]

# Default command (will be overridden when running the container)
CMD ["python", "-c", "import time; time.sleep(86400)"]
