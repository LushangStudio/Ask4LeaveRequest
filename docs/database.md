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
| generated_documents | PDF 二进制、申请关联、顺序、文件名与内容摘要 |

业务状态：`pending → approved / rejected`。文件状态：`not_started → generating → ready / failed`，失败重试 `failed → generating`。文件失败不会回退业务状态。

生成方式为 `combined`（默认）或 `separate`，提交后固定。合并的一份 PDF 在长文本时可以自然分页，不强行缩小文字塞入一页。未通过申请没有 PDF。

MySQL URL 格式为 `mysql+pymysql://ask4leave:<URL编码后的密码>@127.0.0.1:3306/ask4leave?charset=utf8mb4`。PDF 使用 MEDIUMBLOB。MySQL 会话默认事务由 SQLAlchemy 管理；应用使用条件更新抢占审批和生成，唯一约束防止重复审批和重复文件。

`schema.mysql.sql` 由当前 SQLAlchemy 模型生成，是新建空库的参考结构。仅结构编译通过不等于 MySQL 实例集成测试通过；目前自动化闭环使用 SQLite。MySQL 切换须另行运行同一验收流程，尤其检查 utf8mb4、PDF 大小、事务回滚和用户权限。

时间戳采用带 UTC 标识的 ISO 8601 字符串，界面转换为浏览器当地时间；事项日期为学校本地业务日期。数据库账号只访问自己的库，不与 WordTxT 共用密码。正式上线前确认数据保留期限、删除流程及备份恢复要求。

## 申请撤回与请假条撤回

学生仅可将本人 pending 申请变为 withdrawn；负责该申请的辅导员可将 approved 变为 revoked。双方仍可查看记录，状态不可恢复或重新审批。request_withdrawals 保存操作者、角色、时间、原状态与原因，原审批、签名和 PDF 留作历史数据；撤回后 API 不再提供 PDF，旧文件 URL 返回 410，生成重试和审批预览拒绝。系统不能收回此前已下载的文件。并发生成以条件更新发布，撤回获胜后不发布新 PDF。

已有 MySQL 库先备份，再由迁移账号执行 docs/migrations/005-request-withdrawals.mysql.sql，然后部署并重启服务。运行账号仍仅需 DML；空库使用最新 schema.mysql.sql。
