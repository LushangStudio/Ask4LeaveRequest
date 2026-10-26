# Ask4LeaveRequest

请假申请与审批：学生提交多个课程、活动或其他事项，班级内任一辅导员审批，系统生成带签名的中文 PDF。默认合并为一份，也可选择每项一份。师生班级关系由管理员在线管理并持久化到数据库；辅导员可上传并自由裁切签名、审批前预览，签名图片包含请假人及请假日期范围的纯黑点阵水印。申请、审批与签名快照、文件状态和 PDF 内容均存入数据库。未实现密码学电子签名或验真。

PDF 使用正式文书版式：居中“请假条”标题，正文以“兹证明……”介绍学生身份，叙述请假事由和日期，右下方落签名及日期。新申请统一填写具体事项，正文采用“该生因【请假原因】，于【日期】【时间或节次】请假【事项名称】。”，多项逐项叙述。水印单日只显示当天，多日显示最早至最晚日期；电子签名下方不重复打印辅导员姓名。模板变更仅影响新生成文件，不改写已留存的历史 PDF。

生产模式 `APP_MODE=production` 使用复旦 UIS 授权码登录，协议与 WordTxT 一致，没有本专科生类型限制；应用角色、班级和审批范围来自数据库名单。需要服务器上的 UIS 凭据与允许的 HTTPS 回调；ADMIN_USER_IDS 配置管理员。普通本地演示使用 `APP_MODE=demo`，默认使用虚构的两个班级、两位学生与三位辅导员。未指定模式或生产缺少凭据会拒绝启动。

另支持独立的密钥联调入口，可与生产 UIS 同时开启：仅允许运维名单中的 `test-` 用户，通过 `?secret=…&uid=test-123` 登录；正式用户不能借此登录。入口可配置关闭，默认为关闭；当前上线要求关闭旧调试入口。纯测试部署也可用 `APP_MODE=test`。旧测试名单一次性迁移与部署记录见 [联调及 UIS 部署说明](docs/test-login-deployment.md)。

网页视觉风格与 WordTxT 对齐。两套应用都有返回应用列表入口；请假生产用户名块可展开 UIS 退出，测试账号展开本地退出。`APP_LIST_URL` 默认 `/`，本地整站可指定 `http://127.0.0.1:8080/?showall`。

## 启动

需要 Python 3.10+ 和 Node.js 22.13+。在本仓库目录运行：

```bash
npm ci
npm run build
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
APP_MODE=demo .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --workers 1
```

打开 <http://127.0.0.1:8001/>。数据库默认保存到 `var/leave.db`，重启后记录保留。macOS 自动使用系统黑体；Ubuntu 先安装 `fonts-wqy-zenhei`，或设置 `PDF_FONT_PATH` 为可嵌入的中文 TTF/TTC 字体。字体仅用于运行时读取，不随仓库分发。

文书正文优先使用可嵌入的宋体（macOS 的 Songti SC Regular），标题使用黑体。可用 `PDF_BODY_FONT_PATH` 和 `PDF_TITLE_FONT_PATH` 分别指定字体；没有对应字体时回退到 `PDF_FONT_PATH`/已有中文字体。Ubuntu 可额外安装 `fonts-arphic-uming` 使用宋体，原有黑体回退仍可运行。

与首页联动：另一个终端进入相邻 `Lushangstudio-Home`，运行 `python3 scripts/serve.py`，打开 <http://127.0.0.1:8080/>。此本地入口将 `/leave/` 代理至 8001，不改变线上站点。

## Vue 3 前端开发与构建

`src/` 保存 Vue 3 单文件组件、CSS 和 API 模块源码（Composition API / `<script setup>`），Vite 生成 `dist/`，压缩 HTML/CSS/JS 并为资源生成内容哈希。FastAPI 只提供构建产物，不直接发布源码。相对资源路径兼容直接访问 8001 和入口站点的 `/leave/`。

- `npm run dev`：在 <http://127.0.0.1:5175/> 热更新开发，`/api` 代理到 8001；仍需启动演示后端。
- `npm run build`：生成构建产物；修改源码后重新构建即可更新 8001/8080 页面。
- `npm run preview`：在 <http://127.0.0.1:4175/> 检查构建产物，API 同样代理到 8001。
- `npm run format` / `npm run format:check`：格式化 / 检查源码。

本地完整站点启动脚本会自动执行前端构建。准备发布包时先运行 `npm ci && npm run format:check && npm run build`，将 `dist/` 随 Python 应用一起交付；目标机器无需 Node.js。`node_modules/` 和 `dist/` 不提交 Git。服务器按已授权的源码 CD 流程构建部署。

## 演示步骤

