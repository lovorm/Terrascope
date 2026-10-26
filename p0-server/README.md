# 「见山Terrascope」P0 数据管道 + 数字底座 API 骨架

对应《云端优先·可直接落地精简提示词》第三节 P0：**纯云端、无硬件依赖、全免费技术栈**。

## 架构

```
Open-Meteo(免费无密钥) ─┐
和风天气(免费订阅)     ─┼→ services/ → ingest(降频+去重) → SQLite/PostgreSQL → FastAPI
生态环境部空气质量     ─┘                                     ↓
自建 ESP32(增量拓展)  → /api/devices 预留协议(设备ID/JSON上报/OTA)   ECharts Web / 小程序
```

- **降频防超限**：`config.MIN_INTERVAL_MIN` 按源控制最小抓取间隔（Open-Meteo 60min / 和风 30min），窗口内自动跳过
- **幂等去重**：`(源, 站点, 指标, 时间)` 唯一约束，重复抓取不产生脏数据
- **全程溯源**：每条观测带 `source_key / fetched_at`；`GET /api/sources` 返回 9 类数据源元数据（与申报书「数据合规与来源声明」一致）
- **观山指数**：P1 模型版（lr-v1，逻辑回归）优先，P0 规则版兜底，接口契约不变
- **ESP32 预留协议**：注册 → `X-Device-Key` 认证上报 → OTA 版本协商，硬件到位即插即用、云端零修改

## P1 · 观山指数回测模型（已实装）

```bash
python -c "from app.p1 import mountain_model; print(mountain_model.train(days=92))"
# 或线上触发：curl -X POST "$SERVER/api/admin/train-mountain-index" -H "X-Admin-Token: ..."
```

- **标签口径（推算依据）**：08:00–18:00 能见度中位数 ≥15000m 记「可观山」；标签源为 Open-Meteo
  预报系统存档能见度（`past_days` 上限 92 天；归档接口实测不支持能见度变量，扩大窗口列 P1.1 接 ERA5/CDS）
- **特征**：白天云量均值 / 全天累计降水 / 白天湿度均值 / 白天最大风速（预报同样可得，线上线下同口径）
- **评估**：walk-forward TimeSeriesSplit(5) 池化样本外指标，混淆矩阵如实写入
  `data/model/mountain_index_meta.json` 并经 `/api/dashboard/mountain-index` 的 `model_meta` 对外公布
- **模型产物（joblib + meta）不入版本库**：克隆后接口走 `rule-v0` 规则版兜底属预期行为；
  部署后执行上方 train 命令生成模型文件，接口自动切换 `lr-v1`
- **实测记录（2026-09-19，雨季窗口）**：72 有效天 / 正值率 5.6% / 样本外 48 天：
  accuracy 0.917、precision 0.333、recall 0.333——样本小且季节偏斜，P2 上线众包打卡后用
  游客真实目击校准阈值与标签，不对外夸大指标

## 快速开始（本地，零成本）

```bash
pip install -r requirements.txt
cp .env.example .env          # 和风 Key 可留空，自动跳过该源
python -m app.ingest          # 真实抓取丽江两坐标（玉龙雪山/拉市海）
uvicorn app.main:app --reload # 启动 API，文档 http://127.0.0.1:8000/docs
pytest tests/ -v              # 冒烟测试（含真实 Open-Meteo 调用）
```

> 模型产物（joblib + meta）不入库：克隆后接口先走 `rule-v0` 规则版兜底；
> 部署后执行 P1 train 命令生成模型文件，接口自动切换 `lr-v1`。

## 核心接口

| 方法/路径 | 说明 |
|-----------|------|
| `GET /api/dashboard/mountain-index` | 未来 3 天观山指数（规则版，含数据源溯源块） |
| `GET /api/dashboard/latest?metric=&site=` | 最新观测序列（带溯源字段） |
| `GET /api/sources` | 9 类数据源注册表：来源/许可/频率/入库行数/最近数据时间 |
| `POST /api/devices/register` | ESP32 设备注册（device_id + key，key 仅存 sha256） |
| `POST /api/devices/{id}/observations` | 设备批量上报（Header `X-Device-Key`） |
| `GET /api/devices/{id}/ota` | OTA 版本协商（P2 提供固件包） |
| `POST /api/admin/ingest` | 采集触发（Header `X-Admin-Token`），供 Actions 定时调用 |
| `GET /api/admin/logs` | 采集日志：每源成功/失败/行数，管道状态对外可见 |

