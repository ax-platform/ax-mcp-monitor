#!/usr/bin/env python3
"""
Universal MCP Test Client - A multi-purpose client for any MCP server.

This client can:
- Discover available tools dynamically
- Generate test cases automatically
- Support both OAuth and API key authentication
- Provide an interactive REPL for testing
"""

import os
import sys
import json
import asyncio
import argparse
from typing import Optional, Dict, Any, List
from datetime import datetime
import readline  # For better REPL experience

from ax_mcp_wait_client.simple_mcp_client import SimpleMCPClient, SimpleMCPClientWithRefresh
from ax_mcp_wait_client.mcp_remote_wrapper import MCPRemoteWrapper


class UniversalMCPClient:
    """
    Universal client that can work with any MCP server.
    
    Features:
    - Dynamic tool discovery
    - Automatic test generation
    - Interactive REPL mode
    - Support for multiple auth methods
    """
    
    def __init__(self, client: SimpleMCPClient):
        """
        Initialize with an MCP client instance.
        
        Args:
            client: SimpleMCPClient or SimpleMCPClientWithRefresh instance
        """
        self.client = client
        self.tools: List[Dict] = []
        self.prompts: List[Dict] = []
        self.resources: List[Dict] = []
        self._tool_map: Dict[str, Dict] = {}
        
    async def discover(self) -> Dict[str, Any]:
        """
        Discover all capabilities of the MCP server.
        
        Returns:
            Dictionary with tools, prompts, and resources
        """
        print("🔍 Discovering server capabilities...")
        
        # Initialize session
        server_info = await self.client.initialize()
        print(f"✅ Connected to: {server_info.get('serverInfo', {}).get('name', 'Unknown')}")
        print(f"   Version: {server_info.get('serverInfo', {}).get('version', 'Unknown')}")
        
        # Discover tools
        self.tools = await self.client.list_tools()
        self._tool_map = {tool['name']: tool for tool in self.tools}
        print(f"📦 Found {len(self.tools)} tools")
        
        # Discover prompts
        try:
            self.prompts = await self.client.list_prompts()
            print(f"💬 Found {len(self.prompts)} prompts")
        except Exception:
            print("💬 Prompts not supported")
        
        # Discover resources
        try:
            self.resources = await self.client.list_resources()
            print(f"📁 Found {len(self.resources)} resources")
        except Exception:
            print("📁 Resources not supported")
        
        return {
            "server": server_info,
            "tools": self.tools,
            "prompts": self.prompts,
            "resources": self.resources
        }
    
    def list_tools(self, verbose: bool = False):
        """
        List all available tools.
        
        Args:
            verbose: Show detailed information
        """
        if not self.tools:
            print("No tools discovered. Run discover() first.")
            return
        
        print("\n🔧 Available Tools:")
        print("-" * 60)
        
        for tool in self.tools:
            print(f"  • {tool['name']}")
            if tool.get('description'):
                print(f"    {tool['description']}")
            
            if verbose and tool.get('inputSchema'):
                schema = tool['inputSchema']
                if schema.get('properties'):
                    print("    Parameters:")
                    for name, prop in schema['properties'].items():
                        required = name in schema.get('required', [])
                        req_mark = "*" if required else ""
                        desc = prop.get('description', '')
                        type_str = prop.get('type', 'any')
                        print(f"      - {name}{req_mark} ({type_str}): {desc}")
            print()
    
    async def call_tool(self, tool_name: str, args: Optional[Dict] = None) -> Any:
        """
        Call a tool with arguments.
        
        Args:
            tool_name: Name of the tool
            args: Tool arguments
            
        Returns:
            Tool result
        """
        if tool_name not in self._tool_map:
            print(f"❌ Unknown tool: {tool_name}")
            print(f"Available tools: {', '.join(self._tool_map.keys())}")
            return None
        
        try:
            result = await self.client.call_tool(tool_name, args or {})
            return result
        except Exception as e:
            print(f"❌ Error calling {tool_name}: {e}")
            return None
    
    async def generate_tests(self, output_file: Optional[str] = None):
        """
        Generate test cases for all discovered tools.
        
        Args:
            output_file: Optional file to save tests
        """
        print("\n🧪 Generating test cases...")
        
        tests = []
        for tool in self.tools:
            test = self._generate_tool_test(tool)
            tests.append(test)
            
        # Format as Python test file
        test_code = self._format_test_file(tests)
        
        if output_file:
            with open(output_file, 'w') as f:
                f.write(test_code)
            print(f"✅ Tests saved to {output_file}")
        else:
            print("\n" + test_code)
        
        return test_code
    
    def _generate_tool_test(self, tool: Dict) -> Dict:
        """Generate a test case for a tool."""
        # Generate sample arguments based on schema
        args = {}
        if tool.get('inputSchema', {}).get('properties'):
            for name, prop in tool['inputSchema']['properties'].items():
                # Generate sample value based on type
                prop_type = prop.get('type', 'string')
                if prop_type == 'string':
                    args[name] = f"test_{name}"
                elif prop_type == 'number':
                    args[name] = 42
                elif prop_type == 'boolean':
                    args[name] = True
                elif prop_type == 'array':
                    args[name] = []
                elif prop_type == 'object':
                    args[name] = {}
        
        return {
            "name": tool['name'],
            "description": tool.get('description', ''),
            "args": args
        }
    
    def _format_test_file(self, tests: List[Dict]) -> str:
        """Format tests as a Python test file."""
        lines = [
            "#!/usr/bin/env python3",
            '"""',
            "Auto-generated MCP tool tests.",
            f"Generated: {datetime.now().isoformat()}",
            '"""',
            "",
            "import asyncio",
            "import pytest",
            "from ax_mcp_wait_client.universal_client import create_client",
            "",
            "",
            "class TestMCPTools:",
            ""
        ]
        
        for test in tests:
            lines.extend([
                f"    async def test_{test['name']}(self, client):",
                f'        """Test {test["name"]} tool."""',
                f"        result = await client.call_tool(",
                f'            "{test["name"]}",',
                f"            {json.dumps(test['args'], indent=12)}",
                "        )",
                "        assert result is not None",
                ""
            ])
        
        return "\n".join(lines)
    
    async def interactive_repl(self):
        """
        Start an interactive REPL for testing tools.
        """
        print("\n🎮 Interactive MCP REPL")
        print("Commands:")
        print("  tools [verbose]  - List available tools")
        print("  call <tool> [args] - Call a tool (args as JSON)")
        print("  discover - Rediscover server capabilities")
        print("  tests - Generate test cases")
        print("  help - Show this help")
        print("  exit - Exit REPL")
        print("-" * 60)
        
        while True:
            try:
                command = input("\nmcp> ").strip()
                if not command:
                    continue
                
                parts = command.split(None, 1)
                cmd = parts[0].lower()
                
                if cmd == "exit":
                    print("Goodbye!")
                    break
                
                elif cmd == "help":
                    await self.interactive_repl.__wrapped__(self)  # Show help again
                    
                elif cmd == "tools":
                    verbose = len(parts) > 1 and parts[1] == "verbose"
                    self.list_tools(verbose)
                
                elif cmd == "discover":
                    await self.discover()
                
                elif cmd == "tests":
                    await self.generate_tests()
                
                elif cmd == "call":
                    if len(parts) < 2:
                        print("Usage: call <tool> [args]")
                        continue
                    
                    # Parse tool name and optional args
                    tool_parts = parts[1].split(None, 1)
                    tool_name = tool_parts[0]
                    
                    args = {}
                    if len(tool_parts) > 1:
                        try:
                            args = json.loads(tool_parts[1])
                        except json.JSONDecodeError:
                            print("❌ Invalid JSON arguments")
                            continue
                    
                    result = await self.call_tool(tool_name, args)
                    if result is not None:
                        print("Result:")
                        if isinstance(result, str):
                            print(result)
                        else:
                            print(json.dumps(result, indent=2))
                
                else:
                    print(f"Unknown command: {cmd}")
                    print("Type 'help' for available commands")
                    
            except KeyboardInterrupt:
                print("\nUse 'exit' to quit")
            except Exception as e:
                print(f"Error: {e}")


