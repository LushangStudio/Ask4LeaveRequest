# 数据模型与存储

本轮已采用数据库持久化，PDF 也保存在数据库中，避免文件系统与数据库备份不一致。

| 表 | 保存内容 |
| --- | --- |
| people | 服务端用户、角色、学生班级资料；旧 counselor 列保留兼容 |
| directory_members | 运维名单中的有效身份；移除后既有会话也失去访问权 |
| request_counselors | 提交时班级全部辅导员审批范围快照，多对多 |
| counselor_signatures | 辅导员本人裁切的 PNG、版本、摘要、更新时间 |
| approval_signatures | 一次实际审批对应的带纯黑点阵水印签名快照 |
| approval_previews | 15 分钟有效的申请/审批人/签名版本/意见绑定及水印图片 |
| demo_sessions | 登录会话的 SHA-256 摘要、身份和到期时间，不保存原始令牌 |
| test_login_sessions | 密钥入口会话标签和密钥摘要，关闭/轮换后可拒绝旧会话；删除会话时级联删除 |
| uis_login_sessions | UIS 来源标签与 user_type，不按类型过滤，删除会话时级联删除 |
| oauth_states | 有效期内一次性消费的 state 摘要，不保存原始 state |
| leave_requests | 原因、起止日期、生成方式、学生信息快照、审批状态、文件状态、幂等标识 |
| leave_items | 课程/活动/其他事项、名称、日期、时间、排序 |
| approval_records | 一份申请对应一条最终审批，保存审批人姓名快照、结果、意见、时间 |
| request_withdrawals | 学生撤回/辅导员撤回的操作者、原因、时间及原状态 |
| class_directory | 当前班级/人员配置及版本摘要，数据库唯一名单来源 |
| directory_audits | 管理员名单更新的操作者、前后文件摘要、人数及时间 |
| generated_documents | PDF 二进制、申请关联、顺序、文件名与内容摘要 |

业务状态：`pending → approved / rejected`。文件状态：`not_started → generating → ready / failed`，失败重试 `failed → generating`。文件失败不会回退业务状态。

生成方式为 `combined`（默认）或 `separate`，提交后固定。合并的一份 PDF 在长文本时可以自然分页，不强行缩小文字塞入一页。未通过申请没有 PDF。

MySQL URL 格式为 `mysql+pymysql://ask4leave:<URL编码后的密码>@127.0.0.1:3306/ask4leave?charset=utf8mb4`。PDF 使用 MEDIUMBLOB。MySQL 会话默认事务由 SQLAlchemy 管理；应用使用条件更新抢占审批和生成，唯一约束防止重复审批和重复文件。

`schema.mysql.sql` 由当前 SQLAlchemy 模型生成，是新建空库的参考结构。仅结构编译通过不等于 MySQL 实例集成测试通过；目前自动化闭环使用 SQLite。MySQL 切换须另行运行同一验收流程，尤其检查 utf8mb4、PDF 大小、事务回滚和用户权限。

时间戳采用带 UTC 标识的 ISO 8601 字符串，界面转换为浏览器当地时间；事项日期为学校本地业务日期。数据库账号只访问自己的库，不与 WordTxT 共用密码。正式上线前确认数据保留期限、删除流程及备份恢复要求。

## 申请撤回与请假条撤回

学生仅可将本人 pending 申请变为 withdrawn；负责该申请的辅导员可将 approved 变为 revoked。双方仍可查看记录，状态不可恢复或重新审批。request_withdrawals 保存操作者、角色、时间、原状态与原因，原审批、签名和 PDF 留作历史数据；撤回后 API 不再提供 PDF，旧文件 URL 返回 410，生成重试和审批预览拒绝。系统不能收回此前已下载的文件。并发生成以条件更新发布，撤回获胜后不发布新 PDF。

已有 MySQL 库先备份，再由迁移账号执行 docs/migrations/005-request-withdrawals.mysql.sql，然后部署并重启服务。运行账号仍仅需 DML；空库使用最新 schema.mysql.sql。

## 申请附件

每份申请允许 0–3 个附件，每个最多 5 MiB；附件与申请、事项在同一事务中保存至 `request_attachments`，重试提交不会重复保存。历史申请附件列表为空。附件内容不进入申请列表响应，也不合并进 PDF；仅原申请学生及该申请范围内的辅导员可以下载（包含已审批、驳回或撤回记录）。所有附件以强制下载、禁止 MIME 嗅探的方式返回，不在服务端执行或解析。

既有 MySQL 库先备份，再以迁移账号执行 `docs/migrations/010-request-attachments.mysql.sql`，无需删除或改写旧数据。运行账号继续使用原有 DML 权限。新库使用最新 `schema.mysql.sql`。回滚应用可以保留新增表，不能通过删表回滚，否则会丢失附件。数据库备份会包含附件，应留意容量增长。

部署前将 Nginx `/leave/` 的 `client_max_body_size` 从 `5m` 调整为 `22m`（运维仓库模板已更新），执行 `nginx -t` 后再 reload。申请 JSON 使用 base64 携带文件，三份 5 MiB 文件约占 20 MiB，请求上限设为 22 MiB；只有 `POST /api/requests` 放宽，其他接口保持 4,300,000 字节限制。MySQL `max_allowed_packet` 应至少为 32 MiB（MySQL 8 默认通常足够，部署时核验）。数据库迁移和 Nginx 配置须先完成，再发布应用。

## 两种请假方式与附件保留期

新申请传入 `mode=date_range` 或 `mode=items`。日期模式必须有起止日期、无事项，只生成一份 PDF；事项模式必须有 1–30 个事项，不接受手填起止日期，后端取最早和最晚事项日期保存为查询及清理边界。事项模式保留合并／分别生成选项，正文不将不连续事项描述成连续请假天数。旧客户端省略 mode 时保持原验证规则和幂等摘要；旧记录标为 legacy，原 PDF 不重写。

上线前以迁移账号执行 `docs/migrations/011-application-mode.mysql.sql`（一次），给已有表新增 mode，默认 legacy。本地已有 SQLite 自动添加此列；MySQL 不会用运行账号修改表结构。回滚代码时保留此列及附件表，勿删除历史数据。

附件截止日期为请假结束日期加一个自然月（月底超出则取目标月最后一天），保留到该日北京时间 23:59:59。例如 10 月 22 日结束，保留至 11 月 22 日；1 月 31 日结束，非闰年保留至 2 月 28 日。事项模式使用最晚事项日期，与填写顺序无关。期限对所有审批状态生效，不因驳回或撤回重新计时。

服务启动时清理，运行中每小时重试清理，停机期间到期的数据会在下次启动清理；下载接口在截止日之后立即拒绝访问，无需等待物理清理。清理删除附件行及字节，不删除申请、事项、签名、审批记录或生成 PDF。历史数据库备份仍按既有备份轮换策略留存；恢复旧备份后启动服务会重新执行清理。
