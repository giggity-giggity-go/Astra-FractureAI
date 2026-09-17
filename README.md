# Astra-FractureAI

> Product Hunt · GPT-6 Astra Challenge Demo(2026-09-18 启动)
> YOLO 三模型 + GPT-6 Astra 多模态 → X 光骨折智能辅助诊断

## 1. 项目简介

**Astra-FractureAI** 是一个面向放射科的 AI 辅助诊断 Demo。流程:

```
X 光片上传
   ↓
Ultralytics Cloud YOLO 三模型并行(position / range / kind)
   ↓
GPT-6 Astra 多模态(看图 + 读 YOLO 结果)→ 临床建议(流式输出)
```

后端用 Flask + OpenAI Python SDK,YOLO 三模型走 Ultralytics Cloud,LLM 走 OpenAI 兼容端点(默认 MiniMax-M3,9-18 后切 Astra)。前端是由 Flask 同源交付的 Vue 3 无构建单页应用,提供裁剪、医学影像 Canvas 工具、检测叠加、结果卡片和流式安全 Markdown 报告。完整设计见 [`../Astra-FractureAI后端设计.md`](../Astra-FractureAI后端设计.md)、[`../前端设计.md`](../前端设计.md) 与前端独立 [`frontend/README.md`](frontend/README.md)。

---

## 2. 快速启动(3 步)

### 2.1 Conda env

```bash
# 已就绪,直接激活即可
conda activate astra-fractureai
# Python 3.12.14 @ D:\ProgramData\Anaconda_envs\envs\astra-fractureai\
```

依赖在 `requirements.txt`(34 行,8 个 demo 直接依赖 + 26 个间接依赖,均已装好)。

### 2.2 配置 `.env`

```bash
# 从模板复制(本仓库只 commit .env.example)
cp .env.example .env       # macOS/Linux/Git Bash
copy .env.example .env     # Windows cmd/PowerShell
```

必填的 **4 个关键 key**:

| Key | 说明 | 例子 |
|---|---|---|
| `OPENAI_API_KEY` | LLM 鉴权 token | `sk-cp-c32dtL7c...` |
| `OPENAI_BASE_URL` | OpenAI 兼容端点,**必须以 `/v1` 结尾** | `https://api.minimax.cn/v1` |
| `OPENAI_MODEL` | 默认模型(`LLM_MODEL_PRIMARY` 空时回退) | `MiniMax-M3` |
| `YOLO_API_KEY` | Ultralytics Cloud Bearer | `ul_xxx` |

其他 8 个 key 都有兜底默认值,详见 `.env.example` 头部注释。

### 2.3 启动

```bash
python app.py
# 端口由 .env 的 PORT 决定(本实例 7895);若 PORT 未设置,app.py 默认 8080
```

启动后打开 `http://localhost:<PORT>/`（实际端口以 `.env` 的 `PORT` 为准）。Flask 在 `/` 提供 `frontend/index.html`,在 `/frontend/<path>` 提供静态资源；页面与 API 同源,无需 npm 或前端构建命令。

启动日志确认:

```
2026-09-17 [INFO] AstraFractureAI: Environment variables validated successfully.
                Primary LLM: MiniMax-M3, Fallback: MiniMax-M3
```

> 重启 / 换 `.env` 后再启动前请先看 §2.4「停止与重启」——直接二次启动会在 Windows 上撞 `OSError: [WinError 10048]`,因为旧 Flask 进程仍占着 PORT(本实例 `7895`)。

### 2.4 停止与重启 Flask 进程

Flask dev server(Werkzeug)不带 daemon 模式,所以**每次重启都必须先杀掉旧进程**,否则会立刻报端口占用。下方命令按你常用的 shell 三选一即可。

**首选(前台 Ctrl+C)**:在跑 `python app.py` 的那个终端按 **`Ctrl+C`**。Werkzeug 会捕获 SIGINT 跑 Flask 清理钩子(关 socket / join thread),不会留下半挂进程。**直接关窗口**等于 `TerminateProcess`,不跑清理,通常也死,但端口可能卡 `TIME_WAIT` 几十秒。

