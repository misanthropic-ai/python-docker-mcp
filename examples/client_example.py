#!/usr/bin/env python3
"""
Example script demonstrating how to use the Python Docker MCP client.

This example demonstrates:
1. Connecting to the server
2. Listing available tools
3. Executing code in transient containers
4. Working with persistent containers
5. Installing packages
6. Proper cleanup

Usage:
    python client_example.py
"""

import asyncio
import os
import sys

# Add the parent directory to the Python path to import the module
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from python_docker_mcp.client import PythonDockerClient


async def run_transient_example(client):
    """Run examples using transient containers."""
    print("\n=== Transient Container Examples ===")
    
    # Simple hello world
    print("\nRunning simple Hello World:")
    result = await client.execute_transient("print('Hello from Docker container!')")
    print(f"Output: {result['output']}")
    
    # Example with error handling
    print("\nRunning code with error:")
    result = await client.execute_transient("print(undefined_variable)")
    if result["error"]:
        print(f"Error caught: {result['error']}")
    
    # Example with state
    print("\nRunning code with state:")
    state = {"value": 42, "message": "Hello from state"}
    result = await client.execute_transient(
        "print(f'Value: {state[\"value\"]}, Message: {state[\"message\"]}')",
        state
    )
    print(f"Output: {result['output']}")


async def run_persistent_example(client):
    """Run examples using persistent containers."""
    print("\n=== Persistent Container Examples ===")
    
    # Start a new session
    print("\nStarting a new persistent session:")
    code = "x = 10\nprint(f'Initialized x with value: {x}')"
    result, session_id = await client.execute_persistent(code)
    print(f"Session ID: {session_id}")
    print(f"Output: {result['output']}")
    
    # Continue the session
    print("\nContinuing with the same session:")
    code = "x += 5\nprint(f'Updated x to: {x}')"
    result, session_id = await client.execute_persistent(code, session_id)
    print(f"Output: {result['output']}")
    
    # Install a package
    print("\nInstalling a package in the persistent session:")
    result = await client.install_package("numpy", session_id)
    if result["success"]:
        print(f"Successfully installed {result['package_name']}")
    
    # Use the installed package
    print("\nUsing the installed package:")
    code = """
import numpy as np
arr = np.array([1, 2, 3, 4, 5])
print(f'NumPy array: {arr}')
print(f'Mean: {np.mean(arr)}')
"""
    result, session_id = await client.execute_persistent(code, session_id)
    print(f"Output: {result['output']}")
    
    # Clean up the session
    print("\nCleaning up the session:")
    success = await client.cleanup_session(session_id)
    if success:
        print(f"Session {session_id} cleaned up successfully")


async def main():
    """Run the main example."""
    # Initialize the client
    client = PythonDockerClient()
    
    try:
        # Connect to the server
        print("Connecting to MCP server...")
        
        # If you have a custom server script, you can specify it here:
        # await client.connect_to_server("/path/to/server.py")
        
        # Or use the default server
        await client.connect_to_server()
        print("Connected successfully!")
        
        # List available tools
        print("\nListing available tools:")
        tools = await client.list_tools()
        for tool in tools:
            print(f"- {tool['name']}: {tool['description']}")
        
        # Run examples
        await run_transient_example(client)
        await run_persistent_example(client)
        
    except Exception as e:
        print(f"Error: {e}")
    finally:
        # Always close the connection
        if client.session:
            print("\nClosing connection to server...")
            await client.close()
            print("Connection closed.")


if __name__ == "__main__":
    asyncio.run(main()) 