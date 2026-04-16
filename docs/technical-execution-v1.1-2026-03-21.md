# Co-Track 技术执行文档

- 版本：1.1
- 日期：2026-03-21

## 一、技术架构

### 1.1 整体架构
浏览器客户端 ↔ HTTP REST + WebSocket ↔ Nginx ↔ FastAPI 后端（REST、WebSocket、LangGraph 编排、3D 资产管线、规则计算、异步 Worker）

依赖：
- PostgreSQL
- 本地文件存储/S3
- Redis/任务队列
- 外部 AI API（文本、图像、Embedding、Tripo、Meshy、Rodin）

### 1.2 前端技术栈
- React 18 + TypeScript
- Vite
- Fabric.js 6.x（2D 画布）
- Three.js + @react-three/fiber（3D 预览）
- Ant Design 5.x
- Zustand
- Socket.io-client
- Axios
- React Router v6

新增前端模块：
- 基准模型选择弹窗
- 3D 模型上传组件
- 产品参数表单
- 基准模型生成进度卡
- 模型精度与授权标签

### 1.3 后端技术栈
- Python 3.11 + FastAPI
- LangGraph + LangChain
- python-socketio
- SQLAlchemy 2.0
- SQLite（开发）/ PostgreSQL 15（生产）
- 本地文件系统（开发）-> S3（生产）
- Pillow + OpenCV
- trimesh / pygltflib
- Blender Headless（可选）
- python-dotenv

### 1.4 AI/API 选型策略
- 文本模型：Brief 解析、创意对话、报告生成
- 轻量文本模型：Prompt 优化、语义描述
- 图像模型：图案生成
- Embedding：方案聚类
- 3D 生成：Tripo / Meshy / Rodin
- 重纹理（可选）：Meshy Retexture

说明：通过“模型供应商适配层”做路由与替换，不绑定单一厂商。

## 二、数据库设计

### 2.1 核心表
- `users`
- `sessions`（新增：`product_category`、`product_profile`、`base_model_id`、`model_locked_at`）
- `session_members`
- `model_assets`（新增）
- `model_generation_tasks`（新增）
- `designs`（增加 `base_model_id` 快照）
- `generated_images`
- `votes`

### 2.2 关键字段与语义
- `model_assets.source_type`: `upload | library | generated`
- `model_assets.precision_level`: `authoritative | standard | approximate`
- `model_assets.license_scope`: `self_owned | internal | external_restricted`
- `model_assets.export_glb_allowed`: 授权导出开关

## 三、API 设计

### 3.1 REST API（修订）
认证：
- `POST /api/auth/register`
- `POST /api/auth/login`

会议：
- `POST /api/sessions`
- `GET /api/sessions/:id`
- `POST /api/sessions/join`
- `POST /api/sessions/:id/advance`
- `GET /api/sessions/:id/base-model`
- `POST /api/sessions/:id/base-model/select`

模型：
- `POST /api/models/upload`
- `GET /api/models/library`
- `POST /api/models/generate`
- `GET /api/models/tasks/:task_id`
- `POST /api/models/:id/normalize`
- `POST /api/models/:id/extract-uv`
- `GET /api/models/:id/download`

设计：
- `POST /api/designs`
- `GET /api/sessions/:id/designs`
- `PUT /api/designs/:id`

AI：
- `POST /api/ai/parse-brief`
- `POST /api/ai/chat`
- `POST /api/ai/generate-image`
- `POST /api/ai/analyze-designs`

计算/投票/文件：
- `GET /api/designs/:id/engineering`
- `POST /api/votes`
- `POST /api/upload/canvas`
- `GET /api/files/uv/:model_id`
- `GET /api/files/models/:model_id`

### 3.2 WebSocket 事件（修订）
客户端 -> 服务端：
- `session:join`
- `canvas:update`
- `chat:message`
- `stage:advance`
- `model:generate`
- `model:select`

服务端 -> 客户端：
- `session:user_joined`
- `canvas:sync`
- `stage:changed`
- `brief:published`
- `model:task_status`
- `model:ready`
- `model:locked`
- `designs:collected`
- `engineering:ready`
- `chat:broadcast`

## 四、三维模型与基准模型策略

### 4.1 基准模型原则
- 每场会议仅一个 `base_model`
- 所有方案使用同一 `base_model` 贴图
- 投票、排名、预览在同模型下进行
- 不为不同方案生成不同几何模型
- 更换基准模型仅允许主持人在设计前重置会议

