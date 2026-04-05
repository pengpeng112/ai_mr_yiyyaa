#!/bin/sh
# entrypoint.sh - 修复挂载卷权限后启动应用
# Docker volume mount 会覆盖容器内目录权限，需要在启动时修复
set -e

# 确保运行时目录存在且 medaudit 用户可写
for dir in /app/data /app/config /app/logs; do
    mkdir -p "$dir" 2>/dev/null || true
    # 仅在当前用户为 root 时 chown（兼容非 root 场景）
    if [ "$(id -u)" = "0" ]; then
        chown -R medaudit:medaudit "$dir" 2>/dev/null || true
    fi
done

# 如果以 root 运行，切换到 medaudit 用户执行
if [ "$(id -u)" = "0" ]; then
    exec gosu medaudit "$@"
fi

exec "$@"
