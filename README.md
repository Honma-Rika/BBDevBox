# BBDevBox

以 CLI 命令完成任务、以独立 shell verification 判分的 CLI Agent Benchmark: BBDevBox。使用 **LangGraph ReAct harness**，支持 Docker / Podman / 可选 gVisor、实时事件监控、跨模型对比、主从 Agent 协作、SOP 记忆、上下文压缩和动态 prompt profile。

任务数据集与数据分析脚本位于 `data/`。历史评测结果、本次运行输出和本机配置保留在本地，通过 `.gitignore` 排除上传；新环境从 `examples/config.yaml` 创建自己的 `config.yaml`。

## 安装与第一次运行

Python 3.11+，正式评测另需 Docker 或 Podman。模型端点须支持原生 tool calling 和 chat completions 兼容接口。

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp examples/config.yaml config.yaml
# 编辑 config.yaml 的 model.name / base_url 等；密钥只通过环境变量传入。
export OPENAI_API_KEY='...'
bbdevbox run examples/smoke.yaml --config config.yaml
```

运行会立刻输出 `run_id`。另开终端：

```bash
bbdevbox serve
# 浏览器访问 http://127.0.0.1:8765
bbdevbox status --run RUN_ID --watch
```

`status --watch` 输出终端状态，并打印指定运行的网页链接，例如 `http://127.0.0.1:8765/?run=RUN_ID`。
网页默认跟随最新创建的运行；点击左侧运行或打开带 `?run=` 的链接会固定查看该运行，点击“跟随最新运行”恢复自动切换。切换时会清空旧指标，旧请求的迟到响应不会覆盖新选择。

`run`、`status`、`serve` 必须使用同一个 `--root`。页面顶部和服务启动输出均显示实际数据目录。举例：如果任务保存在 `runs`，用 `bbdevbox --root runs serve`；`bbdevbox --root runs/demo serve` 只会显示演示库。`--root` 是全局参数，放在子命令前。

无需密钥、Docker 的离线演示：

```bash
python examples/offline_demo.py
bbdevbox --root runs/demo serve
```

演示使用明确标注的 scripted model fixture，通过真实 LangGraph 和本地 shell 生成两组结果与 `runs/demo/comparison.html`；其分数不代表真实模型能力。`local` 会在宿主执行命令，只适用于明确受信的测试夹具，不能作为安全沙盒。

## 命令行参数完整说明

命令结构为 `bbdevbox [全局参数] 子命令 [子命令参数]`。每个参数只作用于所属命令；`workers`、模型、token 预算等通过 YAML 设置，不存在 `--workers`、`--model` 或 `--max-tokens` 命令行开关。以下默认值对应代码默认配置，`examples/config.yaml` 可以显式覆盖它们。

### 全局参数

| 参数 | 默认值 | 功能及意义 |
| --- | --- | --- |
| `--root PATH` | `runs` | SQLite 数据库、任务轨迹、构建日志、归档和 skills 的存储根目录。放在子命令前，例如 `bbdevbox --root runs/experiment-a serve`。同一次实验的 `run/status/serve/compare` 应使用相同目录。 |
| `-h` / `--help` | — | 显示帮助后退出；支持 `bbdevbox --help` 和 `bbdevbox run --help` 等所有子命令。 |

所有相对路径默认相对于启动命令的当前工作目录；配置文件中的 `prompt_file` 也按此规则解析，不是相对于 YAML 文件所在目录。

### `run`：启动评测或恢复运行

```bash
bbdevbox --root runs/experiment-a run DATASET.yaml --config config.yaml \
  --task TASK_UUID_A --task TASK_UUID_B --limit 1
```

| 参数 | 是否必需 / 默认值 | 功能及意义 |
| --- | --- | --- |
| `dataset` | 必需，位置参数 | YAML 任务数据集路径。每项需包含 `uuid`、`problem` 和 `verification`；容器任务还需 `dockerfile_content`。 |
| `--config PATH` | 可选，未指定时用代码默认值 | 读取模型、沙盒、agent、记忆和并发配置。默认模型名是占位值，真实评测应指定配置文件。 |
| `--task UUID` | 可选，默认全量任务 | 按任务 UUID 筛选；可重复传入多个，保持数据集中的原始顺序。未知 UUID 会报错。 |
| `--limit N` | 可选，无上限 | 在 `--task` 筛选后取前 N 项，N 必须为正整数；适合低成本冒烟与调试。 |
| `--resume RUN_ID` | 可选，默认创建新运行 | 恢复已经停止的指定运行。要求配置、筛选后任务指纹和初始 prompt profile 一致；仅重新执行 interrupted/cancelled 尝试，已完成的 passed/failed/error 保留。 |

