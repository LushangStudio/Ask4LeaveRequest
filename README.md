# Ask4LeaveRequest

请假申请与审批的本地演示：学生提交多个课程、活动或其他事项，辅导员统一审批，系统生成中文 PDF。默认合并为一份，也可选择每项一份。申请、事项、审批快照、文件状态和 PDF 内容均存入数据库。不含验真、签名或电子印章。

当前版本是可运行的演示闭环，尚未接入 ehall，不能作为正式请假凭证。仅监听本机，使用虚构的两组学生与辅导员。未显式设置 `APP_MODE=demo` 时拒绝启动，避免误当正式系统部署。

## 启动

需要 Python 3.10+。在本仓库目录运行：

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
APP_MODE=demo .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --workers 1
```

打开 <http://127.0.0.1:8001/>。数据库默认保存到 `var/leave.db`，重启后记录保留。macOS 自动使用系统黑体；Ubuntu 先安装 `fonts-wqy-zenhei`，或设置 `PDF_FONT_PATH` 为可嵌入的中文 TTF/TTC 字体。字体仅用于运行时读取，不随仓库分发。

与首页联动：另一个终端进入相邻 `Lushangstudio-Home`，运行 `python3 scripts/serve.py`，打开 <http://127.0.0.1:8080/>。此本地入口将 `/leave/` 代理至 8001，不改变线上站点。

## 演示步骤

1. 选择“学生甲”，点击“切换身份”。填写日期、原因，添加课程和活动等多个事项。
2. 选择默认“合并生成”，或改为“分别生成”，提交。
3. 切换“辅导员甲”，通过或填写原因后驳回。
4. 切回“学生甲”，查看审批结果和 PDF。
5. 切换“学生乙”或“辅导员乙”，确认看不到甲的申请及文件。

申请不可直接编辑；驳回后可新建申请。每个学生对应的辅导员来自服务器端数据，学生不能在表单中指定。生成失败保留已通过结果，可以重试。重复提交标识保证网络重试不会创建重复申请；重复审批不会重复生成；同一批文件在数据库事务中一并保存，避免半份文件。

## 数据库

SQLite 用于本地演示。MySQL 8 使用 SQLAlchemy + PyMySQL，PDF 存入 MEDIUMBLOB，事务信息和文件一起备份。参见 [数据库说明](docs/database.md) 及相邻运维仓库的 MySQL 指南。

```bash
# 从权限为 0600 的本地环境文件加载，不把密码写入命令历史。
set -a
. ./.env
set +a
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --workers 1
```

`.env` 不会被程序自动读取。首次启动创建空库表，不是结构迁移系统；以后变更表结构必须增加有版本的迁移，不可依靠 `create_all` 修改旧表。本次不自动迁移 SQLite 既有数据到 MySQL。

## 检查

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

测试覆盖合并/分开生成、中文 PDF 内容、审批权限、文件权限、重复请求、日期校验、驳回、部分生成失败的回滚与重试、长文本分页、历史快照及正式模式启动保护。

## 正式接入前

参见 [ehall 接入边界](docs/ehall.md)。演示登录可自由切换虚构身份，不是身份认证；禁止向公网代理本演示 API。PDF 没有签名，不具备验真功能，正式模板还需业务方提供。当前同步生成适用于小规模演示，固定单 worker；生产需任务队列、任务租约与恢复机制，不能直接扩容多 worker。
