#!/bin/bash
# ============================================================
# Med-Audit - Docker 首次部署脚本（在 Linux 服务器上运行）
# 用法:
#   bash docker_deploy.sh
# 前提:
#   docker load -i med-audit-image.tar 已执行
# 说明:
#   本文件已固定为 LF 换行，避免 Windows -> Linux 时出现 $'\r' 报错
# ============================================================
set -euo pipefail

cd "$(dirname "$0")"
DEPLOY_DIR="$(pwd)"
DATA_DIR="$DEPLOY_DIR/data"
CONFIG_DIR="$DEPLOY_DIR/config"
LOGS_DIR="$DEPLOY_DIR/logs"
ENV_FILE="$DEPLOY_DIR/.env"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

echo ""
echo "============================================================"
echo "  Med-Audit - Docker Deploy"
echo "============================================================"
echo ""

# ---- [1] 检查 Docker ----
info "[1/4] Checking Docker..."
command -v docker >/dev/null 2>&1 || error "Docker not installed. Run: yum install -y docker && systemctl start docker"
docker info >/dev/null 2>&1 || error "Docker daemon not running. Run: systemctl start docker"
info "Docker OK: $(docker --version)"

# ---- [2] 检查镜像 ----
info "[2/4] Checking image..."
if ! docker image inspect med-audit:latest >/dev/null 2>&1; then
    error "Image med-audit:latest not found. Run: docker load -i med-audit-image.tar"
fi
info "Image med-audit:latest ready"

# ---- [3] 检查 .env ----
info "[3/4] Setting up configuration..."
mkdir -p "$DATA_DIR" "$CONFIG_DIR" "$LOGS_DIR"

if [ ! -f "$ENV_FILE" ]; then
    JWT_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))" 2>/dev/null || cat /proc/sys/kernel/random/uuid | tr -d '-')
    SEC_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))" 2>/dev/null || cat /proc/sys/kernel/random/uuid | tr -d '-')
    SERVER_IP=$(hostname -I | awk '{print $1}')

    cat > "$ENV_FILE" <<EOF
# Med-Audit Docker 环境变量
# !! 重要: 请保存此文件，SECRET_KEY 用于解密 config.json 中的密文 !!
JWT_SECRET_KEY=${JWT_KEY}
SECRET_KEY=${SEC_KEY}
ENVIRONMENT=production
ALLOWED_ORIGINS=http://${SERVER_IP}:8000
APP_DB_TYPE=sqlite
APP_ORACLE_HOST=10.255.255.20
APP_ORACLE_PORT=1521
APP_ORACLE_SERVICE_NAME=orcl
APP_ORACLE_USERNAME=
APP_ORACLE_PASSWORD=
EOF
    info ".env generated (random keys)"
    warn "Please backup $ENV_FILE - needed to decrypt Oracle password!"
    warn "If you want Oracle as application DB, edit APP_DB_TYPE and APP_ORACLE_* in $ENV_FILE before first start"
else
    info ".env already exists, keeping it"
fi

# ---- [4] 启动容器 ----
info "[4/4] Starting container..."

docker stop med-audit 2>/dev/null || true
docker rm med-audit 2>/dev/null || true

docker run -d \
    --name med-audit \
    --restart unless-stopped \
    -p 8000:8000 \
    -v "$DATA_DIR":/app/data \
    -v "$CONFIG_DIR":/app/config \
    -v "$LOGS_DIR":/app/logs \
    --env-file "$ENV_FILE" \
    med-audit:latest

info "Waiting for service to start..."
for i in $(seq 1 15); do
    if curl -sf http://localhost:8000/api/health >/dev/null 2>&1; then
        break
    fi
    sleep 2
done

if curl -sf http://localhost:8000/api/health >/dev/null 2>&1; then
    SERVER_IP=$(hostname -I | awk '{print $1}')
    echo ""
    echo "============================================================"
    echo "  [DONE] Docker deploy success!"
    echo "============================================================"
    echo ""
    echo "  Access  : http://${SERVER_IP}:8000"
    echo "  API Doc : http://${SERVER_IP}:8000/docs"
    echo "  Health  : http://${SERVER_IP}:8000/api/health"
    echo ""
    echo "  Login   : admin / admin123"
    echo ""
    echo "  Commands:"
    echo "    View logs : docker logs -f med-audit"
    echo "    Stop      : docker stop med-audit"
    echo "    Restart   : docker restart med-audit"
    echo "    Upgrade   : docker load -i new-image.tar && docker stop med-audit && docker rm med-audit && bash docker_deploy.sh"
    echo "============================================================"
else
    echo ""
    echo "[ERROR] Service not responding. Check logs:"
    echo "  docker logs med-audit"
    exit 1
fi
