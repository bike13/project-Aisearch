from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from openai import OpenAI
import os
import json
import uuid
from datetime import datetime
import asyncio
import sqlite3
from mcp_api import router as mcp_router
from flie_api import router as files_router
from fastmcp import Client
from fastmcp.client.transports import SSETransport
from dotenv import load_dotenv
from langchain.text_splitter import CharacterTextSplitter
from langchain.document_loaders import PyPDFLoader
from langchain.embeddings import HuggingFaceEmbeddings
from sentence_transformers import SentenceTransformer
from langchain.vectorstores import FAISS
from langchain.chains import RetrievalQA
from langchain_openai import ChatOpenAI
from langchain.prompts import ChatPromptTemplate, HumanMessagePromptTemplate
from langchain.document_loaders import UnstructuredFileLoader

# 检查 .env文件是否存在
if not os.path.exists(".env"):
    raise ValueError("环境变量文件 .env不存在，请检查")

load_dotenv()

# 从env中获取配置
API_KEY = os.getenv("API_KEY")
BASE_URL= os.getenv("BASE_URL")
MODEL_NAME = os.getenv("MODEL_NAME")
 
BOCHAAI_SEARCH_API_KEY = os.getenv("BOCHAAI_SEARCH_API_KEY")

#检查配置是否正确
if not API_KEY or not BASE_URL or not MODEL_NAME :
    raise ValueError("API_KEY配置错误，请检查环境变量 .env文件")

# 初始化 FastAPI 应用
app = FastAPI()

# 挂载 MCP 路由和文件管理路由
app.include_router(mcp_router)      # 提供与MCP相关的API接口
app.include_router(files_router)    # 提供文件管理相关的API接口

# 配置 CORS 中间件，允许所有来源、方法和头部跨域请求
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],        # 允许所有域名访问
    allow_credentials=True,
    allow_methods=["*"],        # 允许所有HTTP方法
    allow_headers=["*"],        # 允许所有HTTP头
)

# 挂载静态文件目录，将/static路径映射到本地static文件夹
app.mount("/static", StaticFiles(directory="static"), name="static")

 # 初始化AI客户端
ai_client = OpenAI(
    api_key = API_KEY,
    base_url = BASE_URL
)

# Initialize SQLite database
def init_db():
    conn = sqlite3.connect('chat_history.db')
    cursor = conn.cursor()
    
    # Create chat sessions table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS chat_sessions (
        id TEXT PRIMARY KEY,
        summary TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Create messages table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT,
        role TEXT,
        content TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (session_id) REFERENCES chat_sessions (id)
    )
    ''')
    
    # Create MCP servers table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS mcp_servers (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        url TEXT NOT NULL,
        description TEXT,
        auth_type TEXT,
        auth_value TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Create MCP tools table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS mcp_tools (
        id TEXT PRIMARY KEY,
        server_id TEXT,
        name TEXT NOT NULL,
        description TEXT,
        input_schema TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (server_id) REFERENCES mcp_servers(id)
    )
    ''')
    
    conn.commit()
    conn.close()
    print("数据库初始化完成")

# Perform web search (optional, retained for flexibility)
# https://open.bochaai.com/overview
async def perform_web_search(query: str):
    try:
        import requests
        
        headers = {
            'Content-Type': 'application/json',  # Remove space
            'Authorization': f'Bearer {BOCHAAI_SEARCH_API_KEY}'
        }
     
        payload = json.dumps({
            "query": query,
            "freshness": "noLimit",
            "summary": True, 
            "count": 10
        })

        # 使用搜索API, 参考文档 https://bocha-ai.feishu.cn/wiki/RXEOw02rFiwzGSkd9mUcqoeAnNK
        response = requests.post("https://api.bochaai.com/v1/web-search", headers=headers, data=payload)
        
        # Check status code before parsing JSON
        if response.status_code != 200:
            return f"搜索失败，状态码: {response.status_code}"
            
        # Only parse JSON if status code is 200
        try:
            json_data = response.json()
            print(f"bochaai search response: {json_data}")
            return str(json_data)
        except json.JSONDecodeError as e:
            return f"搜索结果JSON解析失败: {str(e)}"
            
    except Exception as e:
        return f"执行网络搜索时出错: {str(e)}"

