# Astra FractureAI 前端

无需 Node 构建步骤的 Vue 3 单页医学影像工作台，由现有 Flask 服务同源交付。

> 最后更新:2026-09-17(前端落地 + 测试扩展 + 文档同步)

## 运行

在项目根目录启动后端:

```bash
conda activate astra-fractureai
python app.py
```

浏览器打开 `.env` 中 `PORT` 对应的地址(本实例 `http://localhost:7895/`;若 `.env` 未设 `PORT`,`app.py` 默认 `8080`)。Flask 在 `/` 提供 `index.html`,在 `/frontend/<path>` 提供静态资源,**页面与 API 同源**,无需 npm 或前端构建命令。

## 固定 CDN 依赖

`frontend/index.html` 用 unpkg 加载,**版本写死**,无 `@latest`:

| 依赖 | 版本 |
|---|---|
| Vue | `3.5.22` |
| Element Plus | `2.11.7` |
| Element Plus Icons Vue | `2.3.2` |
| Cropper.js | `1.6.2` |
| marked | `12.0.2` |
| DOMPurify | `3.1.6` |

首次打开页面需要浏览器能够访问 `unpkg.com`。未引入 npm、Vite 或其他构建工具。

## 功能流

1. 拖入或点击选择 PNG/JPEG X 光片(前端限制 `MAX_FILE_BYTES = 20 MB`),Element Plus 卡片式 dropzone 支持键盘聚焦与拖拽。
2. Cropper.js 弹窗裁剪与左右 90° 旋转,应用裁剪后生成 JPEG `File`(`maxWidth: 4096`,`imageSmoothingQuality: 'high'`,`quality: 0.94`)。
3. 参数面板:`conf ∈ [0.01, 1.00]` + `iou ∈ [0.00, 0.95]` + `imgsz ∈ {320, 640, 1280}`。改参数后置 `resultsStale`,提示需重新检测。
4. `runDetection()` 调用 `POST /api/detect`,后端三模型并行。响应中的 `image_size = {width, height}` 表示 YOLO 实际接收的预处理图尺寸,前端用 `detectionScale()` 把所有 bbox / polygon 坐标投影回源图尺寸。
5. 高 DPI Canvas 查看器渲染影像 + position(黄色 `#ffe45c`)+ range(青色 `#56d6f4`)。`kind` 不画到 Canvas,只在结果卡内显示。
6. 6+1 工具栏:**窗宽/窗位**、**缩放**(滚轮 anchor-aware)、**平移**、**长度**(2 点像素距离)、**角度**(3 点夹角)、**旋转**(自由拖拽)、**重置**。所有变换统一走显式 `viewportTransform()` 矩阵。
7. 结果卡:按 confidence 降序展示 position/range/kind,带 Element Plus 进度条(三色 `<60` 红 / `<80` 黄 / `≥80` 绿)。局部模型失败显示非阻塞警告条,其余卡片与 LLM 报告仍可继续。
8. `runExplanation()` 调用 `POST /api/explain`(`stream: true`),`consumeSSE()` 用 `ReadableStream` 跨 chunk 缓冲、多行 `data:` 拼接、解析 `{text, model}` 与 `[DONE]`。
9. 报告原始 Markdown 文本保留;`renderMarkdown()` 走 `marked.parse()` → `DOMPurify.sanitize()` → `v-html` 安全渲染;流式追加配合活动 caret 与段落淡入。
10. Settings 齿轮只暴露 `backendUrl` + LLM 模型选择;健康检查刷新模型列表,若旧选择已不可用自动回退 primary。

## 设置与安全边界

`localStorage` 键名:`astra-fractureai-settings`,**只持久化** `{backendUrl, llmModel}` 两个字段。**不接触、不缓存任何 API key**(YOLO / OpenAI 都不进浏览器)。

- 模型下拉只来自 `GET /api/health` 返回的 `models.available`(`LLM_MODEL_PRIMARY` 与 `LLM_FALLBACK` 去重保序)。
- 后端 URL 默认同源,留空 = 当前站点。手动改后会重新调用 `/api/health` 校验。
- 切换影像或重新分析时使用 `AbortController` 取消旧请求,并自增 `generation` id;迟到 SSE chunk 被忽略,避免报告串线。
- LLM 输出 HTML 不会直接信任:`marked.parse()` + `DOMPurify.sanitize()` 是必经管线,禁止 `v-html="rawSseText"`。
- 浏览器 console 不打印任何凭据;Settings 对话框也明确告知"浏览器只保存后端地址与模型选择,不接触任何 API 密钥"。

## API 契约

- `GET /api/health` → 健康状态 + `models.available`(无凭据)。
- `POST /api/detect`(multipart):
  - `file`: PNG/JPEG ≤ 20 MB
  - `conf ∈ [0.01, 1.00]`、`iou ∈ [0.00, 0.95]`、`imgsz ∈ {320, 640, 1280}`
  - 返回 `image_size = {width, height}`;3 模型全失败时 502 + `errors[]`,**不含** `detail` 字段。
- `POST /api/explain`(JSON):
  - `image_base64` + `yolo_result` + 可选 `stream: true` + 可选 `llm_model ∈ configured_models()`
  - 非法 `llm_model` 返回 400 `INVALID_MODEL`
  - SSE 首字节前 fallback,已输出正文时不重播;错误响应只含 `error` + `code`,不回显原始异常

## 浏览器 E2E(2026-09-17)

Chrome DevTools MCP 验证结论:

- 6 个固定 CDN 资源全部 200,页面无 console error。
- 健康检查、上传、裁剪、参数面板、6+1 工具、阶段状态指示器、三类结果卡与 `marked + DOMPurify` 渲染均通过。
- 局部错误路径:Ultralytics Cloud 三模型端点在 20:55–20:56 之间返回 `NETWORK_ERROR` / `TIMEOUT`,后端 `/api/detect` 返回 502 + `errors[]` + `image_size`;前端正确显示非阻塞错误 alert(不是前端 bug,等上游恢复)。

---

此界面只用于辅助筛查演示,不构成医疗诊断或治疗意见。
