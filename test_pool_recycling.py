#!/usr/bin/env python
"""Test script to verify container pool recycling functionality."""

import asyncio
import json
import logging
import time

from python_docker_mcp.config import load_config
from python_docker_mcp.docker_manager import DockerManager

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("test_pool_recycling")

# Set docker manager logger to DEBUG level
docker_logger = logging.getLogger("python_docker_mcp.docker_manager")
docker_logger.setLevel(logging.DEBUG)


async def main():
    """Run container pool recycling tests."""
    # Load configuration
    config = load_config()

    # Configure a small pool size for testing
    config.docker.pool_enabled = True
    config.docker.pool_size = 3
    logger.info(f"Testing with pool size: {config.docker.pool_size}")

    # Initialize the docker manager
    docker_manager = DockerManager(config)

    # Check the default pool_max_age setting
    logger.info(f"Pool maximum age: {docker_manager.pool_max_age} seconds")

    # Initialize the pool
    logger.info("Initializing container pool...")
    await docker_manager.initialize_pool()

    # Get the initial pool state
    async with docker_manager.pool_lock:
        initial_pool_containers = list(docker_manager.container_pool)
        logger.info(f"Initial pool size: {len(initial_pool_containers)}")
        logger.info(f"Initial pool containers: {[c[:12] for c in initial_pool_containers]}")

        # Manually set different timestamps for containers to create age differences
        # but keep them all within the pool_max_age to avoid auto-cleanup
        for i, container_id in enumerate(initial_pool_containers):
            # Set timestamps with small increasing age differences (10, 20, 30 seconds ago)
            age_seconds = 10 * (i + 1)
            timestamp = time.time() - age_seconds
            docker_manager.container_creation_timestamps[container_id] = timestamp
            logger.info(f"Setting container {container_id[:12]} timestamp to {timestamp} (age: {age_seconds} seconds)")

        logger.info(f"Modified timestamps: {docker_manager.container_creation_timestamps}")

    # Now execute a few operations to force a new container to be created and returned to the pool
    logger.info("Creating new containers that should replace the oldest ones in the pool...")

    # Configure a simple test code
    test_code = """
print("Testing container pool recycling")
"""

    # Execute multiple operations to ensure we get more containers than the pool size
    executions = docker_manager.pool_size + 2

    for i in range(executions):
        logger.info(f"Execution {i+1}/{executions}")
        result = await docker_manager.execute_transient(test_code)
        logger.info(f"Execution {i+1} status: {result['status']}")

        # Check pool state after each execution
        async with docker_manager.pool_lock:
            current_pool = list(docker_manager.container_pool)
            logger.info(f"Pool after execution {i+1}: {len(current_pool)} containers")
            logger.info(f"Current pool: {[c[:12] for c in current_pool]}")

        # Wait for the container to be returned to the pool
        await asyncio.sleep(1)

    # Check the final pool state
    async with docker_manager.pool_lock:
        final_pool_containers = list(docker_manager.container_pool)
        logger.info(f"Final pool size: {len(final_pool_containers)}")
        logger.info(f"Final pool containers: {[c[:12] for c in final_pool_containers]}")
        logger.info(f"Final timestamps: {docker_manager.container_creation_timestamps}")

        # Verify that the oldest container was removed
        oldest_container = initial_pool_containers[0]  # First one we set with the oldest timestamp
        if oldest_container not in final_pool_containers:
            logger.info(f"✅ SUCCESS: Oldest container {oldest_container[:12]} was correctly removed from pool")
        else:
            logger.error(f"❌ FAILURE: Oldest container {oldest_container[:12]} is still in the pool!")

        # Check how many of the original containers were replaced
        remaining_original = [c for c in initial_pool_containers if c in final_pool_containers]
        replaced_original = [c for c in initial_pool_containers if c not in final_pool_containers]

        logger.info(f"Original containers remaining in pool: {len(remaining_original)}/{len(initial_pool_containers)}")
        logger.info(f"Original containers replaced: {len(replaced_original)}/{len(initial_pool_containers)}")

        if replaced_original:
            logger.info(f"Replaced containers: {[c[:12] for c in replaced_original]}")

        # Verify new containers were added
        new_containers = [c for c in final_pool_containers if c not in initial_pool_containers]
        logger.info(f"New containers in pool: {len(new_containers)}")
        if new_containers:
            logger.info(f"New container IDs: {[c[:12] for c in new_containers]}")

    logger.info("Test completed successfully!")


if __name__ == "__main__":
    asyncio.run(main())