容器后端会先检查 CLI 和引擎连通性，再分配任务。`run_id` 标识整次运行；attempt ID 标识某个任务的一次重复尝试，用于蒸馏与追踪。`status: completed` 表示评测流程结束，任务是否通过仍要查看 attempts 的 `passed/failed`。

### `serve`：启动网页监控

```bash
bbdevbox --root runs serve --host 127.0.0.1 --port 8765
```

| 参数 | 默认值 | 功能及意义 |
| --- | --- | --- |
| `--host HOST` | `127.0.0.1` | 监听地址，仅允许 `127.0.0.1` 或 `localhost`；远程访问可使用 SSH 隧道。 |
| `--port PORT` | `8765` | 网页与只读 API 的监听端口；同机多服务时需使用不同端口。 |

打开 `http://127.0.0.1:8765/` 默认跟随最新运行；`?run=RUN_ID` 固定查看某次运行。网页显示当前服务的数据目录，方便发现 `--root` 不一致的问题。

### `status`：终端状态监控

| 参数 | 默认值 | 功能及意义 |
| --- | --- | --- |
| `--run RUN_ID` | 可选，默认显示根目录下全部运行 | 只输出指定运行的概要和每个 attempt 的明细，包括状态、step、输入/输出 token、phase、错误和验证结果。 |
| `--watch` | 默认关闭 | 每 2 秒重新读取 SQLite；相关运行均已停止后自动退出。它不会启动网页服务，也不会控制已经打开的浏览器选中了哪个运行。 |

指定 `--run` 时会在标准错误流打印数据目录和默认 8765 端口的网页链接；若 `serve --port` 使用其他端口，打开链接时替换端口。状态 JSON 输出到标准输出，可重定向保存。

### `stop`、`recover`、`cleanup`：运行控制

| 命令及参数 | 默认值 | 功能及意义 |
| --- | --- | --- |
| `stop RUN_ID` | `RUN_ID` 必需 | 请求取消整次运行；正在执行的 shell 命令会在检测到取消后终止，模型请求会等到返回或请求超时。 |
| `recover RUN_ID` | `RUN_ID` 必需 | 将心跳过期且仍标记 running 的崩溃运行置为 interrupted，为清理和恢复做准备；不是重跑正常 error 的入口。 |
| `recover --stale-after SECONDS` | `30`，最小 `10` | 允许恢复前必须超过的心跳失联秒数，避免误恢复仍在工作的运行。应先确认旧进程已经停止。 |
| `cleanup RUN_ID` | `RUN_ID` 必需 | 清理已停止运行记录的容器和任务镜像；拒绝清理 running 的运行，不删除数据库和轨迹，不执行全局 prune。 |

### `compare`、`export`、`import-results`：结果管理

| 命令及参数 | 是否必需 / 默认值 | 功能及意义 |
| --- | --- | --- |
| `compare RUN_A [RUN_B ...]` | 至少一个 RUN_ID | 对比指定运行，输出全量指标、共同完成 task/repetition 的指标和领域细分；配置不一致时给出提示。 |
| `compare --html PATH` | 可选 | 额外生成可离线打开的 HTML 对比报告；不影响终端 JSON。 |
| `export RUN_ID PATH` | 两个位置参数均必需 | 将某次运行导出为旧版结果数组 YAML；这是输出文件，不应提交到仓库。 |
| `import-results PATH` | 文件路径必需 | 将外部历史结果 YAML 导入当前 `--root` 数据库；导入后生成一个新的 run ID。 |
| `import-results --label NAME` | 必需 | 历史结果的模型/实验显示名称，用于网页和报告。 |
| `import-results --duplicates POLICY` | `error` | `error` 拒绝重复 UUID；`concat` 显式拼接全部重复记录的尝试，不挑选最好结果。旧数据的独立性、环境和 prompt 来源仍需由实验者确认。 |

历史模型结果未随 Git 仓库上传，上述导入示例需要使用自己已有的结果文件。

### `memory`、`distill`：经验沉淀

