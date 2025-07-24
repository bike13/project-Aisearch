from fastapi import APIRouter, HTTPException
import sqlite3
import requests
import uuid
import json
from datetime import datetime
from fastmcp import Client
from fastmcp.client.transports import (PythonStdioTransport, SSETransport)



router = APIRouter(prefix="/api/mcp", tags=["mcp"])


# Function to fetch tools from an MCP server
# 参考mcp定义：https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2025-03-26/server/tools.mdx
async def fetch_mcp_tools(server_url: str, auth_type: str, auth_value: str) -> list:
    try:
        async with Client(SSETransport(server_url)) as client:         
            tools = await client.list_tools()
            print(tools)
        # Ensure tools have required fields
        return [
            {
                "id": str(uuid.uuid4()),
                "name": tool.name,
                "description": tool.description,
                "input_schema": json.dumps(tool.inputSchema)
            }
            for tool in tools
        ]
    except Exception as e:
        print(f"Error fetching tools from {server_url}: {str(e)}")
        return []

# 创建 MCP 服务器的接口
@router.post("/servers")
async def create_mcp_server(server: dict):
    try:
        # 生成唯一的 server_id
        server_id = str(uuid.uuid4())
        # 连接到 SQLite 数据库
        conn = sqlite3.connect('chat_history.db')
        cursor = conn.cursor()
        # 插入 MCP 服务器信息到 mcp_servers 表
        cursor.execute(
            '''
            INSERT INTO mcp_servers (id, name, url, description, auth_type, auth_value, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                server_id,
                server["name"],
                server["url"],
                server.get("description", ""),           # 可选字段，默认为空字符串
                server.get("auth_type", "none"),         # 可选字段，默认为 "none"
                server.get("auth_value", ""),             # 可选字段，默认为空字符串
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),  # 创建时间
                datetime.now().strftime('%Y-%m-%d %H:%M:%S')   # 更新时间
            )
        )
        conn.commit()
        
        # 从 MCP 服务器拉取工具列表，并存储到 mcp_tools 表
        tools = await fetch_mcp_tools(server["url"], server.get("auth_type", "none"), server.get("auth_value", ""))
        for tool in tools:
            cursor.execute(
                '''
                INSERT INTO mcp_tools (id, server_id, name, description, input_schema, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ''',
                (
                    tool["id"],                   # 工具唯一 id
                    server_id,                    # 关联的服务器 id
                    tool["name"],                 # 工具名称
                    tool["description"],          # 工具描述
                    tool["input_schema"],         # 工具输入 schema
                    datetime.now().strftime('%Y-%m-%d %H:%M:%S')  # 创建时间
                )
            )
        conn.commit()
        conn.close()
        # 返回创建成功的 server_id 和消息
        return {"id": server_id, "message": "MCP server created successfully"}
    except Exception as e:
        # 捕获异常并返回 HTTP 500 错误
        raise HTTPException(status_code=500, detail=f"Failed to create MCP server: {str(e)}")




# List MCP servers
@router.get("/servers")
async def list_mcp_servers():
    try:
        conn = sqlite3.connect('chat_history.db')
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, url, description, auth_type, auth_value, created_at, updated_at FROM mcp_servers")
        servers = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return servers
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list MCP servers: {str(e)}")

# Get specific MCP server
@router.get("/servers/{server_id}")
async def get_mcp_server(server_id: str):
    try:
        conn = sqlite3.connect('chat_history.db')
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, url, description, auth_type, auth_value, created_at, updated_at FROM mcp_servers WHERE id = ?", (server_id,))
        server = cursor.fetchone()
        conn.close()
        if not server:
            raise HTTPException(status_code=404, detail="MCP server not found")
        return dict(server)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get MCP server: {str(e)}")

# Update MCP server
@router.put("/servers/{server_id}")
async def update_mcp_server(server_id: str, server: dict):
    try:
        conn = sqlite3.connect('chat_history.db')
        cursor = conn.cursor()
        cursor.execute(
            '''
            UPDATE mcp_servers
            SET name = ?, url = ?, description = ?, auth_type = ?, auth_value = ?, updated_at = ?
            WHERE id = ?
            ''',
            (
                server["name"],
                server["url"],
                server.get("description", ""),
                server.get("auth_type", "none"),
                server.get("auth_value", ""),
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                server_id
            )
        )
        if cursor.rowcount == 0:
            conn.close()
            raise HTTPException(status_code=404, detail="MCP server not found")
        
        # Delete existing tools for this server
        cursor.execute("DELETE FROM mcp_tools WHERE server_id = ?", (server_id,))
        
        # Fetch and store new tools
        tools = await fetch_mcp_tools(server["url"], server.get("auth_type", "none"), server.get("auth_value", ""))
        for tool in tools:
            cursor.execute(
                '''
                INSERT INTO mcp_tools (id, server_id, name, description, input_schema,created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ''',
                (
                    tool["id"],
                    server_id,
                    tool["name"],
                    tool["description"],
                    tool["input_schema"],
                    datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                )
            )
        conn.commit()
        conn.close()
        return {"message": "MCP server updated successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update MCP server: {str(e)}")

# Delete MCP server
@router.delete("/servers/{server_id}")
async def delete_mcp_server(server_id: str):
    try:
        conn = sqlite3.connect('chat_history.db')
        cursor = conn.cursor()
        # Delete associated tools
        cursor.execute("DELETE FROM mcp_tools WHERE server_id = ?", (server_id,))
        # Delete server
        cursor.execute("DELETE FROM mcp_servers WHERE id = ?", (server_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="MCP server not found")
        conn.commit()
        conn.close()
        return {"message": "MCP server deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete MCP server: {str(e)}")

# Refresh tools for an MCP server
@router.post("/servers/{server_id}/refresh-tools")
async def refresh_mcp_server_tools(server_id: str):
    try:
        conn = sqlite3.connect('chat_history.db')
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT url, auth_type, auth_value FROM mcp_servers WHERE id = ?", (server_id,))
        server = cursor.fetchone()
        if not server:
            conn.close()
            raise HTTPException(status_code=404, detail="MCP server not found")
        
        # Delete existing tools for this server
        cursor.execute("DELETE FROM mcp_tools WHERE server_id = ?", (server_id,))
        
        # Fetch and store new tools
        tools = await fetch_mcp_tools(server["url"], server["auth_type"], server["auth_value"])
        for tool in tools:
            cursor.execute(
                '''
                INSERT INTO mcp_tools (id, server_id, name, description, input_schema,created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ''',
                (
                    tool["id"],
                    server_id,
                    tool["name"],
                    tool["description"],
                    tool["input_schema"],
                    datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                )
            )
        conn.commit()
        conn.close()
        return {"message": "Tools refreshed successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to refresh tools: {str(e)}")

# List tools (optionally filtered by server_id)
@router.get("/tools")
async def list_tools(server_id: str = None):
    try:
        conn = sqlite3.connect('chat_history.db')
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        if server_id:
            cursor.execute("SELECT * FROM mcp_tools WHERE server_id = ?", (server_id,))
        else:
            cursor.execute("SELECT * FROM mcp_tools")
        tools = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return tools
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list tools: {str(e)}")

# Helper function to get MCP server details (used by process_stream_request)
async def get_mcp_server_details(server_id: str) -> dict:
    try:
        conn = sqlite3.connect('chat_history.db')
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, url, auth_type, auth_value FROM mcp_servers WHERE id = ?", (server_id,))
        server = cursor.fetchone()
        conn.close()
        if not server:
            raise HTTPException(status_code=404, detail="MCP server not found")
        return dict(server)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get MCP server: {str(e)}")