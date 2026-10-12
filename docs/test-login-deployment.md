# 当前部署更新

用户已要求关闭旧 test- 密钥入口，部署时 enabled=false 并重启。班级关系现由数据库和管理员页面管理，旧关系文件仅用于一次性迁移；详见 class-management.md。以下是早期联调部署记录，不再代表当前上线配置。

# test 班级联调入口（2026-10-12）

用户明确要求开启密钥 URL 登录并部署测试班级。该功能仅用于配置中的 `test-` 身份，不是正式 UIS/ehall 登录；不用浏览器提供的姓名或角色来决定权限。

## 已准备的名单

`config/relationships.test.json` 包含 `test-class` 班级；两位辅导员 `test-counselor-1`、`test-counselor-2`；三位学生 `test-123`、`test-124`、`test-125`。每位学生仅属于这个班级，两位辅导员均可审批，实际通过的辅导员签名留存。一位学生不能查看其他学生的申请。

## 私有密钥配置

本次已随机生成 256 bit 密钥，保存在本地 Git 忽略的 `var/test-login.json`，权限 0600，`enabled` 已设为 `true`。不要把该文件加入 Git、前端 dist、公开发布包或日志。部署时将这个现有文件通过受控方式复制到 `/etc/ask4leave/test-login.json`，保持入口开启；服务器上可用 root:ask4leave / 0640，让服务只读。

配置结构如下；示例省略真实密钥：

```json
{ "enabled": true, "secret": "此处填写随机生成的32至128位URL安全密钥" }
```

已有文件不要重新生成，否则用户手里的链接会失效。若在其他独立环境需要新建密钥，可运行 `python scripts/create-test-login-config.py /受控目录/test-login.json`；脚本使用随机数、0600 和排他创建，不覆盖现有配置，也不打印密钥。

## 启动与访问

最终生产部署使用 `APP_MODE=production`，接入与 WordTxT 相同的 UIS 授权码协议，并同时保持独立测试密钥入口开启。不能使用对外开放的 `demo` 模式。`/api/demo/login` 和身份枚举在生产禁用，真实会话必须来自 UIS；带测试标签的会话只允许有效 `test-` 身份。纯测试环境仍可用 `APP_MODE=test`，这时所有身份与班级都必须是 test-，也不会开放 demo 登录。

生产环境示例见相邻仓库 `Lushangstudio-operation/proposed/ask4leave.env.example`。正式名单放在 `/etc/ask4leave/relationships.json`，指定 `RELATIONSHIPS_PATH`；测试班级独立放在 `/etc/ask4leave/relationships.test.json`，指定 `TEST_RELATIONSHIPS_PATH`，两者合并校验后同步。首次没有正式名单时可用 `config/relationships.production.example.json` 的空名单，仍可载入测试班级。`TEST_LOGIN_CONFIG_PATH` 指向私有密钥。只启一个 worker、监听 127.0.0.1:8001。纯测试环境可参考 `ask4leave.test.env.example`。

UIS 的 authorize/token/userInfo/GLO 端点和 Basic/Bearer 请求与 WordTxT 一致。不使用本专科生 allowlist，不按 `user_type` 拒绝任何类型；应用角色和班级仍由运维名单决定。未知学工号没有默认辅导员/学生权限，提示联系运维配置。缺失、null 或空白学工号拒绝认证。生产必须配置 `UIS_OAUTH_CLIENT_ID`、`UIS_OAUTH_CLIENT_SECRET` 与 HTTPS 回调；可由部署智能体在服务器受控读取现有 WordTxT UIS 配置的协议/凭据，不能把密钥写入聊天或发布包。请假回调为 `/leave/api/auth/callback`，需确认 UIS 允许此回调，不能把它误发到 WordTxT 的 `/api/auth/callback`。

UIS state 为 10 分钟有效、数据库摘要一次性消费的随机令牌，浏览器单独的 HttpOnly/Lax Cookie 绑定；业务会话为独立的随机不透明 Cookie，不复用 WordTxT 会话 Cookie。生产强制 Secure，8 小时过期。点击 UIS 退出通过原生 POST 清理本应用会话后跳到复旦 GLO；测试会话退出仅清理测试会话。关闭测试密钥入口不影响正常 UIS 会话。

访问格式：`https://lushangstudio.fudan.edu.cn/leave/?secret=<私有配置中的secret>&uid=test-123`。辅导员只需把 uid 换为 `test-counselor-1` 或 `test-counselor-2`。

服务器验证功能已开启、密钥摘要恒时比较、uid 精确以 `test-` 开头且在有效名单中。不会自动新建 URL 里指定的人。参数缺失、重复、错误密钥、未知或非 test 用户均拒绝。成功设置 HttpOnly / SameSite=Strict 会话 Cookie，然后 303 跳转至不含参数的 `/leave/`；本地 Cookie 路径 `/` 时跳转到 `/`。角色完全来自服务器名单。

## 关闭与轮换

原子更新私有配置中的 `enabled=false` 后重启：新 URL 登录被拒绝，已有测试会话也失效。轮换 secret 后重启同样使旧链接与旧会话失效。配置没有设置时默认关闭，已配置路径读不到或开启时密钥格式不合法会拒绝启动。保持网站页面和健康接口可用不代表入口仍开启。

## 日志、迁移与发布

ASGI 中间件在路由之前从请求 scope 移除 `secret` 和 `uid`，只留下凭据摘要用于校验，因此 Uvicorn access log 不记录密钥。响应设置 `no-store`、`no-referrer`。Nginx 在 HTTP 上下文安装 `ask4leave-log-format.conf`，在 `/leave` 与 `/leave/` 使用只记 `$uri`、不记 `$request`/`$args`/Referer 的专用格式。学校更外层代理如记录原始 URL，需由有权运维限制日志访问或配置脱敏，不能从此应用控制。

新增 `test_login_sessions` 表保存测试会话来源和密钥摘要；`uis_login_sessions` 保存 UIS 来源/类型，`oauth_states` 保存一次性 state 摘要。均不保存原始 secret、OAuth token 或 Cookie。新空库使用最新 schema；旧 MySQL 使用迁移 002、003、004，由迁移账号执行。SQLite 服务启动时增加表。单 worker 小规模部署可以使用 `/var/lib/ask4leave/leave.db`，重启数据保留；不把请假数据混到 WordTxT 数据库。

发布包必须含实际工作区新增的 Vue 源码和编译后的 `dist/`、Python `app/`、依赖与测试名单；只执行旧提交的 `git archive` 会漏掉未提交文件。私有密钥单独传输，绝不进入公开包。先验证 8001，再安装独立 systemd 与 Nginx `/leave/`，保留 WordTxT `/api/` 路由、已有门户 devel 状态与回滚点。

部署验收应在私有终端构造 URL，勿打印密钥：验证正确密钥能登录 test 学生/辅导员并清理 URL，错误密钥/真实 uid 被拒绝，demo 登录返回 404，test 学生互不可见，提交、上传签名、审批预览和正式文书生成闭环可运行。密钥文件的 `enabled` 最终保持 `true`。
