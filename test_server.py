#!/usr/bin/env python3
"""
Manual server test script for python-docker-mcp.

This script starts the MCP server in a subprocess and sends basic commands
to verify its functionality independently of the client.
"""

import asyncio
import json
import os
import subprocess
import sys
import time
from typing import Dict, Any, Optional

SERVER_MODULE = "python_docker_mcp"

def create_jsonrpc_request(method: str, params: Dict[str, Any], request_id: int = 1) -> str:
    """Create a JSONRPC request string."""
    request = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": params
    }
    return json.dumps(request) + "\n"

async def test_server():
    """Test the server by sending direct JSONRPC requests."""
    print("=== Starting python-docker-mcp server test ===")
    
    # Start the server subprocess
    server_env = os.environ.copy()
    
    # Ensure PYTHONPATH includes the current directory
    python_path = os.environ.get("PYTHONPATH", "")
    server_env["PYTHONPATH"] = f"{os.path.abspath('.')}:{python_path}"
    
    server_cmd = [sys.executable, "-m", SERVER_MODULE]
    
    print(f"Starting server with command: {' '.join(server_cmd)}")
    
    proc = subprocess.Popen(
        server_cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=server_env,
        bufsize=0,
    )
    
    # Allow the server to start up
    time.sleep(0.5)
    
    try:
        # Initialize connection
        print("\nSending initialize request...")
        init_request = create_jsonrpc_request(
            "initialize", 
            {
                "protocolVersion": "2.0",
                "clientInfo": {
                    "name": "manual-test",
                    "version": "1.0.0"
                },
                "capabilities": {
                    "tools": True
                }
            }
        )
        proc.stdin.write(init_request.encode())
        proc.stdin.flush()
        
        # Read response
        init_response = proc.stdout.readline().decode()
        print(f"Initialize response: {init_response}")
        
        # List tools
        print("\nSending list_tools request...")
        list_tools_request = create_jsonrpc_request(
            "list_tools",
            {}
        )
        proc.stdin.write(list_tools_request.encode())
        proc.stdin.flush()
        
        # Read response
        list_tools_response = proc.stdout.readline().decode()
        print(f"List tools response: {list_tools_response}")
        
        # Execute transient code
        print("\nSending execute-transient request...")
        code = "print('Hello from manual server test!')\nx = 42\nprint(f'x = {x}')"
        execute_request = create_jsonrpc_request(
            "tool/execute-transient",
            {"code": code}
        )
        proc.stdin.write(execute_request.encode())
        proc.stdin.flush()
        
        # Read response
        execute_response = proc.stdout.readline().decode()
        print(f"Execute response: {execute_response}")
        
        # Execute persistent code
        print("\nSending execute-persistent request...")
        code = "y = 84\nprint(f'y = {y}')"
        persistent_request = create_jsonrpc_request(
            "tool/execute-persistent",
            {"code": code}
        )
        proc.stdin.write(persistent_request.encode())
        proc.stdin.flush()
        
        # Read response
        persistent_response = proc.stdout.readline().decode()
        print(f"Persistent execute response: {persistent_response}")
        
        # Extract session ID
        try:
            response_obj = json.loads(persistent_response)
            content = response_obj.get("result", {}).get("content", [{}])[0]
            text = content.get("text", "")
            
            import re
            session_match = re.search(r"Session ID: ([a-f0-9-]+)", text)
            if session_match:
                session_id = session_match.group(1)
                print(f"Extracted session ID: {session_id}")
                
                # Clean up session
                print("\nSending cleanup-session request...")
                cleanup_request = create_jsonrpc_request(
                    "tool/cleanup-session",
                    {"session_id": session_id}
                )
                proc.stdin.write(cleanup_request.encode())
                proc.stdin.flush()
                
                # Read response
                cleanup_response = proc.stdout.readline().decode()
                print(f"Cleanup response: {cleanup_response}")
        except (json.JSONDecodeError, KeyError, AttributeError) as e:
            print(f"Error extracting session ID: {e}")
        
        print("\n=== Server test completed ===")
    
    finally:
        # Clean up
        print("\nShutting down server...")
        proc.terminate()
        return_code = proc.wait()
        print(f"Server shutdown with exit code: {return_code}")
        
        # Check stderr for any errors
        stderr = proc.stderr.read().decode()
        if stderr.strip():
            print(f"\nServer stderr output: {stderr}")

if __name__ == "__main__":
    asyncio.run(test_server()) 