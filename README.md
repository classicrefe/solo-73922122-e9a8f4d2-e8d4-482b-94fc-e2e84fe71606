# 旧装船磅单入仓 API

用 FastAPI + SQLite 处理不同地磅的重量原文。逗号和点号在同一批中只有两种统一格式：

- `DOT_DECIMAL_COMMA_THOUSANDS`：`.` 为小数点，`,` 为千分位，例如 `1,234.567`；
- `COMMA_DECIMAL_DOT_THOUSANDS`：两者对调，例如 `1.234,567`。

重量原文以**吨**给出，最多三位小数，因此可无损转成整数**公斤**；各舱核定总重也使用整数公斤。

## 1. 启动

```bash
docker compose up --build
```

启动后：

- Swagger 文档：<http://localhost:8000/docs>
- 健康检查：<http://localhost:8000/health>
- SQLite 数据库保存在 Compose 命名卷 `gsb-sqlite-data` 的 `/data/weights.db`。

本机不用 Docker 时：

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## 2. 在 `/docs` 中试报送、更正和取数

Swagger 的请求体已带 `DEMO-001` 示例。也可以使用仓库中的 JSON 文件。

### 2.1 报送整船磅单

调用 `POST /ships`，使用 `examples/registration.json`：

```bash
curl -i -X POST http://localhost:8000/ships \
  -H 'Content-Type: application/json' \
  --data-binary @examples/registration.json
```

该示例中：

- 1 舱核定 `1,001,000 kg`；
- 第 1 行 `1.000` 在两种格式下分别是 `1,000 kg` 或 `1,000,000 kg`；
- 第 3 行 `1,000` 恰好给出相反的两个值；
- 整船总重允许 `(点格式, 点格式)` 和 `(逗号格式, 逗号格式)` 两组解释，因此第 1、3 行仍待查；
- 第 2 行 `5` 在所有解释中都是 `5,000 kg`，可直接供出。

关键响应：

```json
{
  "revision": 1,
  "supplied_rows": [{"line_no": 2, "hold_no": 2, "kg": 5000}],
  "pending_line_nos": [1, 3],
  "holds": [
    {"hold_no": 1, "certified_total_kg": 1001000, "supplied_kg": 0, "remaining_kg": 1001000},
    {"hold_no": 2, "certified_total_kg": 5000, "supplied_kg": 5000, "remaining_kg": 0}
  ]
}
```

### 2.2 先试无解更正，确认旧数据保留

`examples/impossible_correction.json` 把 1 舱改成 `999 kg`，没有任何格式组合能同时满足两舱：

```bash
curl -i -X PATCH http://localhost:8000/ships/DEMO-001/holds \
  -H 'Content-Type: application/json' \
  --data-binary @examples/impossible_correction.json
```

返回 `422`，错误码为 `no_feasible_interpretation`。随后 `GET /ships/DEMO-001` 仍是 `revision=1`、原舱重、原待查行和原供数。该示例不带 `expected_revision`，因此即使已经成功更正过，也仍会先按当前舱重求解并返回无解，而不是 revision 冲突。

### 2.3 提交有效更正并取数

可批量调用：

```bash
curl -i -X PATCH http://localhost:8000/ships/DEMO-001/holds \
  -H 'Content-Type: application/json' \
  --data-binary @examples/correction.json
```

也可在 `/docs` 调用单舱接口 `PATCH /ships/{ship_code}/holds/{hold_no}`：

```bash
curl -i -X PATCH http://localhost:8000/ships/DEMO-001/holds/1 \
  -H 'Content-Type: application/json' \
  --data '{"certified_total_kg":2000}'
```

当 1 舱改为 `2,000 kg` 后，只有“第 1 批用点小数、第 2 批用逗号小数”的组合可行，因此第 1、3 行也成为固定明细：

