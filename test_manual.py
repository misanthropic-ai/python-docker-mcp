#!/usr/bin/env python3
"""
Manual test script for python-docker-mcp server and client.

This script provides basic tests to verify functionality of the python-docker-mcp
server and client without relying on the automated test suite.
"""

import asyncio
import os
import sys
import time
from typing import Dict, Any, Optional

from python_docker_mcp.client import PythonDockerClient


async def test_transient_execution(client: PythonDockerClient) -> None:
    """Test basic execution in a transient container."""
    print("\n=== Testing Transient Execution ===")
    
    # Simple calculation
    code = """
print("Hello from transient container!")
x = 40 + 2
print(f"The answer is {x}")
result = x
"""
    
    print("Executing code...")
    result = await client.execute_transient(code)
    
    print(f"Raw output:\n{result['raw_output']}")
    print(f"Error: {result['error']}")
    if 'output' in result:
        print(f"Parsed output: {result['output']}")


async def test_persistent_execution(client: PythonDockerClient) -> None:
    """Test execution in a persistent container with state preservation."""
    print("\n=== Testing Persistent Execution ===")
    
    # First code execution - define variables
    code1 = """
print("Setting up variables in persistent container")
counter = 0
message = "Hello, persistent world!"
print(f"Initial message: {message}")
print(f"Initial counter: {counter}")
"""
    
    print("Executing first code block...")
    result1, session_id = await client.execute_persistent(code1)
    
    print(f"Session ID: {session_id}")
    print(f"Result:\n{result1['raw_output']}")
    
    # Second code execution - use existing variables
    code2 = """
print("Accessing previously defined variables...")
counter += 1
message += " (updated)"
print(f"Updated message: {message}")
print(f"Updated counter: {counter}")
"""
    
    print("\nExecuting second code block using same session...")
    result2, session_id = await client.execute_persistent(code2, session_id)
    
    print(f"Result:\n{result2['raw_output']}")
    
    # Clean up the session
    print("\nCleaning up session...")
    success = await client.cleanup_session(session_id)
    print(f"Cleanup successful: {success}")


async def test_package_installation(client: PythonDockerClient) -> None:
    """Test package installation and usage."""
    print("\n=== Testing Package Installation ===")
    
    # Create a persistent session
    code1 = 'print("Creating session for package installation")'
    result1, session_id = await client.execute_persistent(code1)
    print(f"Session ID: {session_id}")
    
    # Install a package
    print("\nInstalling numpy package...")
    install_result = await client.install_package("numpy", session_id)
    print(f"Installation success: {install_result['success']}")
    print(f"Installation output: {install_result['raw_output']}")
    
    # Use the installed package
    code2 = """
import numpy as np
arr = np.array([1, 2, 3, 4, 5])
print(f"NumPy array: {arr}")
print(f"Mean: {np.mean(arr)}")
print(f"Sum: {np.sum(arr)}")
"""
    
    print("\nTesting numpy package usage...")
    result2, _ = await client.execute_persistent(code2, session_id)
    print(f"Result:\n{result2['raw_output']}")
    
    # Clean up the session
    print("\nCleaning up session...")
    success = await client.cleanup_session(session_id)
    print(f"Cleanup successful: {success}")


async def test_error_handling(client: PythonDockerClient) -> None:
    """Test error handling in code execution."""
    print("\n=== Testing Error Handling ===")
    
    # Code with a syntax error
    code1 = """
print("This line is correct")
if True
    print("This line has a syntax error")
"""
    
    print("Testing syntax error handling...")
    result1 = await client.execute_transient(code1)
    print(f"Error detected: {result1['error'] is not None}")
    print(f"Error message: {result1['error']}")
    print(f"Raw output:\n{result1['raw_output']}")
    
    # Code with a runtime error
    code2 = """
print("This line will execute")
x = 1 / 0  # Division by zero
print("This line will not execute")
"""
    
    print("\nTesting runtime error handling...")
    result2 = await client.execute_transient(code2)
    print(f"Error detected: {result2['error'] is not None}")
    print(f"Error message: {result2['error']}")
    print(f"Raw output:\n{result2['raw_output']}")


async def check_server_connection() -> None:
    """Check if server is running and accepting connections."""
    print("Checking server connection...")
    client = PythonDockerClient()
    
    try:
        await client.connect_to_server()
        print("✅ Successfully connected to server")
        
        tools = await client.list_tools()
        print(f"Available tools: {len(tools)}")
        for tool in tools:
            print(f"  - {tool['name']}: {tool['description']}")
        
        await client.close()
        return True
    except Exception as e:
        print(f"❌ Failed to connect to server: {e}")
        return False


async def main() -> None:
    """Run the manual tests."""
    print("=== Python Docker MCP Manual Tests ===")
    print(f"Current directory: {os.getcwd()}")
    
    # Check if server is running
    server_running = await check_server_connection()
    if not server_running:
        print("Aborting tests - server connection failed")
        return
    
    # Create client for tests
    client = PythonDockerClient()
    await client.connect_to_server()
    
    try:
        # Run tests
        await test_transient_execution(client)
        await test_persistent_execution(client)
        await test_package_installation(client)
        await test_error_handling(client)
        
        print("\n=== All manual tests completed ===")
    finally:
        # Clean up
        await client.close()


if __name__ == "__main__":
    asyncio.run(main()) 