async def perform_rag_search(query: str):
    # 1. 检索
    faiss_index_path = "./local_faiss_index"
    local_model_path = './local_m3e_model'
    # 检查本地是否已存在模型，如果存在则直接加载，否则从网络下载并保存到本地
    if os.path.exists(local_model_path):
        print(f"从本地加载模型: {local_model_path}")
        model = SentenceTransformer(local_model_path)
    else:
        print(f"本地模型不存在，从网络加载: moka-ai/m3e-base")
        model = SentenceTransformer('moka-ai/m3e-base')
        # 保存模型到本地，以便下次使用
        print(f"保存模型到本地: {local_model_path}")
        model.save(local_model_path)
    embeddings = HuggingFaceEmbeddings(model_name=local_model_path)

    # 1. 文本切分
    # 创建一个文本切分器，将长文本分割成较小的片段
    # 使用换行符作为分隔符，每个片段最大500字符，重叠100字符
    text_splitter = CharacterTextSplitter(
        separator="\n",
        chunk_size=500,
        chunk_overlap=100
    )

    # 读取 document 目录下所有 PDF 文件，并对内容进行切分
    document_dir = "./document"


    # 遍历 document 目录下所有子目录，递归查找所有 PDF 文件
    split_texts = [] 
    supported_exts = [".pdf", ".docx", ".doc", ".txt"]
    all_files = []
    for root, dirs, files in os.walk(document_dir):
        for file in files:
            ext = os.path.splitext(file)[1].lower()
            if ext in supported_exts:
                all_files.append(os.path.join(root, file))

    for file_path in all_files:
        print(f"正在处理文件: {file_path}")
        ext = os.path.splitext(file_path)[1].lower()
        if ext == ".pdf":
            loader = PyPDFLoader(file_path)
            pages = loader.load_and_split()
            for page in pages:
                docs = text_splitter.create_documents([page.page_content])
                for doc in docs:
                    split_texts.append(doc.page_content)
                    print('--------------------------------')
        elif ext in [".docx", ".doc", ".txt"]:
            # 使用 UnstructuredFileLoader 处理 Word 和 TXT 文件
            loader = UnstructuredFileLoader(file_path)
            docs = loader.load()
            for doc in docs:
                # 对每个文档内容进行切分
                split_docs = text_splitter.create_documents([doc.page_content])
                for split_doc in split_docs:
                    split_texts.append(split_doc.page_content)
                    print('--------------------------------')

    # 2. 构建向量数据库（FAISS），并进行索引备份
    if os.path.exists(faiss_index_path):
        # 如果已存在索引，则直接加载
        print(f"检测到已存在的FAISS索引，加载: {faiss_index_path}")
        vectorstore = FAISS.load_local(faiss_index_path, embeddings, allow_dangerous_deserialization=True)
    else:
        # 如果没有索引，则重新构建并保存
        print("未检测到FAISS索引，重新构建并备份...")
        vectorstore = FAISS.from_texts(split_texts, embedding=embeddings)
        vectorstore.save_local(faiss_index_path)
        print(f"已将FAISS索引备份到: {faiss_index_path}")

    # 3. 进行查找检索，返回3个相关文档
    retriever = vectorstore.as_retriever(search_kwargs={"k": 3})

    docs = retriever.invoke(query)
    print(f"RAG检索结果: {docs}")
    return str(docs)
 