```json
{
  "revision": 2,
  "pending_line_nos": [],
  "supplied_rows": [
    {"line_no": 1, "kg": 1000},
    {"line_no": 2, "kg": 5000},
    {"line_no": 3, "kg": 1000}
  ],
  "holds": [
    {"hold_no": 1, "certified_total_kg": 2000, "supplied_kg": 2000, "remaining_kg": 0},
    {"hold_no": 2, "certified_total_kg": 5000, "supplied_kg": 5000, "remaining_kg": 0}
  ]
}
```

再次取数：

```bash
curl http://localhost:8000/ships/DEMO-001
# 同义路径：/ships/DEMO-001/allocation 或 /ships/DEMO-001/supply
```

响应包含：

- `supplied_rows`：所有可行整船解释中重量固定的行、公斤数及固定原因；
- `pending_line_nos`：仍需人工核查的行号；
- `holds[].remaining_kg`：核定总重扣除本次固定明细后的余量；
- `batches[].possible_formats`：该批在可行解释中可能出现的格式，便于排查。

`examples/correction.json` 带 `expected_revision=1`，用于演示乐观版本检查；如果已执行过其它更正，请把它改成 `GET` 到的当前 `revision`，或在请求中省略该字段。

## 3. HTTP 接口

| 方法与路径 | 用途 |
| --- | --- |
| `POST /ships` | body 中带 `ship_code`，一次登记整船 |
| `POST /ships/{ship_code}/intake` | 路径指定船名登记 |
| `PUT /ships/{ship_code}` | 同上的 PUT 别名 |
| `GET /ships` | 船舶摘要列表 |
| `GET /ships/{ship_code}` | 取固定明细、待查行号、舱重余量 |
| `GET /ships/{ship_code}/allocation` | 取数别名 |
| `PATCH /ships/{ship_code}/holds/{hold_no}` | 更正单个舱重 |
| `PATCH /ships/{ship_code}/holds` | 批量更正舱重 |
| `PUT /ships/{ship_code}/hold-weights` | 批量更正的 PUT 别名 |
| `POST /ships/{ship_code}/corrections` | 更正的 POST 别名 |
| `GET /health` | 健康检查 |

为便于旧报文接入，schema 还接受常见别名字段，例如 `line_number/row_no`、`hold`、`weight/tonnage/weight_tonnes`、`hold_weights` 映射、顶层 `rows` 以及行内 `batch_no`。标准字段仍以 `/docs` schema 为准。

## 4. 实现要点

### 4.1 精确解析

`app/parsing.py` 不使用浮点：

1. 按选定格式校验小数分隔符和最多三位小数；
2. 校验千分位分组；
3. 删除千分位；
4. 整数吨乘 1000，小数部分补齐三位后加入。

如果一个原文在两种格式下都合法，就保留两个候选公斤数；如果只在一种格式下合法，该批实际上被原文约束为该格式。

### 4.2 不穷举整船格式组合

每批只有两个格式选项。24 批的整船笛卡尔组合最多为：

```text
2^24 = 16,777,216
```

`app/solver.py` 使用 meet-in-the-middle：

1. 将 24 批拆成两个最多 12 批的半边；
2. 每边最多展开 `2^12 = 4096` 个“各舱贡献向量”；
3. 用哈希表连接左向量 `L` 和右向量 `T - L`，其中 `T` 是各舱核定总重；
4. 连接成功时，用位掩码记录每个批在哪些可行整船解释中出现过哪种格式。

因此它能精确回答“某批的某个格式是否参与至少一个可行解”，而不构造整船笛卡尔积。测试中还有一个小规模暴力枚举 oracle，随机比较了 300 组数据。

行是否可供的判定：

- 两种本地解释公斤数相同：任何情况下都固定，直接供出；
- 公斤数不同，但该批被所有可行整船解释强制为唯一格式：按该格式供出；
- 该批在可行解释中仍有两种格式且行值不同：列入待查。

### 4.3 事务、更正和并发

