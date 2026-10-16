# BankRAG Windows 演示与部署步骤

本文按项目现有 Docker Compose 拓扑编写：FastAPI、MySQL、Redis 使用 Compose；Milvus 继续使用宿主机已有实例；BGE-M3、重排器和 BERT 权重从本地目录挂载。此步骤用于本机求职演示，不代表生产部署。

## 启动前检查

1. Docker Desktop 已启动，`docker info` 能连接 Engine。
2. 本机已有 Milvus，并且集合别名 `finance_deposit_v1_active` 已发布。Compose 容器通过 `host.docker.internal:19530` 访问它。
3. `rag_qa/models/` 中有 BGE-M3、BGE-Reranker-Large 和 `finance_intent_classifier` 模型文件。
4. `.env` 已在本机创建并填写 DashScope 环境变量；不要把该文件提交到仓库或贴进聊天/日志。项目的 `.gitignore` 已忽略 `.env`。
5. 首次构建需要能访问 Docker 镜像源和 Python 包源；如果镜像源拒绝请求，Compose 配置检查仍可通过，但镜像构建不能视为成功。

## PowerShell 启动

在 `qa_system` 目录执行：

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
notepad .env
docker compose config --quiet
docker compose up -d --build
docker compose ps
Invoke-RestMethod http://127.0.0.1:8090/health
```

在编辑器中只在本机填写 `.env`。`docker compose config --quiet` 检查 Compose 展开结果，不会拉取镜像或证明服务可用。应用容器等待 MySQL/Redis 健康后启动；应用的健康状态还要求 Milvus 与分类模型可用。

## 首次准备数据

等 `docker compose ps` 显示 MySQL、Redis 健康且 app 可访问后，在 app 容器内执行：

```powershell
docker compose exec app python faq_to_mysql.py --dry-run
docker compose exec app python ingest.py --dry-run
docker compose exec app python faq_to_mysql.py
docker compose exec app python ingest.py --ingest-only
Invoke-RestMethod http://127.0.0.1:8090/health
```

FAQ 会写入 Compose 的 `bank-rag-mysql` 服务；向量快照发布到外部 Milvus。重复执行导入应按项目幂等规则处理；先看 dry-run 输出再发布。

## 检查与停止

- 查看状态：`docker compose ps`
- 查看应用日志：`docker compose logs --tail 100 app`
- 访问网页：`http://127.0.0.1:8090/`
- 停止容器但保留命名卷：`docker compose down`

Compose 暴露的宿主机端口为 app `8090`、MySQL `3308`、Redis `6380`；容器之间使用服务名和容器端口通信。删除命名卷会清除演示数据库数据，只有在确认不再需要这些数据时才手动清理。

## 2026-10-16 部署验证记录

- `docker compose --env-file local_secrets.env config --quiet` 通过；`docker compose --env-file local_secrets.env build app` 成功，CPU 镜像约883 MB。
- `docker compose --env-file local_secrets.env up -d` 后，app、MySQL、Redis 均为 `healthy`；`GET /health` 返回 200，MySQL、Redis、Milvus、分类器均通过。
- 容器内 HTTP 和 WebSocket 分别测试公开存款问答和投资建议拒答，共4个定向业务路径通过；答案引用、固定免责声明、WebSocket 首帧免责声明、会话历史4轮均通过。
- 本次使用宿主机 Milvus 中已有的演示知识快照，未重新导入 FAQ 或向量数据。首次启动时修复了 Redis 健康检查认证配置。
- 该记录是本机部署冒烟，不代表干净机器构建、浏览器访问、公网链路或生产验收；金融知识仍是演示资料。