| 命令及参数 | 是否必需 / 默认值 | 功能及意义 |
| --- | --- | --- |
| `memory ACTION` | 必需，`list` 或 `promote` | `list` 查看候选与已晋升知识；`promote` 将审阅后的候选晋升为可检索知识并导出 Markdown。 |
| `memory promote ID` | 晋升时必需 | 待晋升候选的知识 ID，不是 run ID 或 attempt ID。来源 attempt 必须 verification passed。 |
| `memory --collection NAME` | `default` | 选择知识集合；用于隔离不同训练来源、领域实验或数据划分。 |
| `distill ATTEMPT_ID` | 必需 | 从通过验证的 attempt 轨迹中提炼候选 `SKILL.md`；没有完整轨迹的历史导入记录不可蒸馏。 |
| `distill --config PATH` | 必需 | 提供离线蒸馏模型配置；会请求模型并产生额外 token 消耗，usage 写入蒸馏事件，不计入原 benchmark 的 token 指标。 |
| `distill --collection NAME` | `default` | 候选技能写入的集合，应与后续 `memory promote` 和运行中的 `memory.collection` 保持一致。 |

### `prompt-set`：修改任务类型提示词

| 参数 | 是否必需 / 默认值 | 功能及意义 |
| --- | --- | --- |
| `path` | 必需，位置参数 | 要创建或修改的 prompt profile YAML 路径，例如 `prompts/profiles.yaml`。 |
| `--from-file PATH` | 必需 | 从 UTF-8 文本/Markdown 读取新的提示词内容，并原子写入 profile 文件。 |
| `--domain NAME` | 可选 | 更新指定 subdomain 的提示词。 |
| `--keyword NAME` | 可选 | 更新指定 keyword 的提示词；与 `--domain` 互斥。两者都不传则更新 default 提示词。 |

### 辅助启动脚本与退出码

| 入口 / 参数 | 默认值 | 功能及意义 |
| --- | --- | --- |
| `python test_docker.py [backend]` | `docker` | 不调用模型，测试镜像构建、容器执行、独立 verification 与清理。backend 可为 `docker` 或 `podman`。 |
| `python test_docker.py --artifacts PATH` | `runs/smoke` | 持久化冒烟测试的 Dockerfile、构建日志和验证输出；每次创建独立子目录。 |
| `bash start_parallel_bench.sh CONFIG [DATASET] [run 参数...]` | CONFIG 必需；DATASET 默认正式数据集 | 包装 `bbdevbox run`；并发数取自配置里的 `workers`。DATASET 后的 `--task/--limit/--resume` 等参数原样传递，不启动独立的 8 进程追加 YAML。 |
| `python examples/offline_demo.py` | 无命令行参数 | 使用 scripted model、本地可信夹具和真实 LangGraph 生成演示结果，不需要模型密钥。 |

`bbdevbox` 正常完成命令返回 0；`run` 最终为 error/cancelled 返回 1；配置、参数或前置运行时错误通常返回 2；在命令外层捕获的 Ctrl+C 返回 130。运行内部处理取消后也可能以 cancelled/1 结束。单项任务验证失败但流程正常结束时，整次运行仍可能 completed/0，因此自动化判断通过率应读取 attempts 或 `compare` 的指标。容器冒烟脚本成功返回 0，测试或清理失败返回 1。

## YAML 运行配置完整说明

配置使用 `bbdevbox run DATASET --config config.yaml` 载入，未填写的字段使用以下代码默认值。未知键会报错；布尔值使用 YAML 的 `true/false`，预算、并发数和长度限制必须为正数，重试数与委派数可以为 0。API key 只放在环境变量中，不写入 YAML。

### 顶层配置

| 配置项 | 代码默认值 | 功能及意义 |
| --- | --- | --- |
| `workers` | `1` | 并行执行的独立 task/attempt 数。越大越占用容器资源，也越容易遇到模型端点限流；不是单个任务内子 agent 的并行数。 |
| `attempts` | `1` | 每个任务独立重复执行次数；每次使用新环境，以估计成功概率。 |
| `seed` | `42` | 任务 `${random_num}` 的确定性渲染种子，不保证远程模型生成本身完全可复现。 |
| `prompt_file` | `null` | 额外 prompt profile YAML；不指定时仅用内置基础 system prompt。 |
| `prompt_reload` | `false` | 每轮读取 prompt 文件的开关。开启可实时调整策略，但不再是固定 prompt 的对照实验；读取失败保留上个版本并记录错误。 |