async def create_client(
    server_url: str,
    auth_type: str = "oauth",
    token: Optional[str] = None,
    token_dir: Optional[str] = None,
    agent_name: str = "universal_mcp_client"
) -> UniversalMCPClient:
    """
    Create a UniversalMCPClient with appropriate authentication.
    
    Args:
        server_url: MCP server URL
        auth_type: "oauth", "bearer", or "none"
        token: Bearer token or API key (for auth_type="bearer")
        token_dir: Token directory (for auth_type="oauth")
        agent_name: Client identifier
        
    Returns:
        Configured UniversalMCPClient instance
    """
    if auth_type == "oauth":
        if not token_dir:
            token_dir = os.getenv("MCP_REMOTE_CONFIG_DIR", "~/.mcp-auth")
        
        wrapper = MCPRemoteWrapper(
            server_url=server_url,
            token_dir=token_dir,
            agent_name=agent_name
        )
        
        if not await wrapper.ensure_authenticated():
            raise Exception("OAuth authentication failed")
        
        client = SimpleMCPClientWithRefresh(
            server_url=server_url,
            token_manager=wrapper,
            agent_name=agent_name
        )
    
    elif auth_type == "bearer":
        client = SimpleMCPClient(
            server_url=server_url,
            access_token=token,
            agent_name=agent_name
        )
    
    else:  # auth_type == "none"
        client = SimpleMCPClient(
            server_url=server_url,
            access_token=None,
            agent_name=agent_name
        )
    
    return UniversalMCPClient(client)


