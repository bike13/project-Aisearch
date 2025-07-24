# 使用官方 Python 镜像
FROM python:3.10-slim



# 设置工作目录
WORKDIR /app

# 更新 pip
RUN pip install --upgrade pip



# 复制并安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt 

 
# 安装 supervisor
RUN apt-get update
RUN apt-get install -y supervisor
RUN mkdir -p /etc/supervisor
COPY supervisord.conf /etc/supervisor/supervisord.conf


# 复制整个 app 目录（包含子目录和静态文件）
COPY . .

# 暴露端口
EXPOSE 8000
EXPOSE 9001
EXPOSE 9002

# 使用 uvicorn 运行 FastAPI 应用
#CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
# 使用 supervisord 启动所有服务
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/supervisord.conf"]


