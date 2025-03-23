#!/usr/bin/env python
# /// script
# dependencies = [
#   "python-docker-mcp",
# ]
# ///

"""
Simple test script for python-docker-mcp.

This script tests the core functionality of the python-docker-mcp package
by running a basic code sample through the Docker execution engine.
"""

import asyncio
import json
import os
import sys

# Add src directory to Python path
sys.path.insert(0, os.path.abspath("src"))

from python_docker_mcp.docker_manager import DockerManager

async def test_simple_code():
    """Run a simple Python code sample through DockerManager."""
    print("=== Testing simple code execution ===")
    
    # Create DockerManager instance
    docker_manager = DockerManager()
    
    # Simple test code
    test_code = """
print("Hello from docker-mcp!")
x = 42
y = 10
result = x + y
print(f"The answer is {result}")
"""
    
    print("\nExecuting code...")
    try:
        # Execute code in a transient container
        state = await docker_manager.execute_transient(test_code)
        
        # Print results
        print("\nExecution results:")
        print(f"Variables: x={state.get('x')}, y={state.get('y')}, result={state.get('result')}")
        print("\nStdout:")
        print(state.get('__stdout__', ''))
        
        if state.get('__stderr__'):
            print("\nStderr:")
            print(state.get('__stderr__'))
        
        if state.get('__error__'):
            print("\nError:")
            print(state.get('__error__'))
        
        print("\nFull state:")
        print(json.dumps({k: v for k, v in state.items() if not k.startswith('__')}, indent=2))
        
        print("\nExecution successful!")
        return True
    
    except Exception as e:
        print(f"\nError: {e}")
        return False

async def main():
    """Run the tests."""
    print("==== Python Docker MCP Simple Test ====")
    success = await test_simple_code()
    print("\n==== Test completed successfully! ====" if success else "\n==== Test failed! ====")

if __name__ == "__main__":
    asyncio.run(main()) 