# Save new chat session
async def create_new_chat_session(session_id: str, query: str, response: str):
    conn = sqlite3.connect('chat_history.db')
    cursor = conn.cursor()
    summary = query[:50] + ("..." if len(query) > 50 else "")
    cursor.execute(
        '''
        INSERT INTO chat_sessions (id, summary, created_at, updated_at)
        VALUES (?, ?, ?, ?)
        ''',
        (session_id, summary, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    )
    cursor.execute(
        '''
        INSERT INTO messages (session_id, role, content, created_at)
        VALUES (?, ?, ?, ?)
        ''',
        (session_id, "user", query, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    )
    cursor.execute(
        '''
        INSERT INTO messages (session_id, role, content, created_at)
        VALUES (?, ?, ?, ?)
        ''',
        (session_id, "assistant", response, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    )
    conn.commit()
    conn.close()

# Add message to existing session
async def add_message_to_session(session_id: str, query: str, response: str):
    conn = sqlite3.connect('chat_history.db')
    cursor = conn.cursor()
    cursor.execute(
        '''
        INSERT INTO messages (session_id, role, content, created_at)
        VALUES (?, ?, ?, ?)
        ''',
        (session_id, "user", query, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    )
    cursor.execute(
        '''
        INSERT INTO messages (session_id, role, content, created_at)
        VALUES (?, ?, ?, ?)
        ''',
        (session_id, "assistant", response, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    )
    cursor.execute(
        '''
        UPDATE chat_sessions
        SET updated_at = ?
        WHERE id = ?
        ''',
        (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), session_id)
    )
    conn.commit()
    conn.close()

# Process stream request (updated to use openai for GLM, requests for tools)
# 这段代码定义了一个异步函数 process_stream_request，用于处理前端发来的流式对话请求，支持普通问答、联网搜索和智能Agent工具调用三种模式。下面逐步解释其主要逻辑：

async def process_stream_request(query: str, session_id: str = None, web_search: bool = False, rag_search: bool = False, agent_mode: bool = False):
    """
    处理流式对话请求，支持普通问答、联网搜索和Agent工具调用。
    参数:
        query: 用户输入的问题
        session_id: 会话ID（可选）
        web_search: 是否启用联网搜索
        rag_search: 是否启用RAG搜索
        agent_mode: 是否启用Agent工具调用
    """

    print(f"query: {query}, session_id: {session_id}, web_search: {web_search}, rag_search: {rag_search}, agent_mode: {agent_mode}")
    
    # 1. 检查会话ID是否存在，不存在则新建一个
    conn = sqlite3.connect('chat_history.db')
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM chat_sessions WHERE id = ?", (session_id,))
    has_session = cursor.fetchone()
    if not has_session:
        session_id = str(uuid.uuid4())

    # 2. 构建上下文信息（如启用联网搜索则获取搜索结果）
    context_parts = []
    if web_search:
        web_results = await perform_web_search(query)
        context_parts.append(web_results)
    context = "\n".join(context_parts) if context_parts else "无上下文信息"

    if rag_search:
        rag_results = await perform_rag_search(query)
        context_parts.append(rag_results)
    context = "\n".join(context_parts) if context_parts else "无上下文信息"

    # 3. 定义一个通用的流式响应生成器
    async def generate(content_stream=None, initial_content=""):
        """
        负责将大模型的响应以SSE流式返回给前端，并在结束后写入数据库。
        """
        full_response = initial_content
        
        if content_stream:
            # 流式返回大模型内容
            try:
                for chunk in content_stream:
                    if chunk.choices[0].delta.content:
                        content = chunk.choices[0].delta.content
                        full_response += content
                        yield f"data: {json.dumps({'content': content, 'session_id': session_id})}\n\n"
                        await asyncio.sleep(0.01)
                    if chunk.choices[0].finish_reason is not None:
                        yield f"data: {json.dumps({'content': '', 'session_id': session_id, 'done': True})}\n\n"
                        break
            except Exception as e:
                yield f"data: {json.dumps({'content': f'错误：GLM API 请求失败 - {str(e)}', 'session_id': session_id, 'done': True})}\n\n"
                return
        else:
            # 非流式直接返回
            yield f"data: {json.dumps({'content': full_response, 'session_id': session_id})}\n\n"
            yield f"data: {json.dumps({'content': '', 'session_id': session_id, 'done': True})}\n\n"
        
        # 结束后写入数据库
        if has_session:
            await add_message_to_session(session_id, query, full_response)
        else:
            await create_new_chat_session(session_id, query, full_response)

    # 4. 如果启用Agent模式，先让大模型判断是否需要调用工具
    if agent_mode:
        # 4.1 查询所有可用工具
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(" SELECT t.*, s.url FROM mcp_tools t LEFT JOIN mcp_servers s ON t.server_id = s.id ")
        tools = [dict(row) for row in cursor.fetchall()]
        conn.close()

        # 4.2 构造工具描述，拼接到prompt里
        tool_descriptions = "\n".join([
            f"server_url: {tool['url']}\n\ntool_name: {tool['name']}\nDescription: {tool['description']}\ninput_schema: {tool['input_schema']}"
            for tool in tools
        ]) if tools else "无可用工具"

        # 4.3 构造Agent决策prompt，要求大模型返回JSON格式（如果需要用工具），否则直接返回答案
        agent_prompt = f"""
        上下文信息:\n{context}\n
        问题: {query}\n
        可用工具:\n{tool_descriptions}\n
        你是一个智能助手，可以根据用户问题选择合适的工具执行操作。
        如果需要使用工具，请返回以下格式的JSON：
        ```jsoni18n-ally
        {{
          "server_url": "server_url",
          "tool_name": "tool_name",
          "parameters":{{"param_name1": "param_value1", "param_name2": "param_value2"}}
        }}
        ```
        如果不需要工具，直接返回回答内容的字符串。
        """

        # 4.4 调用大模型（非流式），让其决策
        try:
            response = ai_client.chat.completions.create(
                model = MODEL_NAME,
                messages= [
                    {"role": "system", "content": "你是一个智能助手，擅长选择合适的工具或直接回答问题。"},
                    {"role": "user", "content": agent_prompt}
                ],
                stream=False,
                response_format={"type": "json_object"} 
            )
            decision = response.choices[0].message.content.strip()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"GLM API request failed: {str(e)}")

        # 4.5 判断大模型返回的是不是工具调用
        try:
            decision_json = json.loads(decision)
            if "server_url" in decision_json and "tool_name" in decision_json:
                # 需要调用工具
                server_url = decision_json["server_url"]
                tool_name = decision_json["tool_name"]
                parameters = decision_json["parameters"]
                
                try:
                    # 4.6 通过SSE协议调用工具服务器
                    async with Client(SSETransport(server_url)) as client: 
                        tool_result = await client.call_tool(tool_name, parameters)
                        tool_response = f"工具 {tool_name} 执行结果：{tool_result}"
                        print(f"工具 {tool_name} 执行结果：{tool_result}")
                        
                        # 4.7 工具调用结果作为上下文，再次调用大模型（流式返回）
                        prompt = f"上下文信息:\n{tool_result}\n\n问题: {query}\n请基于上下文信息回答问题:"
                        stream = ai_client.chat.completions.create(
                            model=MODEL_NAME,
                            messages=[{"role": "user", "content": prompt}],
                            stream=True
                        )
                        return StreamingResponse(
                            generate(stream, tool_response),
                            media_type="text/event-stream",
                            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "Transfer-Encoding": "chunked"}
                        )
                except Exception as e:
                    # 工具调用失败，直接返回错误信息
                    return StreamingResponse(
                        generate(initial_content=f"工具 {tool_name} 执行失败：{str(e)}"),
                        media_type="text/event-stream",
                        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "Transfer-Encoding": "chunked"}
                    )
            else:
                # 直接返回大模型的答案
                return StreamingResponse(
                    generate(initial_content=decision),
                    media_type="text/event-stream",
                    headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "Transfer-Encoding": "chunked"}
                )
        except json.JSONDecodeError:
            # 返回不是JSON，直接作为答案
            return StreamingResponse(
                generate(initial_content=decision),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "Transfer-Encoding": "chunked"}
            )
    
    # 5. 非Agent模式，直接流式调用大模型
    prompt = f"上下文信息:\n{context}\n\n问题: {query}\n请基于上下文信息回答问题:"
    print(f"prompt: {prompt}")
    
    try:
        stream = ai_client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": "你是一个专业的问答助手。"},
                {"role": "user", "content": prompt}
            ],
            stream=True
        )
    except Exception as e:
        # 大模型接口异常，流式返回错误
        async def generate_error():
            global e
            yield f"data: {json.dumps({'content': f'错误：大模型 API 请求失败 - {e}', 'session_id': session_id, 'done': True})}\n\n"
        return StreamingResponse(
            generate_error(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "Transfer-Encoding": "chunked"}
        )
    
    # 6. 正常流式返回大模型内容
    return StreamingResponse(
        generate(stream),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "Transfer-Encoding": "chunked"}
    )


