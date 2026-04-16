# Co-Track 后续执行文档

- 版本：1.0
- 日期：2026-03-21
- 依据文档：
  - `docs/requirements-v1.1-2026-03-21.md`
  - `docs/technical-execution-v1.1-2026-03-21.md`

## 一、执行目标

本阶段目标是将当前演示实现收敛为“可联调、可验收”的 v1.1 版本，重点补齐三条主链路：

1. 阶段 1 的目标设定与基准模型确认闭环。
2. 阶段 2 的画布与 AI 辅助能力闭环。
3. 阶段 3/4 的评审、工程估算、3D 预览与导出闭环。

## 二、当前实现基线与差距

### 2.1 已修正问题（2026-03-21）

- 问题：阶段 1 错误显示创意助手。
- 修正：在 `frontend/src/App.tsx` 中移除 `uiStage === 1` 分支的 `AISidebar` 渲染，仅在阶段 2 保留创意助手。

### 2.2 关键差距清单

1. 阶段 1 当前仍以本地模拟为主：
   - `parseBriefLocally` 需替换为 `/api/ai/parse-brief`。
   - `handlePrepareBaseModel` 需替换为模型上传/模型库/自动生成真实 API 调用链。
2. 前端将后端 `LOBBY/BRIEFING/MODEL_PREPARING` 折叠为一个 UI 阶段，缺少子状态提示。
3. WebSocket 事件尚未对齐技术文档中的 `model:*` 与 `stage:*` 关键事件。
4. 评审与工程估算当前以静态样例数据为主，尚未打通服务端分析任务。
5. 三维预览与授权导出策略尚未完全落地（尤其 `export_glb_allowed` 分支）。

## 三、里程碑与排期

建议按 4 个里程碑推进（从 2026-03-23 开始）：

### M1（2026-03-23 ~ 2026-03-27）：阶段 1 闭环

目标：完成“目标设定 + 基准模型确认 + 锁定”的真实后端闭环。

交付项：

1. 前端接入：
   - `POST /api/ai/parse-brief`
   - `POST /api/models/upload`
   - `GET /api/models/library`
   - `POST /api/models/generate`
   - `GET /api/models/tasks/:task_id`
   - `POST /api/sessions/:id/base-model/select`
2. 阶段 1 UI 增加子状态提示：
   - `LOBBY`、`BRIEFING`、`MODEL_PREPARING`。
3. 主持人锁定模型后，才允许推进到 `DESIGNING`。

验收标准：

1. 三种模型来源至少各成功 1 次。
2. 未锁定模型时推进阶段返回明确错误。
3. 非主持人无法锁定模型或推进阶段。

### M2（2026-03-30 ~ 2026-04-03）：阶段 2 绘制与 AI 闭环

目标：完成 UV 模板画布、自动保存、AI 对话和图案生成的联调。

交付项：

1. 画布背景改为会话级 `uv_template_url`。
2. 接入：
   - `POST /api/ai/chat`
   - `POST /api/ai/generate-image`
3. 图案素材导入画布流程（参考层/底图层/贴花素材）。
4. 自动保存改为本地 + 服务端双写（30 秒）。

验收标准：

1. 同会话所有成员加载同一 UV 模板。
2. AI 对话上下文含 Brief + base_model 信息。
3. 图案生成结果可落地到画布图层。

### M3（2026-04-06 ~ 2026-04-10）：阶段 3 评审与工程估算

目标：完成方案收集、聚类、工程估算、投票排序。

交付项：

1. 接入：
   - `POST /api/ai/analyze-designs`
   - `GET /api/designs/:id/engineering`
   - `POST /api/votes`
2. 工程估算切换到：
   - `scale_m2_per_px = surface_area_m2 / paintable_uv_pixels`
3. 置信度标签展示：
   - `HIGH/MEDIUM/LOW` + `confidence_reason`。

验收标准：

1. 方案墙、聚类、投票排行可实时更新。
2. 不同模型来源对应正确置信度标签。
3. 工程估算数据与模型元数据字段一致。

### M4（2026-04-13 ~ 2026-04-17）：阶段 4 三维预览与导出

目标：完成统一基准模型下的多方案贴图预览与导出策略。

交付项：

1. Three.js 映射按 `mapping_meta.mesh_to_region` 执行。
2. 方案切换后实时更新纹理。
3. 导出分支：
   - 允许：导出带纹理 GLB。
   - 受限：导出预览包（纹理图 + 视图图 + 报告）。

验收标准：

1. 三维交互（旋转/缩放/平移）稳定可用。
2. 导出权限与 `export_glb_allowed` 严格一致。
3. 预览报告带模型精度标签。

## 四、任务拆解（前后端协同）

### 4.1 前端任务

1. 阶段 UI 重构：
   - 主阶段显示 1~4。
   - 阶段 1 内显示后端子状态。
2. API 接入：
   - 替换本地模拟逻辑。
3. WebSocket 接入：
   - `stage:changed`、`model:task_status`、`model:ready`、`model:locked`。
4. 错误提示统一：
   - 沿用 `parseApiError`，补充模型任务状态文案。

### 4.2 后端任务

1. 会话与模型接口补齐：
   - `base_model` 查询与锁定。
2. 模型任务队列：
   - 生成任务轮询 + WebSocket 推送。
3. 工程估算输入标准化：
   - 固化 `surface_area_m2` 和 `paintable_uv_pixels` 来源。
4. 导出权限控制：
   - 统一在服务端执行授权校验。

### 4.3 测试任务

1. 接口测试：
   - 阶段推进权限、模型锁定、导出权限。
2. 端到端流程测试：
   - 从 `LOBBY` 到 `PREVIEWING` 全链路。
3. 回归测试：
   - 画布自动保存、投票统计、3D 贴图切换。

## 五、联调与发布策略

### 5.1 联调顺序

1. 先打通阶段 1（因为阶段 2~4 依赖 `base_model`）。
2. 再联调阶段 2（画布与 AI）。
3. 最后合入阶段 3/4（分析、预览、导出）。

### 5.2 分支与发布建议

1. 分支：
   - `feature/stage1-base-model`
   - `feature/stage2-canvas-ai`
   - `feature/stage3-review-engineering`
   - `feature/stage4-preview-export`
2. 发布：
   - 每个里程碑结束后打一个可演示版本。
   - 关键接口变更先发 `dev`，通过回归后再进 `main`。

## 六、风险与对策

1. 自动生成模型耗时过长：
   - 对策：异步任务 + 进度推送 + 默认模板回退。
2. UV 规范不一致导致贴图错位：
   - 对策：统一 `mapping_meta` 校验器，构建前置检查。
3. 导出授权误判：
   - 对策：服务端单点鉴权，不依赖前端开关。
4. API 成本波动：
   - 对策：阶段 1 模型生成频次限制 + 会话级额度统计。

## 七、完成定义（DoD）

满足以下条件视为 v1.1 可验收：

1. 阶段边界与需求一致（阶段 1 无创意助手，阶段 2 有）。
2. 会话级统一基准模型三路径可用，且可锁定。
3. 工程估算使用模型面积与 UV 像素比例，不再使用固定系数。
4. 三维预览可在统一基准模型下切换方案并正确导出。
5. 至少完成一次从创建会议到导出的全链路演示。
