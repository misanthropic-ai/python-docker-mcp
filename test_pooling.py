#!/usr/bin/env python
"""Test script to verify container pooling functionality."""

import asyncio
import json
import logging
import time

from python_docker_mcp.config import load_config
from python_docker_mcp.docker_manager import DockerManager

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("test_pooling")

# Add more detailed logging for the docker_manager module
docker_logger = logging.getLogger("python_docker_mcp.docker_manager")
docker_logger.setLevel(logging.DEBUG)


async def main():
    """Run container pool tests."""
    # Load configuration
    config = load_config()

    # Check original pool configuration
    logger.info(f"Original pool enabled in config: {getattr(config.docker, 'pool_enabled', False)}")
    logger.info(f"Original pool size in config: {getattr(config.docker, 'pool_size', 0)}")

    # Override with a smaller pool size for better testing
    config.docker.pool_enabled = True
    config.docker.pool_size = 3  # Even smaller for easier testing
    logger.info(f"Testing with pool size: {config.docker.pool_size}")

    # Initialize the docker manager
    docker_manager = DockerManager(config)

    # Initialize the pool
    logger.info("Initializing container pool...")
    await docker_manager.initialize_pool()

    # Get the status of the pool
    async with docker_manager.pool_lock:
        pool_size = len(docker_manager.container_pool)
        logger.info(f"Initial pool size: {pool_size}")
        logger.info(f"Initial containers in pool: {[c[:12] for c in docker_manager.container_pool]}")
        logger.info(f"Initial container timestamps: {docker_manager.container_creation_timestamps}")

    # Configure a simple test code
    test_code = """
print("Container test")
"""

    # First test: Execute multiple transient code runs
    logger.info("========== TEST 1: MULTIPLE TRANSIENT EXECUTIONS ==========")

    # Run more executions than the pool size to force recycling
    executions = 5

    for i in range(executions):
        logger.info(f"Execution {i+1}/{executions}")
        result = await docker_manager.execute_transient(test_code)
        logger.info(f"Execution status: {result['status']}")
        logger.info(f"In-use containers: {[c[:12] for c in docker_manager.in_use_containers]}")

        # Check pool state after each execution
        async with docker_manager.pool_lock:
            current_pool = list(docker_manager.container_pool)
            logger.info(f"Pool after execution {i+1}: {len(current_pool)} containers")
            logger.info(f"Current pool: {[c[:12] for c in current_pool]}")

        # Wait a moment for container to be returned to pool
        await asyncio.sleep(1)

    # Check pool state after all transient executions
    async with docker_manager.pool_lock:
        logger.info(f"Pool after transient executions: {len(docker_manager.container_pool)} containers")
        logger.info(f"Pool containers: {[c[:12] for c in docker_manager.container_pool]}")
        logger.info(f"Container timestamps: {docker_manager.container_creation_timestamps}")

    # Second test: Recreate manager to reset pool state, then create multiple persistent sessions
    logger.info("========== TEST 2: MULTIPLE PERSISTENT SESSIONS ==========")

    # Create a new manager to reset pool state
    docker_manager = DockerManager(config)
    await docker_manager.initialize_pool()

    # Save initial pool state
    async with docker_manager.pool_lock:
        initial_pool = list(docker_manager.container_pool)
        logger.info(f"Initial pool size: {len(initial_pool)}")
        logger.info(f"Initial pool containers: {[c[:12] for c in initial_pool]}")

    # Create some persistent sessions (more than pool size)
    sessions = 5
    session_ids = [f"test-session-{i}" for i in range(sessions)]

    for i, session_id in enumerate(session_ids):
        logger.info(f"Creating persistent session {i+1}/{sessions} with ID {session_id}")
        result = await docker_manager.execute_persistent(session_id, test_code)
        logger.info(f"Session {session_id} status: {result['status']}")

        # Check persistent containers
        logger.info(f"Persistent containers: {len(docker_manager.persistent_containers)}")
        logger.info(f"Persistent container IDs: {[cid[:12] for cid in docker_manager.persistent_containers.values()]}")

        # Check pool state
        async with docker_manager.pool_lock:
            logger.info(f"Pool size: {len(docker_manager.container_pool)}")
            logger.info(f"Pool containers: {[c[:12] for c in docker_manager.container_pool]}")

    # Check final state
    logger.info("========== FINAL STATE ==========")
    logger.info(f"Persistent containers: {len(docker_manager.persistent_containers)}")
    logger.info(f"Pool size: {len(docker_manager.container_pool)}")

    # Clean up sessions
    for session_id in session_ids:
        logger.info(f"Cleaning up session {session_id}")
        await docker_manager.cleanup_session(session_id)

    # Final pool state
    async with docker_manager.pool_lock:
        logger.info(f"Final pool size: {len(docker_manager.container_pool)}")
        logger.info(f"Final pool containers: {[c[:12] for c in docker_manager.container_pool]}")

    logger.info("Test completed successfully!")


if __name__ == "__main__":
    asyncio.run(main())