**从别的 shell 优雅终止**(走 WM_CLOSE,不是 `TerminateProcess`):

```powershell
# PowerShell(推荐,一行查 PID + 一行优雅终止,Windows 11 自带)
Get-NetTCPConnection -LocalPort 7895 -State Listen -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess |
    ForEach-Object { Stop-Process -Id $_ }   # 不加 -Force = 优雅
```

```cmd
:: cmd(备选)
netstat -ano | findstr :7895
:: 最后一列就是 PID,记下来,然后:
taskkill /PID <PID>            REM  不加 /F = 优雅(WM_CLOSE)
```

```bash
# Bash on Windows(Git Bash)— 注意 MSYS 路径转换,双斜杠转义:
netstat -ano | grep 7895
taskkill //PID <PID>           # 不加 //F = 优雅
```

> **真正挂死时才用强制杀**:`Stop-Process -Id <PID> -Force` / `taskkill /PID <PID> /F` / `taskkill //PID <PID> //F`。跳过 Flask 清理,正在跑的 SSE 流和 `ThreadPoolExecutor(max_workers=3)` 会被硬杀;但只要下次能正常重启就没事。

**杀完确认端口已释放**(再跑一次应该没有 LISTENING 行;若还有,等 30–60 s `TIME_WAIT` 过期,或换 `.env` 的 `PORT`):

```powershell
Get-NetTCPConnection -LocalPort 7895 -State Listen -ErrorAction SilentlyContinue   # 应空
```

**重启**:回到 §2.1 激活 conda,然后 `python app.py`,按 `Ctrl+C` 又是同一个循环。

---

## 3. 端点

| 方法 | 路径 | 用途 | 输入 / 备注 |
|---|---|---|---|
| GET | `/` | Vue 3 单页前端(`frontend/index.html`) | 同源交付,无参数 |
| GET | `/frontend/<path>` | 前端静态资源(`app.js` / `style.css` 等) | 路径相对于 `frontend/` 目录 |
| GET | `/api/health` | 健康检查 + 已配置模型列表 | 返回 `models.available`(`LLM_MODEL_PRIMARY` 与 `LLM_FALLBACK` 去重保序),不返回任何凭据 |
| POST | `/api/detect` | YOLO 三模型并行检测 | `multipart/form-data`: `file`(PNG/JPEG ≤ 20MB)+ `conf ∈ [0.01, 1.00]` + `iou ∈ [0.00, 0.95]` + `imgsz ∈ {320, 640, 1280}`。返回 `image_size = {width, height}` 表示 YOLO 实际接收的预处理图尺寸,前端用它把检测坐标投影回源图。3 模型全失败时返回 502 + `errors[]`,**不含** `detail` 字段以避免上游异常泄漏 |
| POST | `/api/explain` | LLM 临床建议(可选流式) | `application/json`:`image_base64` + `yolo_result` + 可选 `stream: true` + 可选 `llm_model ∈ configured_models()`(非法值返回 400 `INVALID_MODEL`)。SSE 首字节前 fallback,已输出正文时不重播;错误响应只含 `error` + `code`,不回显原始异常 |

详细 schema 见 [`../Astra-FractureAI后端设计.md` §3](../Astra-FractureAI后端设计.md)。

---

## 4. 测试

### 4.1 后端测试（9 项核心断言 + 4 套扩展函数 = 13 个 ✓ 编号）

```bash
python test/test_app.py
```

`test/test_app.py` 现含 4 个测试函数,`__main__` 顺序执行:

- `test_all`(9 个核心断言):`/api/health`、`clean_thinking`、`StreamThinkingStripper`、图片管道、非法图拒绝、`/api/detect` 输入校验、`/api/explain` 输入校验、`/api/detect` 的 `image_size` 元数据、`/api/detect` 参数范围(conf/iou/imgsz)。
- `test_configured_models_health_and_llm_routing`:`configured_models()` 去重 + health 暴露 `models.available`、非法 `llm_model` 拒绝、合法非流式首选模型与 fallback。
- `test_sse_fallback_framing_and_safe_error`:SSE 首字节前 fallback + 唯一 `[DONE]` 终止 + 安全 502(无 `detail`)不回显异常。
- `test_frontend_routes_after_assets_exist`:`/` 与 `/frontend/*` 静态资源 200。

