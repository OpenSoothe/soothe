# 内存泄漏调查日志（IG-477 后续）

**创建日期**: 2026-06-11  
**状态**: 进行中 — agentic 查询路径仍有线性 RSS 增长直至 OOM  
**关联文档**: [memory-leak-root-cause-analysis.md](./memory-leak-root-cause-analysis.md), [IG-477-validation-results.md](./IG-477-validation-results.md), [soothed-daemon-memory-leak-diagnosis.md](./soothed-daemon-memory-leak-diagnosis.md)

---

## 1. 问题背景

### 1.1 现象

在生产/本地 Docker 部署（`deploy/docker-compose.yml`，内存上限 4 GiB）中，`soothed` 容器在执行 **agentic 类查询**（含工具调用、子 agent 流式 LLM）时出现：

| 指标 | 典型值 |
|------|--------|
| 空闲 RSS | ~196–215 MiB |
| 峰值 RSS | **~3.9–4.0 GiB**（触顶 cgroup limit） |
| 增长率 | **~400 MiB / 2 秒**（线性，自 execute 阶段约第 9 秒起） |
| OOM 后 | RSS 跌至 ~11–200 MiB，`RestartCount += 1` |
| 查询结果 | CLI exit 0（查询往往在 OOM 前后完成） |

历史版本（v0.6.1，IG-477 前）：RSS 从 ~1 GB 持续增至 ~24 GB。

### 1.2 目标

| 目标 | 标准 |
|------|------|
| 简单 query 内存有界 | 峰值 RSS **< 2 GiB** |
| 无 OOM | `RestartCount` 不增加 |
| 功能正确 | `soothe --no-tui -p "list dir of current workspace"` exit 0 |

### 1.3 测试命令

```bash
# 构建本地镜像（仓库根目录）
docker build -f packages/soothe-daemon/Dockerfile.local -t soothed:0.6.3-fixed3 .

# 启动栈
cd deploy && docker compose up -d

# 执行 query（workspace 来自 cwd，末尾 `.` 不是合法 CLI 参数）
cd /path/to/soothe
.venv/bin/soothe --no-tui -p "list dir of current workspace"

# 自动化测试 + 采样
./scripts/query_memory_loop_test.sh
```

当前镜像 tag：`soothed:0.6.3-fixed4`（见 `deploy/docker-compose.yml`）。

---

## 2. 调查方法

### 2.1 分层排除法

1. **队列/桥接层**：`/api/v1/memory?mode=queues`、ResponsePusher、thread_pool 队列深度  
2. **传输层**：`event_queue`、WebSocket 慢消费者  
3. **QueryEngine**：`full_response` 累积、ThreadLogger buffer  
4. **Agent 执行层**：SootheRunner / LangGraph `astream`、execute vs quiz 路径对比  
5. **环境因子**：tracemalloc 开销、工作区体量、容器 memory limit 缩放实验  

### 2.2 工具与脚本

| 工具 | 用途 | 路径 |
|------|------|------|
| `query_memory_loop_test.sh` | CLI query + docker stats 采样 + 目标判定 | `scripts/query_memory_loop_test.sh` |
| `query_mem_loop_stats.csv` | 每次测试的 RSS 时间序列 | `scripts/query_mem_loop_stats.csv` |
| `docker_memory_test.py` | WebSocket + HTTP memory API | `scripts/docker_memory_test.py` |
| `live_memory_test.py` | 长时间 docker stats | `scripts/live_memory_test.py` |
| Daemon memory API | RSS、队列、大对象 | `GET /api/v1/memory?mode=daemon\|queues\|large` |
| `run_hp002_memray.sh` | HP-002 编排：API key 注入、venv memray 安装 | `scripts/run_hp002_memray.sh` |

### 2.3 对比实验设计

| 实验 | 目的 |
|------|------|
| `say hello` vs `list dir` | 区分 quiz 快路径 vs agentic 全路径 |
| 4 GiB vs 16 GiB limit | 判断是否为“顶到上限”的假泄漏 |
| profiling on/off | 排除 tracemalloc 放大 |
| thread_pool vs worker_pool | 进程隔离是否改变容器级 OOM |
| 容器内单进程 SootheRunner | 排除 daemon+worker 叠加（需 API key 与独立 run） |

### 2.4 判定标准（单次测试）

- **通过**：Peak RSS ≤ 2048 MiB，`RestartCount` 不变，query exit 0  
- **失败**：Peak RSS > 2048 MiB 或 `RestartCount` 增加  

---

## 3. 调查进展

### 3.1 时间线