# Stream endpoint
@app.get("/api/stream")
async def stream(
    query: str,
    session_id: str = Query(None),
    web_search: bool = Query(False),
    rag_search: bool = Query(False),
    agent_mode: bool = Query(False),
):
    return await process_stream_request(query, session_id, web_search, rag_search, agent_mode)


# 会话历史记录 API
@app.get("/api/chat/history")
async def get_chat_history():
    try:
        conn = sqlite3.connect('chat_history.db')
        conn.row_factory = sqlite3.Row  # 启用行工厂，使结果可以通过列名访问
        cursor = conn.cursor()
        
        cursor.execute("SELECT id, summary, updated_at  FROM chat_sessions ORDER BY updated_at DESC")
        rows = cursor.fetchall()
        
        # 将行转换为字典
        sessions = [dict(row) for row in rows]
        
        conn.close()
        return sessions
        
    except Exception as e:
        print(f"获取聊天历史失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取聊天历史失败: {str(e)}")

@app.get("/api/chat/session/{session_id}")
async def get_session(session_id: str):
    try:
        conn = sqlite3.connect('chat_history.db')
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # 查询会话是否存在
        cursor.execute("SELECT id FROM chat_sessions WHERE id = ?", (session_id,))
        session = cursor.fetchone()
        
        if not session:
            conn.close()
            raise HTTPException(status_code=404, detail="会话不存在")
        
        # 获取会话中的所有消息
        cursor.execute(
            "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id asc",
            (session_id,)
        )
        messages = [dict(row) for row in cursor.fetchall()]
        
        conn.close()
        return {"messages": messages}
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"获取会话详情失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取会话详情失败: {str(e)}")