跑法:

```bash
python test/test_app.py
# 应输出 13 行 ✓ 编号通过
```

### 4.2 端到端测试 ✅(2026-09-17 17:22 全过)

**3/3 X-ray 真跑**:`forearm_fracture1.png` + `humurs_fracture1.png` + `humurs_fracture2.png`
全过 detect + explain。详见 [`test/e2e_results.md`](test/e2e_results.md)(含 8 次调试 timeline)。

```bash
python test/test_e2e.py
```

输出示例(完整结果在 `test/e2e_results.json`):

```
[health]                 200 in 0.0s  — primary=MiniMax-M3
[forearm_fracture1.png]  detect 200 in 4.24s — p:1 r:2 k:5
[forearm_fracture1.png]  explain 200 in 7.32s — 5688 chars, model=MiniMax-M3
[humurs_fracture1.png]   detect 200 in 4.66s — p:1 r:1 k:5
[humurs_fracture1.png]   explain 200 in 22.83s — 5351 chars, model=MiniMax-M3
[humurs_fracture2.png]   detect 200 in 4.69s — p:1 r:2 k:5
[humurs_fracture2.png]   explain 200 in 24.31s — 5765 chars, model=MiniMax-M3
TOTAL: 68.06s
```

---

## 5. 已知 caveat

### 5.1 临时 LLM 路由

当前 `.env` 里 `LLM_FALLBACK=MiniMax-M3`,**与 Primary 相同**(Primary 走 `OPENAI_MODEL=MiniMax-M3`)。这意味着 fallback **退化为重试**,不是真正的异构兜底。

**原因**:9-18 之前 Astra 还没上线,没有其他真模型可用,所以临时设成"同模型重试一次"。

**9-18 后必须改**:
```diff
- LLM_FALLBACK=MiniMax-M3
+ LLM_FALLBACK=deepseek-chat
+ # 并在头部加:
+ LLM_MODEL_PRIMARY=gpt-6-astra
```

> 备注:`app.py` 代码层面 `LLM_FALLBACK` 默认值已是 `deepseek-chat`,`LLM_MODEL_PRIMARY` 默认 `MiniMax-M3`(优先级: `LLM_MODEL_PRIMARY` > `OPENAI_MODEL` > `MiniMax-M3`)。本节说的是 `.env` 实际值,不是代码默认。

### 5.2 非默认端口

`PORT=7895`,**不是** Flask 默认的 `8080`。本机调试无需调整;部署到云平台时,外部 URL 要对应转发到 `7895`,或回 `PORT=8080`。

### 5.3 `.env` 含真实 key

- `.env` 在 `.gitignore` 内,**绝不进 git**
- 真实 key 已进 Claude 对话上下文,**强烈建议** rotate:
  - `OPENAI_API_KEY` → MiniMax 控制台
  - `YOLO_API_KEY` → Ultralytics Cloud 控制台
- 前端 `localStorage` 只持久化 `{backendUrl, llmModel}`(键名 `astra-fractureai-settings`)。**不接触、不缓存任何 API key**;所有 LLM 输出经 `marked.parse()` + `DOMPurify.sanitize()` 才进 `v-html`。

### 5.4 Pillow 12 / OpenAI SDK 3.x 兼容

代码用 `Image.Resampling.LANCZOS` 而非 `Image.LANCZOS`(后者在 Pillow 12 deprecated)。
代码用 `datetime.now(timezone.utc)` 而非 `datetime.UTC`(后者在 `from datetime import datetime` 路径下找不到)。两条都已加 root cause 备注。

### 5.5 i18n:代码全英文,prompt 是英文最佳实践

