from fastapi import APIRouter, UploadFile, File, Form, Query, HTTPException, Body
from fastapi.responses import JSONResponse
import os
import shutil
import subprocess
import shutil
from langchain.text_splitter import CharacterTextSplitter
from langchain.document_loaders import PyPDFLoader
from langchain.embeddings import HuggingFaceEmbeddings
from sentence_transformers import SentenceTransformer
from langchain.vectorstores import FAISS


router = APIRouter(prefix="/api/files", tags=["files"])
BASE_DIR = "./document"

def safe_join(base, *paths):
    # 防止目录穿越攻击
    final_path = os.path.abspath(os.path.join(base, *paths))
    if not final_path.startswith(os.path.abspath(base)):
        raise HTTPException(status_code=400, detail="非法路径")
    return final_path

def frontend_path_to_backend(path):
    if not path or path == '根目录' or path == '/':
        return ''
    return path.lstrip('/')

@router.get("/current")
async def get_current_files(path: str = Query(...)):
    try:
        rel_path = frontend_path_to_backend(path)
        current_path = safe_join(BASE_DIR, rel_path) if rel_path else os.path.abspath(BASE_DIR)
        if not os.path.exists(current_path):
            return {"files": [], "folders": []}
        files = []
        folders = []
        for item in os.listdir(current_path):
            if os.path.isfile(os.path.join(current_path, item)):
                files.append(item)
            elif os.path.isdir(os.path.join(current_path, item)):
                folders.append(item)
        return {"files": files, "folders": folders}
    except Exception as e:
        # 文件拉取失败，返回详细错误信息
        raise HTTPException(status_code=500, detail=f"文件拉取失败: {str(e)}")

@router.get("/paths")
async def get_paths():
    try:
        paths = ['']  # 根目录
        for root, dirs, _ in os.walk(BASE_DIR):
            for d in dirs:
                dir_path = os.path.join(root, d)
                rel_path = os.path.relpath(dir_path, BASE_DIR)
                rel_path = rel_path.replace("\\", "/")
                paths.append(rel_path)
        return paths
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"目录路径获取失败: {str(e)}")

@router.post("/folders")
async def create_folder(name: str = Form(...), path: str = Form(...)):
    try:
        rel_path = frontend_path_to_backend(path)
        current_path = safe_join(BASE_DIR, rel_path) if rel_path else os.path.abspath(BASE_DIR)
        os.makedirs(os.path.join(current_path, name), exist_ok=True)
        return {"message": "文件夹创建成功"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"文件夹创建失败: {str(e)}")

@router.post("/upload")
async def upload_file(file: UploadFile = File(...), path: str = Form(...)):
    try:
        rel_path = frontend_path_to_backend(path)
        current_path = safe_join(BASE_DIR, rel_path) if rel_path else os.path.abspath(BASE_DIR)
        os.makedirs(current_path, exist_ok=True)
        file_path = os.path.join(current_path, file.filename)
        with open(file_path, "wb") as f:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)
        return {"message": "文件上传成功"}
    except Exception as e:
        # 详细错误信息返回给前端，便于调试
        raise HTTPException(status_code=500, detail=f"文件上传失败: {str(e)}")

@router.delete("/del")
async def delete_file(
    name: str = Body(...),
    path: str = Body(...),
    type: str = Body(...)
):
    try:
        rel_path = frontend_path_to_backend(path)
        current_path = safe_join(BASE_DIR, rel_path) if rel_path else os.path.abspath(BASE_DIR)
        target_path = os.path.join(current_path, name)
        if not os.path.exists(target_path):
            raise HTTPException(status_code=404, detail="目标不存在")
        if type == "file":
            os.remove(target_path)
            return {"message": "文件删除成功"}
        elif type == "folder":
            shutil.rmtree(target_path)
            return {"message": "文件夹删除成功"}
        else:
            raise HTTPException(status_code=400, detail="无效类型")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")



@router.post("/reIndex")
async def reIndex():
    # 1. 删除原有索引
    faiss_index_dir = "./local_faiss_index"
    if os.path.exists(faiss_index_dir):
        for f in os.listdir(faiss_index_dir):
            file_path = os.path.join(faiss_index_dir, f)
            if os.path.isfile(file_path):
                os.remove(file_path)

    # 2. 遍历所有PDF，切分文本
    document_dir = BASE_DIR
    text_splitter = CharacterTextSplitter(separator="\n", chunk_size=500, chunk_overlap=100)
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

    # 3. 构建嵌入模型
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

    # 4. 构建faiss索引并保存
    os.makedirs(faiss_index_dir, exist_ok=True)
    if split_texts:
        vectorstore = FAISS.from_texts(split_texts, embedding=embeddings)
        vectorstore.save_local(faiss_index_dir)
        return {"message": "索引重建完成", "text_chunks": len(split_texts)}
    else:
        return {"message": "未找到PDF文件，未重建索引"}










