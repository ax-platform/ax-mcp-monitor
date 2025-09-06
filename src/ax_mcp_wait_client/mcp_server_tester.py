#!/usr/bin/env python3
"""
MCP Server Testing Framework

A comprehensive testing tool for MCP servers that:
- Tests all available tools with different agents
- Validates authentication and authorization
- Measures performance and latency
- Generates test reports
"""

import os
import sys
import json
import time
import asyncio
import uuid
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from pathlib import Path

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from bearer_refresh import BearerTokenStore, MCPBearerAuth


@dataclass
class TestResult:
    """Result of a single test."""
    tool_name: str
    agent_name: str
    success: bool
    duration_ms: float
    error: Optional[str] = None
    response: Optional[Any] = None
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class TestSuite:
    """Collection of test results."""
    server_url: str
    results: List[TestResult] = field(default_factory=list)
    start_time: datetime = field(default_factory=datetime.now)
    end_time: Optional[datetime] = None
    
    def add_result(self, result: TestResult):
        """Add a test result."""
        self.results.append(result)
    
    def get_summary(self) -> Dict[str, Any]:
        """Get test summary statistics."""
        if not self.results:
            return {"total": 0, "passed": 0, "failed": 0}
        
        passed = sum(1 for r in self.results if r.success)
        failed = len(self.results) - passed
        avg_duration = sum(r.duration_ms for r in self.results) / len(self.results)
        
        # Group by tool
        by_tool = {}
        for r in self.results:
            if r.tool_name not in by_tool:
                by_tool[r.tool_name] = {"passed": 0, "failed": 0, "avg_ms": 0, "times": []}
            
            if r.success:
                by_tool[r.tool_name]["passed"] += 1
            else:
                by_tool[r.tool_name]["failed"] += 1
            by_tool[r.tool_name]["times"].append(r.duration_ms)
        
        # Calculate averages
        for tool in by_tool.values():
            if tool["times"]:
                tool["avg_ms"] = sum(tool["times"]) / len(tool["times"])
            del tool["times"]  # Remove raw times from summary
        
        return {
            "total": len(self.results),
            "passed": passed,
            "failed": failed,
            "success_rate": (passed / len(self.results)) * 100,
            "avg_duration_ms": avg_duration,
            "by_tool": by_tool,
            "duration_seconds": (self.end_time - self.start_time).total_seconds() if self.end_time else None
        }


