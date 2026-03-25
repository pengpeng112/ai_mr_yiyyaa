# backend/Dockerfile
FROM python:3.11-slim

# 安装 Oracle Instant Client 依赖
RUN apt-get update && \
    apt-get install -y --no-install-recommends libaio1t64 curl gcc build-essential || \
    apt-get install -y --no-install-recommends libaio1 curl gcc build-essential && \
    rm -rf /var/lib/apt/lists/*

# Oracle Instant Client（离线部署：提前下载放入 ./oracle-client/）
COPY oracle-client/ /opt/oracle/
ENV LD_LIBRARY_PATH=/opt/oracle
ENV ORACLE_HOME=/opt/oracle

WORKDIR /app

# 先安装依赖（利用 Docker 缓存）
COPY requirements.txt .
RUN pip install --no-cache-dir "setuptools<81" wheel && \
    grep -v "^cx_Oracle==" requirements.txt > requirements.base.txt && \
    pip install --no-cache-dir -r requirements.base.txt && \
    pip install --no-cache-dir --no-build-isolation cx_Oracle==8.3.0

# 复制应用代码
COPY app/ ./app/

# 前端打包产物（如有）
COPY static/ ./static/

# 创建数据目录
RUN mkdir -p data config logs

EXPOSE 8080

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:8080/api/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
