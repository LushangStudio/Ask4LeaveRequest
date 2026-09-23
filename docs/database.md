# 数据模型与存储

本轮已采用数据库持久化，PDF 也保存在数据库中，避免文件系统与数据库备份不一致。

| 表 | 保存内容 |
| --- | --- |
| people | 服务端的用户、角色、学生所属辅导员、个人资料 |
| demo_sessions | 演示会话的 SHA-256 摘要、身份和到期时间，不保存原始令牌 |
| leave_requests | 原因、起止日期、生成方式、学生信息快照、审批状态、文件状态、幂等标识 |
| leave_items | 课程/活动/其他事项、名称、日期、时间、排序 |
| approval_records | 一份申请对应一条最终审批，保存审批人姓名快照、结果、意见、时间 |
| generated_documents | PDF 二进制、申请关联、顺序、文件名与内容摘要 |

业务状态：`pending → approved / rejected`。文件状态：`not_started → generating → ready / failed`，失败重试 `failed → generating`。文件失败不会回退业务状态。

生成方式为 `combined`（默认）或 `separate`，提交后固定。合并的一份 PDF 在长文本时可以自然分页，不强行缩小文字塞入一页。未通过申请没有 PDF。

MySQL URL 格式为 `mysql+pymysql://ask4leave:<URL编码后的密码>@127.0.0.1:3306/ask4leave?charset=utf8mb4`。PDF 使用 MEDIUMBLOB。MySQL 会话默认事务由 SQLAlchemy 管理；应用使用条件更新抢占审批和生成，唯一约束防止重复审批和重复文件。

`schema.mysql.sql` 由当前 SQLAlchemy 模型生成，是新建空库的参考结构。仅结构编译通过不等于 MySQL 实例集成测试通过；目前自动化闭环使用 SQLite。MySQL 切换须另行运行同一验收流程，尤其检查 utf8mb4、PDF 大小、事务回滚和用户权限。

时间戳采用带 UTC 标识的 ISO 8601 字符串，界面转换为浏览器当地时间；事项日期为学校本地业务日期。数据库账号只访问自己的库，不与 WordTxT 共用密码。正式上线前确认数据保留期限、删除流程及备份恢复要求。
