# test/ · 端到端测试图片库

> ⚠️ 2026-09-17 状态:**本目录当前为空**。用户手动从外部数据集(Kaggle FracAtlas / Roboflow)拖入真实骨折 X 光后,Claude 会基于实际文件名写 `test_e2e.py`。
>
> **为什么 Claude 不自动复制**:毕设项目 `D:\WORKSTATION\PYTHON\Graduation project\DjangoFractureAI-Clean\` 内部**没有真实骨折 X 光**(只有 24 张完全相同的占位测试图,且不带 FracAtlas/HBFMID/Roboflow 原数据集)。`humurs_fracture1.png` 也不存在 —— 前面 session 提到的文件名是预期命名,不是已有文件。

---

## 1. 命名规范

`<部位>_<类型>_<序号>.<ext>`,例如:

- `distal_radius_transverse_001.jpg` — 桡骨远端横形骨折
- `humerus_spiral_002.png` — 肱骨螺旋形骨折
- `femur_comminuted_003.jpeg` — 股骨粉碎性骨折
- `tibia_oblique_004.webp` — 胫骨斜形骨折

**部位推荐词表**:`distal_radius`(桡骨远端) / `proximal_humerus`(肱骨近端) / `humerus_shaft`(肱骨干) / `femur_neck`(股骨颈) / `tibia_plateau`(胫骨平台)

**骨折类型推荐词表**:`transverse`(横形) / `oblique`(斜形) / `spiral`(螺旋形) / `comminuted`(粉碎性) / `greenstick`(青枝) / `impacted`(嵌插) / `avulsion`(撕脱)

序号建议 3 位补零(`001` ~ `999`)以便排序。

---

## 2. 推荐数据来源

| 来源 | 特点 | 备注 |
|---|---|---|
| **Kaggle FracAtlas** | 1477 张带骨折标注,X 光为主 | 需 Kaggle 账号,免费下载 |
| **Roboflow Universe** | 搜 "fracture xray" / "xray fracture" | 部分需注册,Web 直接下载 |
| **MURA** | 斯坦福肌肉骨骼 X 光数据集(7 类) | 需申请 |
| **FracNet** | 肘关节 + 腕关节骨折 | 需 GitHub 下载 |

---

## 3. 文件大小 / 格式要求(对齐 `app.py` 校验)

| 项 | 限制 | 出处 |
|---|---|---|
| **格式** | PNG / JPG / GIF / WebP | `app.py` `_ALLOWED_MAGIC` |
| **大小** | ≤ 20MB | `app.py` `MAX_IMAGE_BYTES` |
| **最小** | ≥ 16 字节 | `app.py` `validate_image` |
| **分辨率** | 不限,自动压到 1024px | `app.py` `preprocess_image` |

不满足格式 / 大小限制的图会被 `/api/detect` 拒绝并返回英文 error。

---

## 4. Smoke test 流程(用户拖图后,Claude 写 `test_e2e.py` 时使用)

### 4.1 启动后端

```bash
conda activate astra-fractureai
python app.py
# 监听 0.0.0.0:7895
```

### 4.2 上传测试图

```bash
curl -F file=@test/distal_radius_transverse_001.jpg \
  http://localhost:7895/api/detect
```

期望返回:

```json
{
  "success": true,
  "positions": [...],
  "range": [...],
  "kind": [...],
  "processing_time": ~3000,
  "errors": []
}
```

### 4.3 拿 LLM 临床建议

```bash
curl -X POST http://localhost:7895/api/explain \
  -H 'Content-Type: application/json' \
  -d '{
    "image_base64": "'$(base64 -w 0 test/distal_radius_transverse_001.jpg)'",
    "yolo_result": {...4.2 的输出...}
  }'
```

期望返回英文 Markdown 5 段结构(`## Impression` / `## YOLO Correlation` / ...)。

---

## 5. .gitignore

`test/` 里的图片**不进 git**,原因:
1. 仓库膨胀(单图几 MB × 几十张 → 几百 MB)
2. 隐私合规(部分数据集有授权限制)

`.gitkeep` 保留是为了让**目录本身**可被 git track(空目录默认 git 不收)。

`.gitignore` 已配条目:

```
test/*
!test/.gitkeep
!test/README.md
```

---

## 6. 隐私声明

- ✅ 公开数据集(Kaggle/Roboflow/MURA)已**官方脱敏**,无患者身份信息
- ⚠️ 若从医院 / 内部渠道拿到 X 光,**必须**手动裁剪患者姓名 / ID / 日期后再放入
- ⚠️ demo 视频 / Product Hunt 投稿时只展示**图像内容 + AI 输出**,不展示元数据

---

## 7. 当前状态

| 项 | 状态 |
|---|---|
| 目录创建 | ✅ 2026-09-17 16:14 |
| README 写入 | ✅ 2026-09-17 16:14 |
| .gitkeep 写入 | ✅ 2026-09-17 16:14 |
| 实际图片 | ⏳ 等待用户拖入 |
| `test_e2e.py` 端到端测试 | ⏳ 拖图后另起 plan |

---

## 8. 用户后续动作清单

1. ⬜ 下载 3-5 张真实骨折 X 光(从 §2 来源)
2. ⬜ 按 §1 命名规范重命名
3. ⬜ 拖入 `D:\WORKSTATION\ChatGPT Competition\Astra-FractureAI\test\`
4. ⬜ 告诉 Claude "图已拖入",触发 Phase B 写 `test_e2e.py`
