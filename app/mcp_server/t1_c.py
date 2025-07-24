from fastmcp import Client
from fastmcp.client.transports import (PythonStdioTransport, SSETransport)
import asyncio

async def test_sse():
    async with Client(SSETransport("http://127.0.0.1:9001/sse")) as client:
        tools = await client.list_tools()
        
        for tool in tools:
            print(f"Tool: {tool.name}")
            print(f"Description: {tool.description}")
            if tool.inputSchema:
                print(f"Parameters: {tool.inputSchema}")


async def test_sse_2():
    async with Client(SSETransport("http://127.0.0.1:9001/sse")) as client:
        result = await client.call_tool("add", {"a": 1, "b": 2})
        print(result)


if __name__ == "__main__":
    result1 = asyncio.run(test_sse())
    print(result1)
    # result2 = asyncio.run(test_sse_2())
    # print(result2)