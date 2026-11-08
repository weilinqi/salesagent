# 对练连接修复

本次排查发现：本地 `backend/.env` 的 `PORT` 为 8011，而 Vite 的 HTTP 和 WebSocket 代理固定为 8002。浏览器显示“正在连接 AI 服务器”实际表示 WebSocket 未建立，此时尚未进入模型调用。

后续现场验证发现，后端实际上通过启动参数运行在 8002，覆盖了 `.env` 的 8011。不能把 `.env` 当成正在运行的服务地址。现已修正：HTTP 和 WebSocket 默认都代理到 8002；只有明确在 frontend/.env.local 设置 `SALESAGENT_BACKEND_PORT` 时才使用其他端口。不读取或向前端注入模型密钥。开发与 preview 模式均应用代理。Docker/Nginx 的容器后端端口仍由其部署配置管理。

连接握手超过 10 秒会关闭旧连接并按原有上限重试；重试耗尽或被服务器拒绝时显示失败提示，并提供“重新连接”，不再一直显示连接中。

## 使修复生效

Vite 监听配置文件变更后会重载代理；若仍运行旧配置，停止旧前端进程，在 frontend 目录重新执行 `npm run dev`，然后刷新浏览器。若后端实际启动在其他端口，在 frontend/.env.local 设置 `SALESAGENT_BACKEND_PORT=实际端口`，再重启 Vite。

后端需运行在前端所指定的端口。例如默认代理 8002 时，在 backend 目录执行 `..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8002`。`python -m app.main` 则读取 settings.PORT；命令行 --port 优先于配置文件，核对时应以实际监听端口为准。

开发页面一般为 `http://localhost:5173`。页面的准确 Origin（协议、主机和端口）必须在 backend/.env 的 CORS_ORIGINS 中；本次没有放宽该校验。线上页面还需部署新构建，并由部署环境正确转发 /ws/ 的 Upgrade 请求。

## 验证证据

- 端口修正后 50 项前端离线回归通过；TypeScript、Vite 构建和 ESLint 通过。新增测试直接加载真实 Vite 配置，验证显式运行端口优先，不受 backend/.env PORT 干扰。
- 使用临时 SQLite、测试身份和已有测试消息，实际启动临时后端与 Vite，验证真实配置的 HTTP 代理到 8011 返回 200，WebSocket 经代理完成认证握手及消息收发。
- 临时服务已关闭；未访问真实历史记录或调用付费模型。生产部署及真实 MiniMax 响应未验证。
- 500 修复现场验证：8002 后端 /health 和 /ready 返回 200；修复前 5173 的 /api/v1/auth/me 返回 500，修复后返回正确的未登录状态 401，前端首页返回 200。
