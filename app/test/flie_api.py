from fastapi import FastAPI, UploadFile, File, Form, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import os
import shutil
from typing import List

app = FastAPI()

@app.get("/api/index")
async def show_index():
    return {"message": "这是首页!"}

# 获取文件列表
def list_files_and_folders(path):
    items = []
    if not os.path.exists(path):
        return items
    for name in os.listdir(path):
        full_path = os.path.join(path, name)
        if os.path.isdir(full_path):
            items.append({"name": name, "type": "folder"})
        else:
            items.append({"name": name, "type": "file"})
    return items

@app.get("/api/files")
async def get_files(path: str):
    items = list_files_and_folders(path)
    return JSONResponse(items)

# 获取目录列表（返回所有子目录的绝对路径）
def get_all_dirs(root):
    result = []
    for dirpath, dirnames, _ in os.walk(root):
        result.append(dirpath.replace("\\", "/"))
    return result

@app.get("/api/paths")
async def get_paths():
    root = "document"
    if not os.path.exists(root):
        os.makedirs(root)
    paths = get_all_dirs(root)
    return JSONResponse(paths)

# 新建目录
@app.post("/api/folders")
async def create_folder(name: str = Form(...), path: str = Form(...)):
    new_dir = os.path.join(path, name)
    if not os.path.exists(new_dir):
        os.makedirs(new_dir)
        return {"message": "Folder created successfully"}
    else:
        return JSONResponse({"detail": "Folder already exists"}, status_code=400)

# 上传文件
@app.post("/api/files/upload")
async def upload_file(file: UploadFile = File(...), path: str = Form(...)):
    if not os.path.exists(path):
        os.makedirs(path)
    file_path = os.path.join(path, file.filename)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return {"message": "File uploaded successfully"}

# 删除文件或目录
@app.delete("/api/files")
async def delete_file(name: str = Form(...), path: str = Form(...), type: str = Form(...)):
    target = os.path.join(path, name)
    if type == "file":
        if os.path.exists(target):
            os.remove(target)
            return {"message": "File deleted successfully"}
        else:
            return JSONResponse({"detail": "File not found"}, status_code=404)
    elif type == "folder":
        if os.path.exists(target):
            shutil.rmtree(target)
            return {"message": "Folder deleted successfully"}
        else:
            return JSONResponse({"detail": "Folder not found"}, status_code=404)
    else:
        return JSONResponse({"detail": "Invalid type"}, status_code=400)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