async def main():
    """Main entry point for the universal client."""
    parser = argparse.ArgumentParser(
        description="Universal MCP Client - Test any MCP server"
    )
    parser.add_argument(
        "server_url",
        help="MCP server URL (e.g., http://localhost:8001/mcp)"
    )
    parser.add_argument(
        "--auth",
        choices=["oauth", "bearer", "none"],
        default="oauth",
        help="Authentication type (default: oauth)"
    )
    parser.add_argument(
        "--token",
        help="Bearer token or API key (for --auth bearer)"
    )
    parser.add_argument(
        "--token-dir",
        help="Token directory for OAuth (default: MCP_REMOTE_CONFIG_DIR)"
    )
    parser.add_argument(
        "--agent-name",
        default="universal_mcp_client",
        help="Client identifier"
    )
    parser.add_argument(
        "--discover",
        action="store_true",
        help="Discover and list server capabilities"
    )
    parser.add_argument(
        "--generate-tests",
        metavar="FILE",
        help="Generate test file for all tools"
    )
    parser.add_argument(
        "--call",
        metavar="TOOL",
        help="Call a specific tool"
    )
    parser.add_argument(
        "--args",
        help="Tool arguments as JSON string"
    )
    parser.add_argument(
        "--repl",
        action="store_true",
        help="Start interactive REPL"
    )
    
    args = parser.parse_args()
    
    # Create client
    universal_client = await create_client(
        server_url=args.server_url,
        auth_type=args.auth,
        token=args.token,
        token_dir=args.token_dir,
        agent_name=args.agent_name
    )
    
    # Discover capabilities
    if args.discover or args.repl or args.generate_tests:
        await universal_client.discover()
    
    # Execute requested action
    if args.discover:
        universal_client.list_tools(verbose=True)
    
    elif args.generate_tests:
        await universal_client.generate_tests(args.generate_tests)
    
    elif args.call:
        tool_args = {}
        if args.args:
            try:
                tool_args = json.loads(args.args)
            except json.JSONDecodeError:
                print(f"❌ Invalid JSON arguments: {args.args}")
                return 1
        
        result = await universal_client.call_tool(args.call, tool_args)
        if result is not None:
            if isinstance(result, str):
                print(result)
            else:
                print(json.dumps(result, indent=2))
    
    elif args.repl:
        await universal_client.interactive_repl()
    
    else:
        # Default: show discovered capabilities
        await universal_client.discover()
        universal_client.list_tools()
    
    # Clean up
    await universal_client.client.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))