| 日期 | 进展 |
|------|------|
| 2026-06-10 | IG-477 验证：bounded queue 在 idle/轻负载下有效（~203 MiB 稳定） |
| 2026-06-11 | 补充修复：ResponsePusher 信号量背压、pool_runner 有界队列、LoopState 清理 |
| 2026-06-11 | 发现 `full_response_chars` 缺少 `nonlocal` 导致 query 失败，已修 |
| 2026-06-11 | 确认 `say hello` 稳定 ~215 MiB；`list dir` 仍线性增至 OOM |
| 2026-06-11 | 16 GiB limit 实验：峰值 ~8096 MiB 仍 OOM → **泄漏与 limit 成比例，非固定顶满 4G** |
| 2026-06-11 | 排除 tracemalloc 为主因（关闭后仍 OOM） |
| 2026-06-11 | 本文档建立，下一步：execute 阶段 heap 剖析 |
| 2026-06-11 | HP-001：本地 tracemalloc（60 chunks），execute 段 RSS ~725 MiB；完整 OOM 路径待 HP-002 |

### 3.2 测试结果摘要（迭代 6–13，镜像 fixed3）

| 迭代 | Query | Limit | Peak RSS | RestartCount | Query | 备注 |
|------|-------|-------|----------|--------------|-------|------|
| 6 | list dir | 4G | 4034 MiB | 1 | OK | synthesis LLM 直连后仍 OOM |
| 8 | list dir | 4G | 3731 MiB | 1 | OK | 不传播 updates chunk |
| 10 | list dir | 4G | 3846 MiB | 1 | OK | stream_mode 仅 messages |
| 11 | list dir | 4G | 3867 MiB | 1 | OK | durability=exit |
| 12 | list dir | 16G | **8096 MiB** | 1 | OK | 线性增长至 ~8G |
| 13 | list dir | 4G (worker_pool) | 4075 MiB | 1 | OK | 进程隔离未消除容器级 OOM |
| 14 | list dir | 4G (fixed4: 去掉 updates stream_mode) | **3811 MiB** | 1 | OK | **~400 MiB/2s 未变**；updates 非唯一根因 |
| — | say hello | 4G | **214 MiB** | 0 | OK | quiz 路径无泄漏 |

**RSS 采样形态（典型 list dir）**：

```
0–7s:   ~200 MiB   （初始化 / plan / 工具启动）
9s+:    +~400 MiB/2s 线性增长
28–46s: 触顶 OOM → RSS 骤降 → 恢复 ~195 MiB
```

### 3.3 已排除的假设

| 假设 | 证据 |
|------|------|
| response_queue 无界（IG-477 主因） | 队列深度恒为 0；IG-477 后 idle 稳定 |
| call_soon_threadsafe 无限累积 | 信号量/计数器限制后仍 OOM |
| event_queue (10000) 堆积 | 有界 1000；headless 单客户端 |
| tracemalloc 导致 | `SOOTHE_MEMORY_PROFILING_ENABLED=false` 仍 OOM |
| synthesis CoreAgent 图 | 改 direct `llm.astream` 后仍 OOM |
| updates/custom stream 向下游传播 | 过滤/缩小 stream_mode 后仍 OOM |
| LangGraph durability=sync 每步 checkpoint | `durability=exit` 后仍 OOM |
| subgraphs=True 命名空间膨胀 | `subgraphs=False` 后仍 OOM |
| ls 递归读全仓库 | deepagents `ls` 非递归；顶层 ~20 项 |

### 3.4 当前 leading hypothesis

**Agentic Execute 阶段**（CoreAgent + 子 agent 工具流式 LLM，非 quiz 路径）存在 **进程内状态线性膨胀**：

- 约每 2 秒分配 **~400 MiB** 且 **直至进程被 OOM killer 终止才释放**
- 与容器 memory limit 缩放实验一致（4G→~4G 峰值，16G→~8G 峰值）
- 可能位置（待 heap 证实）：
  1. LangGraph `CompiledStateGraph.astream` 的 **messages channel** 在 token 流期间持续增长
  2. **AsyncPostgresSaver** 序列化缓冲区（即使 `durability=exit`，in-memory state 仍增长）
  3. **deepagents / 子 agent** 中间件在流式阶段持有大对象
  4. **LLM HTTP 客户端** 流式读缓冲（DashScope/OpenAI 兼容层）

**次要因素**：

- 工作区 `soothe` 在容器内 **6.1 GiB / 167k 文件**（`find … | wc -l`），可能放大 agent 上下文/索引类操作，但 `ls` 本身非递归。

### 3.5 已合入的代码修复（IG-477 补充）

