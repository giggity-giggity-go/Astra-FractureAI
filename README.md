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

后端用 Flask + OpenAI Python SDK,YOLO 三模型走 Ultralytics Cloud,LLM 走 OpenAI 兼容端点(默认 MiniMax-M3,9-18 后切 Astra)。完整设计见 [`../Astra-FractureAI后端设计.md`](../Astra-FractureAI后端设计.md)。

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
# 默认监听 0.0.0.0:7895(PORT=7895,可在 .env 覆盖)
```

启动日志确认:

```
2026-09-17 [INFO] AstraFractureAI: Environment variables validated successfully.
                Primary LLM: MiniMax-M3, Fallback: MiniMax-M3
```

---

## 3. 端点

| 方法 | 路径 | 用途 | 输入 |
|---|---|---|---|
| GET | `/api/health` | 健康检查 | 无 |
| POST | `/api/detect` | YOLO 三模型并行检测 | `multipart/form-data` 字段 `file`(图)+ 可选 `conf`/`iou`/`imgsz` |
| POST | `/api/explain` | LLM 临床建议(可选流式) | `application/json` `{image_base64, yolo_result, stream?}` |

详细 schema 见 [`../Astra-FractureAI后端设计.md` §3](../Astra-FractureAI后端设计.md)。

---

## 4. 测试

### 4.1 单元测试(7 套件)

```bash
python test/test_app.py
```

| # | 套件 | 验证内容 |
|---|---|---|
| 1 | `/api/health` | 200 + `{status:"healthy", models:{...}}` |
| 2 | `clean_thinking` | 5 种 thinking 格式(`<think>` / `<thought>` / ` ```thinking``` ` / 未闭合 / 干净文本) |
| 3 | `StreamThinkingStripper` | 跨 chunk 拼接 + flush |
| 4 | Image 管道 | PNG → JPEG 1024px + q85 + base64 |
| 5 | 非法图拒绝 | 16 字节以下 / magic 不符 → ValueError |
| 6 | `/api/detect` 校验 | 缺 `file` → 400 |
| 7 | `/api/explain` 校验 | 缺 `image_base64` → 400 |

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

### 5.2 非默认端口

`PORT=7895`,**不是** Flask 默认的 `8080`。本机调试无需调整;部署到云平台时,外部 URL 要对应转发到 `7895`,或回 `PORT=8080`。

### 5.3 `.env` 含真实 key

- `.env` 在 `.gitignore` 内,**绝不进 git**
- 真实 key 已进 Claude 对话上下文,**强烈建议** rotate:
  - `OPENAI_API_KEY` → MiniMax 控制台
  - `YOLO_API_KEY` → Ultralytics Cloud 控制台

### 5.4 Pillow 12 / OpenAI SDK 3.x 兼容

代码用 `Image.Resampling.LANCZOS` 而非 `Image.LANCZOS`(后者在 Pillow 12 deprecated)。
代码用 `datetime.now(timezone.utc)` 而非 `datetime.UTC`(后者在 `from datetime import datetime` 路径下找不到)。两条都已加 root cause 备注。

### 5.5 i18n:代码全英文,prompt 是英文最佳实践

`app.py` **所有代码字符串**(raise / error / response)均为英文,LLM prompt 也是英文(OpenAI Vision 最佳实践结构:5 段 Markdown `## Impression` / `## YOLO Correlation` / `## Recommended Workup` / `## Acute Management` / `## Safety Disclaimer`)。

- ✅ 注释 + docstring 保留中文(便于国内开发者阅读)
- ✅ `SYSTEM_PROMPT` / `USER_TEXT_TEMPLATE` 已拆为模块级常量,便于将来加 `SYSTEM_PROMPT_ZH_CN` 走 `locale=...` 切换
- ✅ 7 套件测试同步更新关键字(`"仅支持"` → `"accepted"`)
- ⚠️ **副作用**:LLM 输出也是英文,前端 UI 文案如果保留中文,可能要做 i18n

---

## 6. 9-18 后 TODO

| # | 任务 | 步骤 |
|---|---|---|
| 1 | 切 Astra | `.env` 加 `LLM_MODEL_PRIMARY=gpt-6-astra` |
| 2 | 真正异构 fallback | `LLM_FALLBACK=deepseek-chat` |
| 3 | 跑测试 | `python test/test_app.py`(7 套件仍应全过) |
| 4 | 端到端 | `humurs_fracture1.png` 真打 |
| 5 | 录视频 | < 2 分钟 demo |
| 6 | 投稿 | Product Hunt 上线 + GitHub 仓库公开 |

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
├── .env                  # 真实 key,严禁 git(1.7 KB)
├── .env.example          # 12 key 模板,可提交(2.4 KB)
├── .gitignore            # Python + .env 排除
├── app.py                # Flask 后端(663 行,30 KB)
├── test/                 # 端到端测试(test_app.py 7 套件 + README + .gitkeep)
├── requirements.txt      # 8 个 demo 依赖(34 行)
└── README.md             # 本文件
```

---

## 9. License

未指定。如需在 Product Hunt 公开仓库,建议加 `MIT` 或 `Apache-2.0`。
