# T-A2 服务器部署清单（SQLite 起步）

## 适用环境

- Ubuntu 22.04+ / Debian 12+
- 服务器目录约定：`/opt/yunqi-naxi/p0-server`
- Python 3.10+（系统包即可，无需编译）
- 数据库：默认 SQLite，文件位于 `p0-server/data/yunqi.db`

## 一键部署

```bash
cd /opt/yunqi-naxi/p0-server
sudo bash deploy/deploy.sh
```

脚本动作：安装 `python3`/`venv`/`pip` → 创建 `terrascope` 系统用户 → 建立 `.venv` →
安装 `requirements.txt` → 校验生产环境变量 → 安装并启动 `terrascope-api.service` → 本机健康检查。

## 部署前必做

1. 将仓库放置到 `/opt/yunqi-naxi/p0-server`，或同步修改 `deploy/terrascope-api.service` 中的绝对路径。
2. 创建 `p0-server/.env`，至少写入：

```bash
ADMIN_TOKEN=强随机令牌
QWEATHER_API_KEY=可选_为空则自动跳过
YUNQI_DATABASE_URL=sqlite:////opt/yunqi-naxi/p0-server/data/yunqi.db
```

3. `.env` 权限应为 `600`，属主为 `terrascope`；部署脚本会自动处理。
4. 生成强随机令牌：`openssl rand -hex 32`。

## systemd 常用命令

```bash
systemctl status terrascope-api --no-pager
systemctl restart terrascope-api
journalctl -u terrascope-api -f
```

## 端口与防火墙

- systemd 默认仅监听 `127.0.0.1:8000`，建议由 Nginx 反代到 80/443 后再公网开放。
- 临时联调可开放 8000，但决赛演示前建议关闭直连。
- 云安全组需同步放行对应端口。

## 数据备份


```bash
# 每日备份 SQLite（建议 crontab）
0 3 * * * sudo -u terrascope sqlite3 /opt/yunqi-naxi/p0-server/data/yunqi.db \
  ".backup /opt/yunqi-naxi/backups/yunqi-$(date +\%F).db"
```

## 常见问题

- **健康检查失败**：`journalctl -u terrascope-api -n 100 --no-pager` 查看异常。
- **数据库权限**：`chown -R terrascope:terrascope data/`。
- **升级部署**：`git pull` 后重跑 `sudo bash deploy/deploy.sh`；脚本幂等，venv 已存在时只增量安装依赖。
- **切 PostgreSQL**：部署稳定后修改 `YUNQI_DATABASE_URL`，本任务不包含该变更。

## 验收清单

- `systemctl is-active terrascope-api` 输出 `active`
- `curl http://127.0.0.1:8000/health` 返回 `status: ok`
- `curl -H "X-Admin-Token: <token>" -X POST http://127.0.0.1:8000/api/admin/ingest` 有返回
- `curl http://127.0.0.1:8000/api/admin/logs` 日志持续增长