### `model`：模型连接和请求

| 配置项 | 代码默认值 | 功能及意义 |
| --- | --- | --- |
| `model.name` | `your-tool-calling-model` | 端点实际接受的模型 ID；默认是占位值，真实运行前需修改。 |
| `model.base_url` | `null` | chat completions 兼容端点的 API 基址，如 `http://localhost:8000/v1`；null 使用 provider 默认地址。 |
| `model.api_key_env` | `OPENAI_API_KEY` | 从哪个环境变量读取密钥；保存到运行配置的是变量名，不是密钥值。指定兼容端点但没有密钥时使用占位认证值，仅适用于服务允许无认证的情况。 |
| `model.temperature` | `null` | 采样温度；null 表示不显式传入，遵循 provider 默认行为。部分模型不接受温度参数。 |
| `model.max_output_tokens` | `4096` | 每次响应的最大输出 token；实际调用还受全局剩余预算限制，provider 可能包含 reasoning token 等内部计量。 |
| `model.timeout` | `120` 秒 | 单次模型请求超时；实际请求时与当前尝试剩余时间取更小值。 |
| `model.retries` | `2` | 遇到连接、超时、限流或服务端暂时故障时，首次请求之后允许的额外重试次数。SDK 隐式重试关闭；harness 重试计入全局 step。 |
| `model.extra_body` | `{}` | 原样透传 provider 特定的请求字段；只填写端点明确支持的字段，不在这里放密钥或其他秘密。 |

### `sandbox`：环境隔离和资源限制

| 配置项 | 代码默认值 | 功能及意义 |
| --- | --- | --- |
| `sandbox.backend` | `docker` | `docker/podman/local`；前两者运行容器，local 在宿主执行，仅用于可信夹具。 |
| `sandbox.runtime` | `null` | 容器引擎 runtime 名称；`runsc` 需预先安装注册 gVisor，不可用时直接失败。 |
| `sandbox.network` | `none` | 任务容器运行阶段的网络模式：none 禁用外网，bridge 允许通常的出站网络。它不控制 Dockerfile 构建或基础镜像拉取的网络。 |
| `sandbox.memory` | `2g` | 每个容器的内存限制，采用 runtime 支持的单位字符串。 |
| `sandbox.cpus` | `2` | 每个容器可使用的 CPU 配额，可为正小数；不限制宿主模型服务的 CPU。 |
| `sandbox.pids_limit` | `256` | 每个容器内的进程数限制，减少进程失控风险；过小可能影响服务启动。 |
| `sandbox.build_timeout` | `600` 秒 | 单次任务镜像构建超时，不等于模型请求超时。 |
| `sandbox.command_timeout` | `60` 秒 | agent 每条命令的时间上限；独立 verification 也使用该值。容器命令超时会停止整个任务容器，避免后台后代残留。 |
| `sandbox.allow_local` | `false` | 必须显式设 true 才允许 local 后端。local 不提供文件系统、网络、CPU/RAM 等容器隔离。 |

### `agent`：任务预算与协作策略

| 配置项 | 代码默认值 | 功能及意义 |
| --- | --- | --- |
| `agent.max_steps` | `40` | 每个 attempt 的全局模型调用次数上限，包含主 agent、子 agent、LLM 摘要和重试；不是 shell 命令数。 |
| `agent.max_tokens` | `150000` | 每个 attempt 的累计输入+输出 token 预算；共享给主 agent、子 agent、摘要调用。优先使用返回的 usage，缺失时标记估算/未知。 |
| `agent.max_seconds` | `1200` 秒 | 一个执行段的时间预算，包含环境初始化和 agent 执行；verification 和清理另有超时。崩溃恢复的新执行段获得新的时间预算，原 step/token 消耗保留。 |
| `agent.multi_agent` | `false` | 暴露 `delegate` 工具，让主 agent 委派独立上下文子图；共享同一沙盒并顺序执行。 |
| `agent.max_delegations` | `3` | 每个执行段最多委派多少次；0 表示不允许实际委派。 |
| `agent.child_steps` | `8` | 每个子 agent 的最大图循环轮数，同时受全局 step/token/time 预算限制；子 agent 不再继续委派。 |
| `agent.allow_prompt_updates` | `false` | 暴露 `update_prompt`，允许更新当前 attempt 的附加 system 指令并保存提案；不会删除内置基础约束，也不会自动覆盖全局 profile。 |