- 登记表为 `ships / holds / batches / weight_rows`；当前有效供数快照存于 `ships.allocation_json`。
- 报送和更正都先完成解析与求解，再执行 `BEGIN IMMEDIATE` 短事务写入，避免在长时间核对期间持有写锁。
- 更正成功时，舱重、revision 和新供数快照在同一 SQLite 事务中提交。
- 无解时在写事务前返回 `422`；提交或写入失败时回滚，旧舱重和旧 `allocation_json` 保持不变。
- 锁按 `ship_code` 区分（`app/concurrency.py`），核对 A 船不会阻塞 B 船入仓。FastAPI 的普通 `def` 端点在线程池中执行，不会阻塞事件循环。
- SQLite 使用 WAL 和 `busy_timeout=15s`。Compose/镜像默认单 Uvicorn worker；若多进程部署，`expected_revision` 与库内 revision 检查会返回 `409`，防止同船并发更正静默覆盖。

## 5. 自测结果

下列结果来自当前工作区（Python 3.11，临时依赖目录；命令等价于安装 `requirements-dev.txt` 后执行）。

### 5.1 自动化测试

```text
26 passed, 1 warning in 1.78s
```

覆盖：

- 两种数字格式、三位小数、非法原文和负数；
- MITM 求解器与小规模暴力枚举结果一致；
- `/docs`、健康检查、报送、取数、无解更正保留旧数据、成功更正、revision 冲突、重复船号、404；
- 模拟 commit 失败后旧舱重和供数不变；
- 用屏障让 A 船停在核对函数中，验证 B 船仍可完成入仓；
- 24 批、12 舱、2000 行上限数据。

### 5.2 上限基准

```text
whole-ship Cartesian combinations avoided: 2**24 = 16,777,216
dense half states: left=4,096, right=4,096 (theoretical max 4,096 each)
max rows evaluation: 30.1 ms, supplied=2000
dense solver: 114.1 ms, batch_choice_sets=24
```

### 5.3 真实 Uvicorn HTTP 抽测

已在本机用 Uvicorn 临时端口真实启动并实测最终流程：

- `GET /health` → `200 {"status":"ok"}`
- `GET /docs` → `200`，HTML 含 Swagger UI
- `POST /ships`（示例）→ `201`，待查 `[1,3]`
- `PATCH .../holds` 改为 `999 kg` → `422 no_feasible_interpretation`
- 随后 `GET /ships/DEMO-001` → `200`，仍为 `revision=1` 和原余量
- `PATCH .../holds/1` 改为 `2000 kg` → `200 revision=2`，三行全部供出
- `GET /openapi.json` → `200`，包含报送、单舱/批量更正和取数路径

另一次真实 HTTP 并发抽测中，2000 行上限船 `MAXHTTP` 与普通小船 `OTHERHTTP` 同时报送，分别得到 `201`（约 `138 ms`）和 `201`（约 `55 ms`）；确定性的“核对期间 B 船完成”时序由线程屏障测试覆盖。

## 6. 设计假设与未完成项

1. **千分位按标准三位分组校验。** 例如 `12,34` 只会被当作逗号小数 `12.34 t`，不会把逗号当合法千分位。若真实旧磅单存在不规范分组但仍要求机械删除分隔符，需要调整 `app/parsing.py` 的严格度。
2. **当前环境没有 Docker/Podman 守护进程**，因此这里实际验证了 Compose YAML 解析、Dockerfile 依赖可安装、Uvicorn 真实启动和 HTTP 关键流程，但未能在该沙箱内执行 `docker compose up --build`。Dockerfile 使用标准 `python:3.12-slim`、固定依赖和普通健康检查。
3. 服务没有鉴权，默认面向可信内网；如需公网使用，应在反向代理或应用层增加认证、审计和传输加密。
4. `GET` 读取最近一次登记/更正时生成的供数快照；不会把“取数”本身写成一次已发货扣减。当前需求没有要求独立的发货确认或多次部分提货状态。
5. 没有实现删除船舶接口；重复 `POST /ships`（相同 `ship_code`）或重复 `POST /ships/{ship_code}/intake` 返回 `409`，应使用更正接口改变舱重。