优先级：
1. 用户上传模型
2. 模型库标准模型
3. 自动生成近似模型

### 4.2 参数模板与初始化
- 首发高铁模板（车型、编组、长宽高、车头风格、车身比例、窗带、顶部设备简化）
- 通用产品模板（长宽高、主轮廓、三视图特征、对称性、部件、精度等级）

### 4.3 自动生成近似流程
1. 读取参数模板
2. 生成标准化描述 Prompt
3. 生成参考三视图/轮廓
4. 调用 3D API
5. 下载并归一化
6. 检查或生成 UV
7. 提取可喷涂区与映射
8. 输出 UV 模板
9. 计算表面积与 UV 像素比例
10. 保存会话级 `base_model`

### 4.4 UV 规范
每个 `model_asset` 必须包含：
- `uv_template_url`
- `mapping_meta`
- `surface_area_m2`
- `paintable_uv_pixels`

高铁建议：4096x2048 UV、2048x1024 画布、车头/车身/车顶/车尾分区。

### 4.5 Three.js 映射逻辑
通过 `mapping_meta.mesh_to_region` 决定可喷涂网格，不再使用 `child.name.includes('body')` 之类硬编码。

### 4.6 授权与导出策略
可导出 GLB：自有/内部/已获可分发授权模型。  
默认不导出原始底模：受限第三方资产。  
受限时仅导出预览包（纹理 + 视图 + 报告）。

## 五、工程计算逻辑

### 5.1 颜色面积统计（修订）
将固定 `scale_m2_per_px` 改为：

`scale_m2_per_px = paintable_surface_area_m2 / paintable_uv_pixels`

来源：
- `paintable_surface_area_m2` -> `model_assets.surface_area_m2`
- `paintable_uv_pixels` -> `model_assets.paintable_uv_pixels`

### 5.2 材料用量
保留原逻辑：`usage_kg_m2 * layers * area`，后续按产品类别扩展参数表。

### 5.3 施工难度
保留公式（颜色数、渐变、图案复杂度、面积），新增模型来源置信标识，不直接改分。

### 5.4 报告置信度（新增）
建议规则：
- HIGH：用户上传权威模型
- MEDIUM：系统标准模型
- LOW：自动生成近似模型

示例字段：
- `confidence_level`
- `confidence_reason`

## 六、开发路线图
1. 基础框架：React/Vite、FastAPI、JWT、会议与 WebSocket
2. 基准模型模块：模型来源三路径、模型资产与任务表、归一化和 UV、锁定机制
3. 画布与 AI：Fabric.js、UV 背景、AI 对话、图案生成、状态保存
4. 协作与工程：方案收集、聚类、工程估算、报告、投票
5. 3D 预览与导出：纹理切换、多方案预览、导出、授权控制

## 七、开发与部署配置

### 7.1 环境变量
`ANTHROPIC_API_KEY`
`OPENAI_API_KEY`
`TRIPO_API_KEY`
`MESHY_API_KEY`
`HYPER3D_API_KEY`
`DATABASE_URL`
`SECRET_KEY`
`FILE_STORAGE_PATH`
`MODEL_LIBRARY_PATH`
`ALLOW_EXTERNAL_MODEL_EXPORT`
`BASE_MODEL_TIMEOUT_SEC`
`BLENDER_BIN`
`REDIS_URL`

### 7.2 本地开发启动
- frontend：`cd frontend && npm run dev`（或根目录执行 `npm run frontend:dev`）
- backend：`cd backend && uv sync && uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload`

### 7.3 生产部署
- 前端：Vercel/Nginx 静态托管
- 后端：应用服务与 Worker 分离
- DB：PostgreSQL
- 存储：S3/OSS
- AI API：按需调用
- 模型导出：基于授权策略

## 八、风险与应对
- 自动生成近似模型精度不足（高）：标注 Approximate，允许设计前替换
- 多产品 UV 规范不统一（中）：统一 `uv_template_url + mapping_meta`
- 外部授权限制导出（高）：默认禁导底模，仅导预览包
- 3D 任务耗时（中）：异步任务 + 进度反馈 + 默认模板回退
- API 成本超预期（中）：会议级限额，阶段 1 仅一次模型生成
- 工程估算误差（中）：`confidence_level` 分层
- 多产品参数不统一（中）：模板配置中心，按类别扩展

## 文档更新记录
- v1.0（2026-03-21）：原方案版本
- v1.1（2026-03-21）：引入会话级统一基准模型机制，新增三路径模型来源，统一多产品族外观展示底模体系