### `context`：归档、裁剪和摘要

| 配置项 | 代码默认值 | 功能及意义 |
| --- | --- | --- |
| `context.max_input_tokens` | `24000` | 输入上下文估计预算，包含 system prompt、检索参考、工具 schema 和消息。本实现采用 UTF-8 字节保守估计，不等于 provider tokenizer 的精确计数。 |
| `context.keep_recent_turns` | `3` | 压缩时优先保留最近几个完整 AI+工具返回轮次；预算不足时会减少，避免拆散 tool_call_id 配对。 |
| `context.output_chars` | `12000` | 超过此字符数的工具输出仅在上下文保留首尾片段与归档引用；完整内容存盘。 |
| `context.chunk_chars` | `6000` | 归档分块读取和 LLM 分块摘要的字符数；按 Unicode 字符而非字节切分。 |
| `context.summary_chars` | `5000` | 历史压缩摘要的目标字符上限；为容纳最近轮次，必要时可进一步缩短。 |
| `context.llm_summary` | `false` | false 使用抽取式摘要；true 请求模型逐块总结，增加费用并消耗全局 step/token 预算。 |

### `memory`：知识读取策略

| 配置项 | 代码默认值 | 功能及意义 |
| --- | --- | --- |
| `memory.mode` | `"off"` | off 禁用跨任务召回；frozen 只检索运行开始时冻结的已晋升知识；continual 检索随晋升变化的知识库。为避免 YAML 1.1 将 off 解析为布尔值，请加引号。 |
| `memory.collection` | `default` | 本次运行读写知识提案的集合名，用于训练/测试来源隔离。 |
| `memory.top_k` | `3` | 每次召回最多返回的知识条数；只从已晋升、同集合、同领域且非当前 UUID 的记录检索。 |
| `memory.max_chars` | `6000` | 每次知识召回的累计文本长度上限，也用于限制模型调用中注入的工作笔记长度。 |

新实验可以复制配置并固定上述参数进行对照。运行配置、初始 prompt 和记忆快照会记录在数据库中；修改某些参数后不能继续沿用同一个 `--resume` 运行。

## 八项能力

| 能力 | 实现与入口 |
| --- | --- |
| Harness | `harness.py` 的 LangGraph `think → act → think`，原生工具调用、独立判分、步数 / token / 时间预算 |
| 沙盒 | `Sandbox` 协议；Docker、Podman CLI 后端；Linux 可选 `runtime: runsc`；资源限制、网络策略、进程超时与定向清理 |
| 可视化对比 | `serve` 仪表盘、领域指标、`compare --html` 离线报告、旧版结果导入 |
| 实时监控 | SQLite WAL 事件与计数事务、2 秒心跳、SSE 游标重连、任务 / 尝试分开展示、当前 agent / phase / step / tokens |
| Multi-Agent | `agent.multi_agent: true`，`delegate` 创建独立上下文子图；共享任务环境、顺序执行、统一预算、有限委派 |
| Skills / 记忆 | 工作笔记、长期记忆提案、成功轨迹 `distill`、显式晋升 `SKILL.md`、FTS5 检索与注入、冻结快照 |
| 上下文压缩 | 工具输出落盘、Unicode chunk 读取、完整历史归档、成组裁剪、抽取式或 LLM 分块摘要 |
| Prompt engineering | keyword / domain / default profile 路由、版本 SHA256、可选热加载、可选单次任务 prompt 更新和持久化提案 |

LangGraph 是本项目选用的现代通用编排框架；框架选择本身不构成 SOTA 分数的证明。选型依据与扩展边界见 [架构设计](docs/architecture.md)。

## 现有数据集、并发与重复尝试

```bash
bbdevbox run 'data/[TerminalBenchVer]uuid_bash_agent_questions.yaml' --config config.yaml
bbdevbox run 'data/[TerminalBenchVer]uuid_bash_agent_questions.yaml' --config config.yaml \
  --task 0fc1b67c-fce2-4fdc-b509-20ca83da38bb
```

配置 `workers` 控制任务并发，`attempts` 控制每个任务的独立重复次数。每次尝试使用独立环境，`${random_num}` 由 seed / UUID / repetition 确定；不受线程调度影响。verification 和 Dockerfile 不进入模型上下文。