class MCPServerTester:
    """
    Comprehensive MCP server testing framework.
    """
    
    def __init__(
        self,
        server_url: str = "http://localhost:8001/mcp",
        oauth_url: str = "http://localhost:8001",
        base_token_dir: str = "/Users/jacob/.mcp-auth/paxai/e2e38b9d"
    ):
        self.server_url = server_url
        self.oauth_url = oauth_url
        self.base_token_dir = Path(base_token_dir)
        self.available_agents = self._discover_agents()
        self.test_suite = TestSuite(server_url)
    
    def _discover_agents(self) -> Dict[str, Path]:
        """Discover all agents with valid tokens."""
        agents = {}
        
        if not self.base_token_dir.exists():
            return agents
        
        for agent_dir in self.base_token_dir.iterdir():
            if agent_dir.is_dir():
                # Look for mcp-remote tokens
                for mcp_dir in agent_dir.glob("mcp-remote-*"):
                    token_files = list(mcp_dir.glob("*_tokens.json"))
                    if token_files:
                        agents[agent_dir.name] = agent_dir
                        break
        
        return agents
    
    async def test_with_agent(
        self,
        agent_name: str,
        tools_to_test: Optional[List[str]] = None,
        verbose: bool = True
    ) -> List[TestResult]:
        """
        Run tests with a specific agent.
        
        Args:
            agent_name: Name of the agent to use
            tools_to_test: Specific tools to test (None = all)
            verbose: Print progress
            
        Returns:
            List of test results
        """
        if agent_name not in self.available_agents:
            raise ValueError(f"Agent '{agent_name}' not found. Available: {list(self.available_agents.keys())}")
        
        results = []
        token_dir = self.available_agents[agent_name]
        
        # Create bearer auth
        store = BearerTokenStore(str(token_dir))
        auth = MCPBearerAuth(store, self.oauth_url)
        
        # Set up headers with agent name
        headers = {
            "X-Agent-Name": agent_name,
            "X-Client-Instance": str(uuid.uuid4()),
            "X-Idempotency-Key": str(uuid.uuid4()),
        }
        
        if verbose:
            print(f"\n🧪 Testing with agent: {agent_name}")
            print("-" * 50)
        
        try:
            async with streamablehttp_client(
                url=self.server_url,
                headers=headers,
                auth=auth,
                timeout=timedelta(seconds=30),
            ) as (read, write, _):
                async with ClientSession(read, write) as session:
                    # Initialize session
                    await session.initialize()
                    
                    # Get available tools
                    tools = await session.list_tools()
                    
                    if verbose:
                        print(f"Found {len(tools)} tools")
                    
                    # Filter tools if specified
                    if tools_to_test:
                        tools = [t for t in tools if t.name in tools_to_test]
                    
                    # Test each tool
                    for tool in tools:
                        result = await self._test_tool(session, tool, agent_name, verbose)
                        results.append(result)
                        self.test_suite.add_result(result)
        
        except Exception as e:
            if verbose:
                print(f"❌ Session error: {e}")
            return results
        
        return results
    
    async def _test_tool(
        self,
        session: ClientSession,
        tool: Any,
        agent_name: str,
        verbose: bool
    ) -> TestResult:
        """Test a single tool."""
        tool_name = tool.name
        
        # Generate test arguments based on tool
        test_args = self._generate_test_args(tool_name)
        
        start_time = time.time()
        try:
            result = await session.call_tool(tool_name, test_args)
            duration_ms = (time.time() - start_time) * 1000
            
            # Validate response
            success = result is not None
            
            if verbose:
                status = "✅" if success else "⚠️"
                print(f"  {status} {tool_name}: {duration_ms:.1f}ms")
            
            return TestResult(
                tool_name=tool_name,
                agent_name=agent_name,
                success=success,
                duration_ms=duration_ms,
                response=result
            )
            
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            
            if verbose:
                print(f"  ❌ {tool_name}: {str(e)[:50]}")
            
            return TestResult(
                tool_name=tool_name,
                agent_name=agent_name,
                success=False,
                duration_ms=duration_ms,
                error=str(e)
            )
    
    def _generate_test_args(self, tool_name: str) -> Dict[str, Any]:
        """Generate appropriate test arguments for a tool."""
        # Tool-specific test arguments
        test_configs = {
            "messages": {
                "action": "check",
                "limit": 1,
                "mode": "latest"
            },
            "tasks": {
                "action": "list",
                "limit": 5
            },
            "search": {
                "action": "search",
                "query": "test",
                "limit": 5
            },
            "spaces": {
                "action": "current"
            }
        }
        
        return test_configs.get(tool_name, {})
    
    async def test_all_agents(
        self,
        tools_to_test: Optional[List[str]] = None,
        verbose: bool = True
    ) -> Dict[str, List[TestResult]]:
        """
        Test with all available agents.
        
        Args:
            tools_to_test: Specific tools to test
            verbose: Print progress
            
        Returns:
            Dictionary mapping agent names to results
        """
        all_results = {}
        
        print(f"\n🚀 Testing MCP Server: {self.server_url}")
        print(f"📦 Available agents: {len(self.available_agents)}")
        print("=" * 60)
        
        for agent_name in self.available_agents:
            try:
                results = await self.test_with_agent(agent_name, tools_to_test, verbose)
                all_results[agent_name] = results
            except Exception as e:
                print(f"❌ Failed to test with {agent_name}: {e}")
                all_results[agent_name] = []
        
        self.test_suite.end_time = datetime.now()
        return all_results
    
    async def performance_test(
        self,
        agent_name: str,
        tool_name: str,
        iterations: int = 10,
        concurrent: bool = False
    ) -> Dict[str, Any]:
        """
        Run performance tests on a specific tool.
        
        Args:
            agent_name: Agent to use
            tool_name: Tool to test
            iterations: Number of test iterations
            concurrent: Run tests concurrently
            
        Returns:
            Performance statistics
        """
        if agent_name not in self.available_agents:
            raise ValueError(f"Agent '{agent_name}' not found")
        
        print(f"\n⚡ Performance Testing: {tool_name}")
        print(f"Agent: {agent_name}, Iterations: {iterations}")
        print("-" * 50)
        
        token_dir = self.available_agents[agent_name]
        store = BearerTokenStore(str(token_dir))
        auth = MCPBearerAuth(store, self.oauth_url)
        
        timings = []
        errors = 0
        
        async def run_single_test() -> float:
            """Run a single test iteration."""
            headers = {
                "X-Agent-Name": agent_name,
                "X-Client-Instance": str(uuid.uuid4()),
                "X-Idempotency-Key": str(uuid.uuid4()),
            }
            
            try:
                start = time.time()
                async with streamablehttp_client(
                    url=self.server_url,
                    headers=headers,
                    auth=auth,
                    timeout=timedelta(seconds=30),
                ) as (read, write, _):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        test_args = self._generate_test_args(tool_name)
                        await session.call_tool(tool_name, test_args)
                
                duration = (time.time() - start) * 1000
                return duration
            except Exception:
                return -1  # Error marker
        
        if concurrent:
            # Run tests concurrently
            tasks = [run_single_test() for _ in range(iterations)]
            results = await asyncio.gather(*tasks)
        else:
            # Run tests sequentially
            results = []
            for i in range(iterations):
                result = await run_single_test()
                results.append(result)
                if result > 0:
                    print(f"  Iteration {i+1}: {result:.1f}ms")
                else:
                    print(f"  Iteration {i+1}: ERROR")
        
        # Calculate statistics
        valid_timings = [t for t in results if t > 0]
        errors = len([t for t in results if t <= 0])
        
        if valid_timings:
            stats = {
                "tool": tool_name,
                "agent": agent_name,
                "iterations": iterations,
                "successful": len(valid_timings),
                "errors": errors,
                "min_ms": min(valid_timings),
                "max_ms": max(valid_timings),
                "avg_ms": sum(valid_timings) / len(valid_timings),
                "median_ms": sorted(valid_timings)[len(valid_timings) // 2],
                "concurrent": concurrent
            }
        else:
            stats = {
                "tool": tool_name,
                "agent": agent_name,
                "iterations": iterations,
                "successful": 0,
                "errors": errors,
                "error": "All tests failed"
            }
        
        print("\n📊 Performance Results:")
        for key, value in stats.items():
            if isinstance(value, float):
                print(f"  {key}: {value:.2f}")
            else:
                print(f"  {key}: {value}")
        
        return stats
    
    def generate_report(self, output_file: Optional[str] = None) -> str:
        """
        Generate a test report.
        
        Args:
            output_file: Optional file to save report
            
        Returns:
            Report as string
        """
        summary = self.test_suite.get_summary()
        
        report_lines = [
            "=" * 60,
            "MCP Server Test Report",
            "=" * 60,
            f"Server: {self.server_url}",
            f"Test Date: {self.test_suite.start_time.isoformat()}",
            "",
            "Summary:",
            f"  Total Tests: {summary['total']}",
            f"  Passed: {summary['passed']}",
            f"  Failed: {summary['failed']}",
            f"  Success Rate: {summary.get('success_rate', 0):.1f}%",
            f"  Avg Duration: {summary.get('avg_duration_ms', 0):.1f}ms",
            "",
            "Results by Tool:",
        ]
        
        for tool_name, stats in summary.get("by_tool", {}).items():
            report_lines.append(f"  {tool_name}:")
            report_lines.append(f"    Passed: {stats['passed']}")
            report_lines.append(f"    Failed: {stats['failed']}")
            report_lines.append(f"    Avg Time: {stats['avg_ms']:.1f}ms")
        
        report_lines.extend([
            "",
            "Failed Tests:",
        ])
        
        for result in self.test_suite.results:
            if not result.success:
                report_lines.append(f"  {result.agent_name}/{result.tool_name}: {result.error or 'Unknown error'}")
        
        report = "\n".join(report_lines)
        
        if output_file:
            with open(output_file, "w") as f:
                f.write(report)
            print(f"\n📄 Report saved to: {output_file}")
        
        return report


async def main():
    """Example usage of the MCP Server Tester."""
    import argparse
    
    parser = argparse.ArgumentParser(description="MCP Server Testing Framework")
    parser.add_argument(
        "--server",
        default="http://localhost:8001/mcp",
        help="MCP server URL"
    )
    parser.add_argument(
        "--agent",
        help="Specific agent to test with"
    )
    parser.add_argument(
        "--tool",
        help="Specific tool to test"
    )
    parser.add_argument(
        "--performance",
        action="store_true",
        help="Run performance tests"
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=10,
        help="Performance test iterations"
    )
    parser.add_argument(
        "--report",
        help="Generate report file"
    )
    
    args = parser.parse_args()
    
    # Create tester
    tester = MCPServerTester(server_url=args.server)
    
    if args.performance and args.agent and args.tool:
        # Run performance test
        await tester.performance_test(
            args.agent,
            args.tool,
            args.iterations
        )
    elif args.agent:
        # Test with specific agent
        tools = [args.tool] if args.tool else None
        await tester.test_with_agent(args.agent, tools)
    else:
        # Test all agents
        tools = [args.tool] if args.tool else None
        await tester.test_all_agents(tools)
    
    # Generate report if requested
    if args.report:
        tester.generate_report(args.report)
    else:
        # Print summary
        summary = tester.test_suite.get_summary()
        print("\n" + "=" * 60)
        print(f"✅ Passed: {summary['passed']}")
        print(f"❌ Failed: {summary['failed']}")
        print(f"📊 Success Rate: {summary.get('success_rate', 0):.1f}%")


if __name__ == "__main__":
    asyncio.run(main())