1. 选择“学生甲”，点击“切换身份”。填写日期、原因，添加课程和活动等多个事项。
2. 选择默认“合并生成”，或改为“分别生成”，提交。
3. 切换“辅导员甲”，上传手写签名截图，拖动选区或四角裁切后保存。填写审批意见，点击“预览并审批”，核对带签名的 PDF 后确认通过；也可填写原因后直接驳回。
4. 切回“学生甲”，查看审批结果和 PDF。
5. 切换“学生乙”或“辅导员乙”，确认看不到甲的申请及文件；辅导员丙负责两个班级，可处理甲、乙两班申请。已通过申请可由负责辅导员撤回至待审批，再次预览后重新通过或驳回；历史审批和撤回记录保留，旧 PDF 永久失效。

申请不可直接编辑；驳回后可新建申请。每位学生只能属于一个班级，每班可有多位辅导员，同一辅导员可负责多个班级。关系来自运维配置，学生不能在表单中指定。生成失败保留已通过结果和签名快照，可以重试。重复提交标识保证网络重试不会创建重复申请；重复审批不会重复生成；同一批文件在数据库事务中一并保存，避免半份文件。

格式、导入校验、权限与历史记录处理见 [运维配置说明](docs/operator-configuration.md)。生产名单以数据库为准，管理员独立页面支持学生与班级管理、班级辅导员关联及 CSV 批量导入；旧 JSON 仅可一次性迁移，本地虚构 fixture 只初始化全新 demo/test 数据库。

## 数据库

SQLite 用于本地演示。MySQL 8 使用 SQLAlchemy + PyMySQL，PDF 存入 MEDIUMBLOB，事务信息和文件一起备份。参见 [数据库说明](docs/database.md) 及相邻运维仓库的 MySQL 指南。

```bash
# 从权限为 0600 的本地环境文件加载，不把密码写入命令历史。
set -a
. ./.env
set +a
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --workers 1
```

`.env` 不会被程序自动读取。首次启动创建空库表，不依靠 `create_all` 修改旧表。本次为班级审批范围和签名增加五张独立表，既有 MySQL 数据库参考 `docs/migrations/002-class-signatures.mysql.sql`；本地 SQLite 自动增加新表并保留旧记录。不自动迁移 SQLite 既有数据到 MySQL。

## 检查

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

测试覆盖合并/分开生成、中文 PDF 内容、多班/多辅导员权限、并发审批、配置校验和身份停用、签名及预览权限、意见/签名变化与预览过期、纯黑点阵二值化、历史签名快照、重复请求、日期校验、驳回、部分生成失败的回滚与重试、长文本分页及正式模式启动保护。

## 正式接入前

参见 [ehall 接入边界](docs/ehall.md)。演示登录可自由切换虚构身份，不是身份认证；禁止向公网代理本演示 API。PDF 包含带水印的手写签名图片，不具备密码学验真功能，正式模板还需业务方确认。当前同步生成固定单 worker；扩容前需任务队列、任务租约与恢复机制。现有服务器梳理与独立 systemd/Nginx/环境文件模板在相邻运维仓库 `docs/leave-readiness-2026-10-12.md`，模板未部署。

管理员独立班级管理页、管理员配置和升级步骤见 [docs/class-management.md](docs/class-management.md)。

请假结束日期最多为北京时间当前日期后三个自然月，月末按目标月最后一天处理；前后端均校验。

## 持续集成

GitHub Actions `CI / Build and test` 在 main 推送、Pull Request 及手动触发时运行。Ubuntu 干净环境使用 Node 22、Python 3.10 和中文字体，依次执行 `npm ci`、格式检查、Vite 构建、Python 依赖检查与全部 pytest；同时验证 `/`、`/leave/` 下实际构建资源可加载，且构建产物、数据库和运行环境文件未被 Git 跟踪。工作流只有仓库读取权限，不读取生产密钥，也不连接或部署生产服务器。

本地运行测试前先执行 `npm ci && npm run build`；测试使用临时数据库及虚构身份。

## 1.1.0 验收与升级

逐条核对见 [1022 迭代建议验收](docs/acceptance-1.1.0.md)。部署前执行新增表迁移 `docs/migrations/012-approval-archives.mysql.sql`，无需删除现有数据。旧版已经撤回的终态记录不自动恢复；新版本辅导员撤回后回到待审批。原审批元数据、签名快照和文件摘要归档，失效的 PDF 内容删除，旧下载地址永久不可用。

### 临时 PDF 下载链接

普通下载由已登录且有权限的用户生成，链接有效期为 180 秒，有效期内不限下载次数；外部浏览器无需应用登录 Cookie。请假条撤回、文件删除或审批预览失效后，链接同时失效。原登录下载接口继续保留。

服务在 `LEAVE_DATA_DIR/download-link.key` 自动创建权限为 `0600` 的签名密钥；须保留该文件并让同一部署的所有进程共享。无需数据库迁移。密钥不应提交仓库或公开；删除或轮换密钥会使已发出的链接失效。临时链接也是访问凭据，不应转发；日志中的 `/api/public-pdfs/` 路径应按敏感下载链接处理。免登录仅针对本应用，不绕过学校 WebVPN 的访问认证。
