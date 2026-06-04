# backend/Dockerfile
# 适用于 OpenEuler / CentOS / Ubuntu 内网部署
FROM python:3.11-slim

# 安装系统依赖
# libaio1t64 是 Debian 12+ 的包名，旧版叫 libaio1，两者都尝试
RUN apt-get update && \
    (apt-get install -y --no-install-recommends libaio1t64 || \
     apt-get install -y --no-install-recommends libaio1) && \
    apt-get install -y --no-install-recommends \
        curl \
        gcc \
        python3-dev \
        gosu \
        tzdata && \
    # 设置时区为上海（Asia/Shanghai）
    ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime && \
    echo "Asia/Shanghai" > /etc/timezone && \
    # Debian 12+ 中 Oracle 11g/19c 仍可能寻找 libaio.so.1，这里补兼容软链
    (ln -sf /usr/lib/x86_64-linux-gnu/libaio.so.1t64 /usr/lib/x86_64-linux-gnu/libaio.so.1 2>/dev/null || true) && \
    (ln -sf /lib/x86_64-linux-gnu/libaio.so.1t64 /lib/x86_64-linux-gnu/libaio.so.1 2>/dev/null || true) && \
    rm -rf /var/lib/apt/lists/*

ENV TZ=Asia/Shanghai

# Oracle Instant Client（离线部署：从 oracle-client/linux/ 复制）
COPY oracle-client/linux/ /opt/oracle/
RUN cd /opt/oracle && \
    mkdir -p /opt/oracle/lib && \
    # 创建软链接（Oracle 11.2 需要）
    (ln -sf libclntsh.so.11.1 libclntsh.so  2>/dev/null || true) && \
    (ln -sf libocci.so.11.1  libocci.so    2>/dev/null || true) && \
    (ln -sf /opt/oracle/libclntsh.so.11.1 /opt/oracle/lib/libclntsh.so 2>/dev/null || true) && \
    (ln -sf /opt/oracle/libocci.so.11.1 /opt/oracle/lib/libocci.so 2>/dev/null || true) && \
    # 更新动态链接库缓存
    echo "/opt/oracle" > /etc/ld.so.conf.d/oracle.conf && \
    ldconfig

ENV LD_LIBRARY_PATH=/opt/oracle:/opt/oracle/lib
ENV ORACLE_HOME=/opt/oracle
ENV NLS_LANG=SIMPLIFIED CHINESE_CHINA.AL32UTF8

WORKDIR /app

# 先安装依赖（利用 Docker layer 缓存）
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir "setuptools<81" wheel && \
    # 先安装除 cx_Oracle 外的依赖
    grep -v "^cx_Oracle" requirements.txt > requirements.base.txt && \
    pip install --no-cache-dir -r requirements.base.txt && \
    # 单独安装 cx_Oracle（需要 Oracle Client 头文件）
    pip install --no-cache-dir --no-build-isolation cx_Oracle==8.3.0

# 复制应用代码
COPY app/ ./app/
COPY scripts/ ./scripts/

# 前端静态文件
COPY static/ ./static/

# 创建运行时目录
RUN mkdir -p data config logs

# 创建非 root 用户（实际切换由 entrypoint.sh 完成，以便修复挂载卷权限）
RUN groupadd -r medaudit && useradd -r -g medaudit -d /app medaudit && chown -R medaudit:medaudit /app

# 复制 entrypoint 脚本
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENTRYPOINT ["entrypoint.sh"]

# 暴露端口
EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

# 启动命令
# 保持单 worker，避免应用内 APScheduler 在多进程下重复执行
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