| 文件 | 变更 |
|------|------|
| `response_bridge.py` | `threading.Semaphore(100)` 阻塞 worker，真正背压 |
| `query/engine.py` | `full_response` 100KB 上限 + `nonlocal` |
| `pool_runner.py` | mp/asyncio queue `maxsize=100`，put 超时 |
| `executor.py` | 不 yield 非 interrupt 的 `updates`；`durability="exit"`；**HP-003: `stream_mode` 仅 `messages+custom`，interrupt 改 `aget_state`** |
| `synthesis.py` | 合成阶段 `llm.astream` 直连 |
| `_core.py` | `astream(..., durability=...)` |
| `schemas.py` | `clear_goal_state` 清理 skill/MCP 缓存 |
| `session.py` | `event_queue` maxsize 1000 |
| `deploy/.env` | `SOOTHE_MEMORY_PROFILING_ENABLED=false` |

---

## 4. 下一步计划

### 4.1 P0：Native 内存定位（HP-007）

1. execute 流期间采集 **`/proc/<pid>/smaps_rollup`** 或 `memray run --native`（worker 线程 attach）
2. 对比 **Postgres checkpointer on/off**（临时 `MemorySaver`）对 cgroup 峰值的影响
3. 对比 **HTTP 流式客户端**（禁用 `stream_usage`、缩小 read buffer）  
4. 记录到 §5

```bash
# 容器内 smaps 采样（execute 第 10–30s）
docker exec deploy-soothed-1 bash -c 'PID=$(pgrep -f soothe_daemon); grep -E "Rss|Pss" /proc/$PID/smaps_rollup'

./scripts/run_hp005_incontainer.sh   # 同 cgroup exec 对照
```

### 4.2 P1：Daemon vs Runner 对比（已完成 HP-004/005）

- 更小 workspace（空目录）对比 167k 文件仓库  
- 强制 `LEDGER_DIRECT` 跳过 synthesis，观察峰值是否下降  
- 单步 execute（禁用 parallel / 限制 tool 输出大小）  

### 4.3 P2：针对性修复（待 P0 结果）

- 若 messages channel：自定义 reducer / 流式阶段不保留全量 chunk  
- 若 checkpointer：execute 流使用 `MemorySaver` 或 ephemeral thread 不写 PG  
- 若 HTTP 缓冲：调整 langchain 流式 chunk 大小或禁用 `stream_usage`  

### 4.4 验收

重复 `./scripts/query_memory_loop_test.sh` 直至：

- Peak RSS < 2048 MiB  
- RestartCount = 0  
- 连续 3 次 list dir query 通过  

---

## 5. Heap 剖析记录（待填）

| 运行 ID | 日期 | 环境 | 条件 | 峰值 RSS | Top allocator #1 | Top allocator #2 | 结论 |
|---------|------|------|------|----------|------------------|------------------|------|
| HP-001 | 2026-06-11 | 本地 host, config.dev.yml | 60 chunks 后停止 | 流中 ~708 MiB；cleanup 后 ~1898 MiB | `importlib` / anthropic vertex (~1.9 MB tracemalloc) | `numpy` import (~1 MB) | 流式阶段 RSS 已跳至 ~725 MiB（execute 起点）；**tracemalloc 对 import 敏感，需 memray 在容器内对完整 query 剖析** |
| HP-002 | 2026-06-11 | Docker 8g 隔离容器 + memray 1.19.3 | SootheRunner 直跑 list dir（50 chunks 后挂起，1.1 GiB bin） | 进程内 ~1456 MiB @ chunk 50；**无 daemon 级 400 MiB/2s** | `importlib` 71.9%（冷启动） | LangGraph `_execute_step_collecting_events` + `aget_state` 各 ~22% | **隔离 runner 线性暴涨弱于 daemon**；memray 证实 execute 流 + checkpointer 读状态是大头；**非 updates 下游传播问题** |
| HP-003 | 2026-06-11 | fixed4 daemon 4G | 去掉 `updates` stream_mode | **3811 MiB** | — | — | **无效**：RSS 曲线与 iter 6–13 相同（~400 MiB/2s） |
| HP-004 | 2026-06-11 | fixed5 daemon 4G | 二分 daemon 层：`drop_chunks` / `minimal` / 单项 bypass | **3777–4093 MiB** | — | — | **全部仍 OOM**；ThreadLogger/coalescer/broadcast/ResponsePusher **非主因** |
| HP-005 | 2026-06-11 | daemon 容器内 `docker exec` SootheRunner | 与 daemon 同 cgroup，daemon 空闲 | cgroup **3846 MiB @ 26s**；进程 psutil **~173 MiB @ chunk 50** | — | — | **进程 RSS ≪ cgroup RSS** → 主要为 **native / 非 Python 堆** 分配 |
| HP-006 | 2026-06-11 | 独立 4G 容器（无 daemon）SootheRunner | 同 deploy 网络 + PG | OOM @ ~30s；进程 psutil **~176 MiB @ chunk 50** | — | — | 与 HP-005 相同：**线性 cgroup 增长 + psutil 低估** |

