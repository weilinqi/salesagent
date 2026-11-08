# 对练连接修复

本次排查发现：本地 `backend/.env` 的 `PORT` 为 8011，而 Vite 的 HTTP 和 WebSocket 代理固定为 8002。浏览器显示“正在连接 AI 服务器”实际表示 WebSocket 未建立，此时尚未进入模型调用。

现在 Vite 只读取后端的 PORT 字段，HTTP 和 WebSocket 代理共享端口配置；未配置时仍使用 8002。不读取或向前端注入模型密钥。开发与 preview 模式均应用代理。Docker/Nginx 的容器后端端口仍由其部署配置管理。

连接握手超过 10 秒会关闭旧连接并按原有上限重试；重试耗尽或被服务器拒绝时显示失败提示，并提供“重新连接”，不再一直显示连接中。

## 使修复生效

停止旧前端进程，重新在 frontend 目录执行 `npm run dev`，然后刷新浏览器。修改 backend/.env 的 PORT 后也需要重启前端。

后端需运行在相同的 PORT 上。例如在 backend 目录执行 `..\.venv\Scripts\python.exe -m app.main`，该入口读取 settings.PORT。使用 uvicorn 命令启动时，应明确选择与 PORT 一致的端口。

开发页面一般为 `http://localhost:5173`。页面的准确 Origin（协议、主机和端口）必须在 backend/.env 的 CORS_ORIGINS 中；本次没有放宽该校验。线上页面还需部署新构建，并由部署环境正确转发 /ws/ 的 Upgrade 请求。

## 验证证据

- 49 项前端离线回归通过；TypeScript、Vite 构建和 ESLint 通过。
- 使用临时 SQLite、测试身份和已有测试消息，实际启动临时后端与 Vite，验证真实配置的 HTTP 代理到 8011 返回 200，WebSocket 经代理完成认证握手及消息收发。
- 临时服务已关闭；未访问真实历史记录或调用付费模型。生产部署及真实 MiniMax 响应未验证。