`app.py` **所有代码字符串**(raise / error / response)均为英文,LLM prompt 也是英文(OpenAI Vision 最佳实践结构:5 段 Markdown `## Impression` / `## YOLO Correlation` / `## Recommended Workup` / `## Acute Management` / `## Safety Disclaimer`)。

- ✅ 后端代码字符串和 LLM prompt 仍使用英文
- ✅ 前端采用中文医学工作台文案(位置/范围/类型中文标签、阶段状态、错误提示、工具按钮、对话框),模型输出原文经 Markdown 渲染保留
- ✅ `SYSTEM_PROMPT` / `USER_TEXT_TEMPLATE` 已拆为模块级常量,便于将来加 `SYSTEM_PROMPT_ZH_CN` 走 `locale=...` 切换
- ✅ `/api/detect` 三模型全失败返回的 502 响应只含 `error` + `errors[]`,**不含**可能携带上游凭据或内部异常的 `detail` 字段(2026-09-17 review 修复)

---

## 6. 9-18 后 TODO

| # | 任务 | 步骤 |
|---|---|---|
| 1 | 切 Astra | `.env` 加 `LLM_MODEL_PRIMARY=gpt-6-astra` |
| 2 | 真正异构 fallback | `LLM_FALLBACK=deepseek-chat` |
| 3 | 跑测试 | `python test/test_app.py`(13 项断言应全过) |
| 4 | 端到端 | `humurs_fracture1.png` 真打 |
| 5 | 录视频 | < 2 分钟 demo |
| 6 | 投稿 | Product Hunt 上线 + GitHub 仓库公开 |
| 7 | 前端最终 overlay 重验 | Ultralytics Cloud 9-17 临时返回 `NETWORK_ERROR` / `TIMEOUT`,导致 `/api/detect` 返回 502。上游恢复后用 `humurs_fracture1.png` 重跑并确认 bbox/polygon 在 zoom/pan/rotate 后坐标仍对齐 |

---

## 7. 详细设计 / 文档索引

| 路径 | 用途 |
|---|---|
| [`../Astra-FractureAI后端设计.md`](../Astra-FractureAI后端设计.md) | ⭐ 后端设计 v1.0(16 章节,33 KB,写代码的唯一蓝图) |
| [`../progress.md`](../progress.md) | 项目进度日志(已 26 项) |
| [`../CLAUDE.md`](../CLAUDE.md) | 目录级硬约束(4 条 MCP 规则) |
| [`../GPT-6-Astra调研报告.md`](../GPT-6-Astra调研报告.md) | Astra 是推理模型的关键事实 |
| [`../OpenAI兼容端点可行性报告.md`](../OpenAI兼容端点可行性报告.md) | OpenAI SDK 源码级 + 8 厂商对照 |
| [`../OpenAI-SDK-thinking-统一方案调研.md`](../OpenAI-SDK-thinking-统一方案调研.md) | thinking 处理 A/B/C 方案对比 |
| [`../Ultralytics云平台API调研报告.md`](../Ultralytics云平台API调研报告.md) | YOLO 三模型 endpoint schema |

---

## 8. 文件清单(本子目录)

```
Astra-FractureAI/
├── .env                  # 真实 key,严禁 git
├── .env.example          # 配置模板,可提交
├── .gitignore            # Python + .env 排除
├── app.py                # Flask API、模型路由、SSE 与前端静态服务
├── frontend/
│   ├── index.html        # Vue/Element Plus 单页界面与固定 CDN 依赖
│   ├── app.js            # 上传、Canvas、API、SSE 和设置逻辑
│   ├── style.css         # 暗色响应式医学工作台
│   └── README.md         # 前端运行、CDN 版本与安全边界
├── test/
│   ├── test_app.py       # 后端契约、模型路由、SSE 与静态路由测试(13 项断言)
│   ├── test_e2e.py       # 真实外部服务 E2E
│   ├── e2e_results.md    # 端到端 8 次调试 timeline
│   └── test_fracture_img/# 本地 X 光测试图片
├── requirements.txt
└── README.md
```

---

## 9. License

未指定。如需在 Product Hunt 公开仓库,建议加 `MIT` 或 `Apache-2.0`。