### HP-004 详情

- **脚本**: `scripts/run_hp004_bisect.sh` → `scripts/hp004_results.csv`
- **结论**: 即使 `SOOTHE_DAEMON_HP004_DROP_CHUNKS=1`（worker 不向 main 推送 chunk）仍 OOM → 泄漏在 **worker 内 LangGraph 执行**，不在 daemon 主循环消费路径

### HP-005 / HP-006 详情

- **关键矛盾**: `psutil.Process.rss` 在 execute 流中仅 ~175 MiB，但 docker cgroup 仍 **~400 MiB/2s** 涨至 4 GiB 后 OOM
- 与 §3.3 tracemalloc 仅 ~0.9–14 MB 一致：**泄漏主体在 Python 堆外**（HTTP 读缓冲、LangGraph 原生层、glibc arena、PG 驱动等）
- HP-002（8 GiB 隔离容器）曾报告 chunk1 **1423 MiB** 进程 RSS — 可能与 **8g limit 下更晚 OOM / 不同采样时机** 有关，需用 `/proc/pid/smaps` 复核

### HP-002 详情

- **命令**: `./scripts/run_hp002_memray.sh`（修复：从 running container 补全 `DASHSCOPE_CP_API_KEY`，`ensurepip` + venv memray）
- **输出**: `scripts/hp002/heap_execute.bin`（1.1 GiB）、`memray_summary.txt`、`hp002_run.log`
- **观察**:
  - baseline 41.8 MiB → chunk 1 **1423 MiB**（agent 初始化）→ chunk 50 **1456 MiB**（43s，增长放缓）
  - 50 chunks 后进程 100% CPU 挂起 ~25 min（list-dir 工具/LLM 长任务），手动终止
  - memray top（按 Total Memory %）：`importlib` 71.9%；`create_chat_model` 23.7%；LangGraph `_execute_step_collecting_events` / `aget_state` 各 22.3%
- **与 daemon 差异**: 同 prompt 在 **daemon+thread_pool** 仍 ~400 MiB/2s 至 OOM；隔离 SootheRunner **无此线性段** → 泄漏可能含 **daemon 桥接层**（ResponsePusher / ThreadLogger / coalescer）或 **双线程同进程引用**

### HP-001 详情

- **命令**: `.venv/bin/python scripts/heap_profile_execute_query.py --max-chunks 60 --config config/config.dev.yml --workspace .`
- **输出**: `scripts/heap_execute_tracemalloc.json`
- **观察**:
  - chunk 2–60 期间 RSS **~706–726 MiB**（未继续线性暴涨，因提前 `--max-chunks 60` 终止）
  - execute 开始后 deepagents filesystem middleware 加载
  - tracemalloc top growth 含 `langgraph/pregel/_read.py`、`langchain_core/messages/utils.py`（tool calling 路径）
- **限制**: 本地运行非 Docker 4G cgroup；完整 query 未跑完；**不能代表 Docker 中 ~400 MiB/2s 至 OOM 的全貌**

### HP-002 计划（P0）

```bash
# 1. 停止 daemon，避免同 cgroup 竞争（可选）
docker compose -f deploy/docker-compose.yml stop soothed

# 2. 在镜像中安装 memray 并拷贝脚本（或 rebuild 临时层）
docker run --rm --network deploy_soothe-app \\
  -e DASHSCOPE_API_KEY -e DASHSCOPE_CP_API_KEY \\
  -v $(pwd)/deploy/config.yml:/app/config.yml:ro \\
  -v $(pwd)/scripts:/scripts:ro \\
  -m 4g soothed:0.6.3-fixed3 \\
  bash -c 'pip install -q memray && python /scripts/heap_profile_execute_query.py \\
    --config /app/config.yml --workspace /var/lib/soothe/workspaces/soothe'

# 3. 生成火焰图
memray flamegraph scripts/heap_execute.bin
```

---

## 6. 参考日志片段

Execute 阶段典型日志（list dir）：

```
[Execute] steps=1 mode=parallel max_parallel=2 tool_limit=15
[SubagentTool] ns=execute:… name=ls id=… preview=['LICENSE', 'uv.lock', …]
```

Quiz 对照（`say hello`）：无 Execute/SubagentTool，RSS 全程 ~214 MiB。

---

*本文档随调查更新；下次 milestone 后更新 §3 时间线与 §5 heap 表。*
