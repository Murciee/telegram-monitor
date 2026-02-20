# 1. 使用官方 Python 3.11 轻量级基础镜像
FROM python:3.11-slim

# 2. 设置工作目录
WORKDIR /app

# 3. 安装 C 编译器和系统依赖 (这是安装 psutil 和 cryptography 必须的)
RUN apt-get update && apt-get install -y \
    gcc \
    python3-dev \
    libssl-dev \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# 4. 先复制依赖清单并安装，利用 Docker 缓存加速后续构建
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. 复制所有的代码到容器中
COPY . .

# 6. 暴露你在 .env 中设置的 8000 端口
EXPOSE 8000

# 7. 启动你的程序
CMD ["python", "web_app_launcher.py"]