# 删除会话
@app.delete("/api/chat/session/{session_id}")
async def delete_session(session_id: str):
    try:
        conn = sqlite3.connect('chat_history.db')
        cursor = conn.cursor()
        
        # 首先删除会话关联的所有消息
        cursor.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        
        # 然后删除会话本身
        cursor.execute("DELETE FROM chat_sessions WHERE id = ?", (session_id,))
        
        if cursor.rowcount == 0:
            conn.close()
            raise HTTPException(status_code=404, detail="会话不存在")
        
        conn.commit()
        conn.close()
        
        return {"message": "会话已删除"}
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"删除会话失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"删除会话失败: {str(e)}")



from fastapi import Body

@app.put("/api/chat/renameSession/{session_id}")
async def rename_session(
    session_id: str,
    data: dict = Body(...)
):

    new_name = data.get("new_name")
    print(f"重命名会话: {session_id}, 新名称: {new_name}")
    if not new_name:
        raise HTTPException(status_code=400, detail="缺少 new_name 参数")
    try:
        conn = sqlite3.connect('chat_history.db')
        cursor = conn.cursor()

        # 重命名会话
        cursor.execute("UPDATE chat_sessions SET summary = ? WHERE id = ?", (new_name, session_id))
        
        conn.commit()
        conn.close()
        
        return {"message": "会话已重命名"}
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"重命名会话失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"重命名会话失败: {str(e)}")



# 导出会话为markdown格式下载
@app.get("/api/chat/export/{session_id}")
async def export_session(session_id: str):
    try:
        conn = sqlite3.connect('chat_history.db')
        conn.row_factory = sqlite3.Row  # Set row factory to enable dictionary access
        cursor = conn.cursor()
        
        # 查询会话是否存在
        cursor.execute("SELECT id, summary FROM chat_sessions WHERE id = ?", (session_id,))
        session = cursor.fetchone()
        
        if not session:
            conn.close()
            raise HTTPException(status_code=404, detail="会话不存在")
        
        # 获取会话中的所有消息
        cursor.execute("SELECT role, content FROM messages WHERE session_id = ? ORDER BY id asc", (session_id,))
        messages = cursor.fetchall()
        
        # 构建markdown内容
        markdown_content = f"# 会话历史记录\n\n"
        markdown_content += f"## 会话ID: {session_id}\n\n"
        markdown_content += f"## 会话总结: {session['summary']}\n\n"
        
        for message in messages:
            role = message['role']
            content = message['content']
            markdown_content += f"### {role}\n\n{content}\n\n"
        
        conn.close()
        
        return StreamingResponse(
            iter([markdown_content]), 
            media_type="text/markdown", 
            headers={"Content-Disposition": f"attachment; filename=session_{session_id}.md"}
        )
        
    except Exception as e:
        print(f"导出会话失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"导出会话失败: {str(e)}")













# 健康检查接口
@app.get("/api/health")
def health_check():
    return {"status": "healthy"}


if __name__ == "__main__":
    init_db()
    import uvicorn
    # 可以通过环境变量设置端口，默认为8000
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)