ESP32 上报示例（P0 即可联调）：

```bash
curl -X POST http://127.0.0.1:8000/api/devices/esp32-001/observations \
  -H "X-Device-Key: <注册时密钥>" -H "Content-Type: application/json" \
  -d '[{"metric":"co2_ppm","value":652,"unit":"ppm"}]'
```

## 生产部署（腾讯云学生轻量服务器，年成本 ≤300 元）

1. 服务器装 Python 3.10+、PostgreSQL（或继续用 SQLite 单机跑，P0 足够）
2. `YUNQI_DATABASE_URL=postgresql+psycopg2://...` 切库，其余零改动
3. systemd 常驻：`uvicorn app.main:app --host 0.0.0.0 --port 8000`
4. GitHub 仓库 Secrets 配置 `YUNQI_SERVER`（域名）与 `YUNQI_ADMIN_TOKEN`，`.github/workflows/ingest.yml` 每 2 小时自动采集；服务端降频二次兜底
5. 域名备案后挂 Nginx + 免费证书，即得公开演示链接（P0 产出物）

## 运维（Actions 定时任务）

服务器侧部署由 `deploy/README.md` 负责（systemd、`.env`、健康检查）；本节只负责 GitHub Actions 侧的定时任务配置与告警。

### Secrets 配置

1. 打开仓库 **Settings → Secrets and variables → Actions**。
2. 新增 `TERRASCOPE_SERVER_URL`：值为服务地址，如 `https://terrascope.example.com`（Nginx 反代后）或临时联调的 `http://<服务器IP>:8000`。
3. 新增 `ADMIN_TOKEN`：必须与服务器 `.env` 中的 `ADMIN_TOKEN` 一致。
4. Secrets 未配置时，两个 workflow 会打印「secrets 未配置，跳过」并正常退出，不会产生每小时红屏邮件。

### 手动验证

1. 打开仓库 **Actions** 页面。
2. 左侧选中 **Ingest**，点击 **Run workflow** 手动触发，确认任务绿色通过、`/api/admin/logs` 行数增长。
3. 左侧选中 **Retrain**，同样手动触发一次，确认 summary 中指标齐全、`/api/dashboard/mountain-index` 返回 `lr-v1`。

### 告警、暂停与恢复

- 任务失败时，GitHub 默认向仓库所有者发送邮件；如需其他成员接收，可在 **Actions → 对应 workflow → Subscribe** 订阅通知。
- 暂停：进入 **Actions → 对应 workflow → ⋯ → Disable**。
- 恢复：同一菜单选择 **Enable**。
- 若文档间存在重复表述，以本节为准。

## 环境变量

| 变量 | 必填 | 说明 |
|------|------|------|
| `YUNQI_DATABASE_URL` | 否 | 默认 SQLite；带 `YUNQI_` 前缀避免与宿主环境全局 `DATABASE_URL` 冲突 |
| `QWEATHER_API_KEY` | 否 | 和风天气免费订阅 Key，缺省自动跳过并记日志 |
| `ADMIN_TOKEN` | 是(生产) | 管理触发令牌，与 Actions Secret 一致 |

## 路线衔接

- **P1**：观山指数回测模型（本库 open-meteo 历史数据即为训练集，目标准确率 ≥75% + 混淆矩阵如实公布）；Sentinel-2/Landsat 时序（`services/` 增文件，路由复用）；小程序直连本 API
- **P2**：众包打卡表 + 异常告警（基于 `observations` 时序滑动窗口）+ OTA 固件分发 + 日志监控加固

## 进度留痕

- **2026-10-25 T-A1**：`/api/dashboard/mountain-index` 先查最近 7 天观测；窗口为空时回退全表并返回 `note` 提示，避免采集管道停跑后接口静默返回空列表。
- **2026-10-25 T-A2**：新增 `deploy/` 服务器部署产物（一键脚本、systemd 单元、部署清单），SQLite 起步，仅监听本机 127.0.0.1:8000，公网暴露建议经 Nginx 反代。