旧数据集中有依赖外部 HTTP 和运行时 apt 安装的任务，需设置 `sandbox.network: bridge`；默认 `none` 仅允许容器自身回环网络。该策略限制运行阶段，Dockerfile **构建阶段仍可能访问网络**。镜像的原始 CMD / ENTRYPOINT 保留，以启动任务所需的服务；镜像必须保持运行，且提供 bash 和 GNU timeout。未声明启动指令时追加保活 CMD。

`bash -lc` 每条容器命令独立运行；`cd`、shell 变量不会跨调用保留。服务应后台运行并重定向输出。内存 / CPU / PID 限制针对容器；`local` 不提供这些隔离保证。gVisor 需在宿主预先安装并注册，不会静默降级；macOS 上须由相应 Linux VM/远程 Linux runtime 提供。

### Docker 未找到或无法连接

`docker executable not found` 表示运行 bbdevbox 的进程在 PATH 中找不到 Docker CLI。macOS 可按 [Docker 官方安装说明](https://docs.docker.com/desktop/setup/install/mac-install/)安装并启动 Docker Desktop。仅安装 Docker CLI 不会启动容器引擎。

在同一个终端验证：

```bash
# 安装了 Docker Desktop 但当前终端找不到 CLI 时：
export PATH="$HOME/.docker/bin:/Applications/Docker.app/Contents/Resources/bin:$PATH"
command -v docker
docker info
python test_docker.py docker
bbdevbox run examples/smoke.yaml --config config.yaml
```

只有 `docker info` 成功连接服务端后再运行正式数据集。新版会在创建运行记录、分发任务前统一检查 CLI 和 runtime；未创建资源时不会再次调用清理命令。若使用 Podman，配置 `sandbox.backend: podman`，并先让 `podman info` 成功。原数据集包含 Dockerfile，不能通过切换 `local` 绕过容器依赖。

历史运行中已记录的 error 尝试不会被 `--resume` 重跑；修复环境后执行原始 run 命令，创建新的 run ID。

### 镜像构建失败与 Docker Hub 超时

`Image build failed (1)` 是构建失败的汇总信息，具体原因查看异常附带的 Docker 输出和绝对路径 `build.log`。`python test_docker.py docker` 的 Dockerfile、构建日志和验证结果现在保存在 `runs/smoke/docker-<id>/`，退出后不会删除；清理错误也不会覆盖原始失败。

若输出停在 `load metadata for docker.io/library/ubuntu:24.04`，并出现 `failed to authorize: DeadlineExceeded`，应检查 Docker Desktop 到镜像仓库及鉴权服务的网络、代理和 DNS。先单独执行 `docker pull ubuntu:24.04`；若也失败，应先修复拉取基础镜像的链路。根据 [Docker Desktop 代理配置说明](https://docs.docker.com/desktop/settings-and-maintenance/settings/#proxies)，在设置的 Proxies 页面配置实际可用的 HTTP/HTTPS 代理，并确认用于 image pull 的 Containers proxy（若当前版本提供）配置正确，不要把示例端口当成本机代理端口。

拉取成功后再运行 `python test_docker.py docker`。`sandbox.network` 控制任务容器运行时网络，不控制 Docker daemon 拉取基础镜像；修改该选项不能直接解决上述 metadata 超时。

## 结果对比与历史迁移

```bash
bbdevbox import-results data/gpt-5_bash_agent_results.yaml --label historical-gpt-5 --duplicates concat
bbdevbox import-results data/gemini-2.5-pro_bash_agent_results.yaml --label historical-gemini --duplicates concat
bbdevbox compare RUN_A RUN_B --html comparison.html
bbdevbox export RUN_A exported-results.yaml
```

比较同时返回全量指标和双方**均已完成**的共同 task / repetition 指标；保留所有重复尝试，错误计入分母。macro pass@1 为每个任务的重复成功比例的均值；不采用 best-of，不把“任一次成功任务数”称为 pass@1。Wilson 区间仅是把重复尝试视为独立观察的描述性区间。不同数据指纹、预算、prompt 或记忆配置会触发提示。

历史 YAML 没有环境 / prompt / token 拆分的完整来源记录；导入后明确标记其来源未知，总 token 暂归输入列，不应解读为真实输入量。默认拒绝重复 UUID；若确认应保留全部追加记录，显式使用 `--duplicates concat`，拼接每条记录的尝试数组，不进行挑优或去重。此方式不保证重复记录在统计上独立。`success_rounds` 旧指标语义已废弃；兼容导出仅以通过时的 LLM 调用数填充。

## 运行控制与恢复

```bash
bbdevbox stop RUN_ID
# 崩溃后心跳超过 30 秒，先确认旧 runner 已停止：
bbdevbox recover RUN_ID
bbdevbox cleanup RUN_ID
bbdevbox run DATASET.yaml --config config.yaml --resume RUN_ID
```

恢复要求初始配置、任务指纹、prompt profile 一致。已完成尝试（含 failed/error）保持不变；只重跑 interrupted/cancelled 尝试，使用新沙盒，保留原事件、轨迹和累计 step/token 消耗。不会在任意 shell 副作用处恢复，也不会声称恢复了原容器。重新启动的执行段获得新的墙钟预算，任务耗时包含中断间隔。进行中的模型请求无法撤回，停止操作会在请求返回或超时后处理；usage 在每次响应返回后更新，非 provider 的逐 token 账单流。

## Skills、记忆与动态 prompt

成功运行后从 `status --run RUN_ID` 获取 attempt ID：

```bash
bbdevbox distill ATTEMPT_ID --config config.yaml --collection training
bbdevbox memory list --collection training
# 审阅候选内容后晋升；仅 verification passed 的来源可以晋升：
bbdevbox memory promote CANDIDATE_ID --collection training
```

晋升会导出 `runs/skills/<id>/SKILL.md`，记录来源任务、尝试和 collection。抽取使用独立模型调用，token usage 记录在 `skill_distilled` 事件里，**不计入 benchmark 分数的 token 成本**。超长轨迹只抽取尾部，完整轨迹保留。候选生成不代表内容正确或已消除任务答案；晋升前应泛化参数、删除具体答案和敏感值。

`remember(scope="short")` 保存当前尝试的工作笔记；`scope="long"` 提交待审记忆。`recall` 搜索已晋升、同领域、同 collection 的内容。检索使用 SQLite FTS5/BM25 词法匹配，支持 SQL 安全过滤、top-k 与长度限制；不需要 embedding 服务。短期上下文与笔记不跨尝试共享。

记忆模式：`"off"`（基线默认，YAML 中需要引号）、`frozen`（运行开始冻结知识 ID 集）、`continual`（读取随晋升变化的知识库）。同 UUID 任务经验始终排除，防止重复题泄漏。正式比较应在独立训练任务沉淀 SOP，使用审阅过的 collection 和 `frozen` 快照，固定 prompt，关闭任务内 prompt 自更新；SOP 内容来自数据库，编辑导出的 Markdown 不会隐式改变已冻结内容。

```bash
bbdevbox prompt-set prompts/profiles.yaml --domain 'DevOps and Systems' --from-file domain-prompt.md
```

prompt 优先级为 keyword > domain > default，并叠加基础工具约束。默认在运行开始冻结；`prompt_reload: true` 后每轮读取文件，原子更新后下一轮生效，读取失败沿用上个版本并记录事件。`agent.allow_prompt_updates: true` 暴露 `update_prompt` 工具，仅改变当前尝试的附加指令，并保存待审 prompt 提案；可晋升导出后通过 `prompt-set` 应用于后续任务。所有实际使用的 system prompt 和 SHA256 写入事件。

详细压缩策略、记忆生命周期及威胁边界见 [架构设计](docs/architecture.md)；完整参数参见 [示例配置](examples/config.yaml)。

## 开发

```bash
pip install -e '.[dev]'
pytest -q
ruff check src tests examples test_docker.py
python -m build --no-isolation
# Docker 可用时，执行不调用模型的真实容器冒烟检查：
python test_docker.py docker
```

CI 在 Python 3.11 / 3.12 上运行测试、lint 和打包，并在 Ubuntu Docker 上运行容器冒烟检查。`requirements.lock` 固定本次验证的开发依赖版本；需要重现时先 `pip install -r requirements.lock`，再 `pip install --no-deps -e .`。

代码许可证为 MIT。原始数据集与历史模型结果的来源和再分发状态见 [数据说明](data/DATASET_CARD.md)。
