# 金融问答系统应用镜像
# 说明：
#   1. 模型文件（BGE-M3 / reranker / BERT）体积大，不打包进镜像，运行时通过 volume 挂载
#   2. 知识库数据（data/finance）同样通过 volume 挂载
FROM python:3.10-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# 系统依赖：编译工具 + OpenCV 运行库（RapidOCR 需要 libgl/libglib）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ curl git zlib1g-dev \
    libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# CPU 容器使用官方 CPU wheel；其余依赖与本地 requirements.txt 保持同一版本。
COPY requirements-docker.txt .

# 升级 pip 并以 PyPI 镜像提供通用依赖，CPU wheel 源只提供 PyTorch CPU 构建。
RUN pip install --no-cache-dir --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple/ \
    && pip install --no-cache-dir torch==2.12.1+cpu \
        -i https://pypi.tuna.tsinghua.edu.cn/simple/ \
        --extra-index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements-docker.txt -i https://pypi.tuna.tsinghua.edu.cn/simple/

# 复制项目代码
COPY . .

EXPOSE 8090

CMD ["sh", "-c", "python -m uvicorn app:app --host 0.0.0.0 --port 8090"]
