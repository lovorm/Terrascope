#!/usr/bin/env bash
# 「见山Terrascope」P0 服务部署脚本（Ubuntu 22.04+ / Debian 12+，SQLite 起步）
# 用法：在项目 p0-server 目录执行 sudo bash deploy/deploy.sh
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "请使用 sudo 执行：sudo bash deploy/deploy.sh" >&2
  exit 1
fi

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_USER="terrascope"
SERVICE_NAME="terrascope-api"
ENV_FILE="${APP_DIR}/.env"
UNIT_SRC="${APP_DIR}/deploy/terrascope-api.service"
UNIT_DST="/etc/systemd/system/${SERVICE_NAME}.service"

echo "==> 1/6 安装系统依赖"
apt-get update
apt-get install -y python3 python3-venv python3-pip

echo "==> 2/6 创建运行用户与目录权限（${APP_USER}）"
if ! id "${APP_USER}" >/dev/null 2>&1; then
  useradd --system --create-home --shell /usr/sbin/nologin "${APP_USER}"
fi
chown -R "${APP_USER}:${APP_USER}" "${APP_DIR}"

echo "==> 3/6 安装 Python 依赖（requirements.txt 白名单）"
sudo -u "${APP_USER}" python3 -m venv "${APP_DIR}/.venv"
sudo -u "${APP_USER}" "${APP_DIR}/.venv/bin/pip" install -r "${APP_DIR}/requirements.txt"

echo "==> 4/6 检查生产环境变量"
if [[ ! -f "${ENV_FILE}" ]]; then
  echo "缺少 ${ENV_FILE}；请先写入至少 ADMIN_TOKEN=<强随机令牌> 后重跑" >&2
  exit 1
fi
set -a
# shellcheck disable=SC1090
. "${ENV_FILE}"
set +a
if [[ -z "${ADMIN_TOKEN:-}" ]] || [[ "${ADMIN_TOKEN}" == "change-me-in-env" ]]; then
  echo "ADMIN_TOKEN 不能为空，也不能使用默认值 change-me-in-env" >&2
  exit 1
fi
chmod 600 "${ENV_FILE}"
chown "${APP_USER}:${APP_USER}" "${ENV_FILE}"

echo "==> 5/6 配置 systemd"
install -m 644 "${UNIT_SRC}" "${UNIT_DST}"
systemctl daemon-reload
systemctl enable --now "${SERVICE_NAME}"
systemctl restart "${SERVICE_NAME}"

echo "==> 6/6 健康检查（本机回环）"
for attempt in $(seq 1 15); do
  if curl -fsS http://127.0.0.1:8000/health >/dev/null; then
    echo "部署完成：服务已监听 127.0.0.1:8000"
    echo "后续操作：nginx 反代 80/443，或临时开放 8000 端口进行联调"
    exit 0
  fi
  sleep 1
done

echo "健康检查失败，请查看日志排障：journalctl -u ${SERVICE_NAME} -n 100 --no-pager" >&2
systemctl status "${SERVICE_NAME}" --no-pager || true
exit 1
