import asyncio
import os
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def test_devops_mcp():
    """
    Programmatically tests the DevOps MCP Server by connecting to it via stdio
    and invoking the generate_bedrock_credentials tool.
    """
    print("Starting DevOps MCP Test...")
    
    # Path to the MCP server script
    server_script = os.path.abspath("devops_mcp.py")
    
    import sys
    # Configure the stdio transport to launch our server
    server_params = StdioServerParameters(
        command=sys.executable,
        args=[server_script]
    )
    
    print(f"Connecting to MCP server at {server_script}...")
    
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # Initialize the MCP connection
            await session.initialize()
            print("Successfully initialized MCP session.\n")
            
            # List available tools on the server
            tools_response = await session.list_tools()
            print("Available Tools on DevOps MCP:")
            for tool in tools_response.tools:
                print(f"- {tool.name}: {tool.description}")
            print("\n")
            
            # Call the generate_bedrock_credentials tool
            print("Calling 'generate_bedrock_credentials' tool...")
            result = await session.call_tool(
                "generate_bedrock_credentials", 
                {"role_arn": "arn:aws:iam::123456789012:role/AgentBedrockRole"}
            )
            
            # Print the output from the tool
            print("\nTool Output:")
            print("-" * 40)
            print(result.content[0].text)
            print("-" * 40)
            print("\nTest complete! The MCP architecture is working perfectly.")

if __name__ == "__main__":
    # Workaround for Windows asyncio event loop policy if needed
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        
    asyncio.run(test_devops_mcp())
