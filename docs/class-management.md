# 在线班级管理、数据库与批量导入

班级管理页面独立于工作台：生产路径 `/leave/class-management/`。只有服务器配置中的管理员能看到入口和调用管理接口；直接访问页面不会暴露人员资料，非管理员 API 返回 403。管理员通过 UIS 登录，不要求先有学生班级或辅导员身份；管理员权限可叠加在学生/辅导员身份上。

## 管理员配置

在服务器 `/etc/ask4leave/ask4leave.env` 设置英文逗号分隔的真实 UIS 学工号，例如 `ADMIN_USER_IDS=ADMIN001,ADMIN002`，重启后生效。浏览器不能增删管理员；空值关闭管理权限。管理员无需先登记到学生/辅导员名单。

## 数据库为唯一名单来源

班级与人员关系持久化在 MySQL 的 class_directory 表，既有 people、directory_members 等业务权限表同时更新。class_directory.directory 为受控 JSON 数据列，并非服务器 JSON 文件；更新名单、同步权限和写入 directory_audits 在同一个数据库事务中完成。操作失败全部回滚。SHA-256 版本和条件更新防止旧页面覆盖其他管理员的修改。保存立即生效，无需重启；重启以数据库恢复，修改旧 JSON 文件不会覆盖在线名单。

生产已废弃 RELATIONSHIPS_PATH/TEST_RELATIONSHIPS_PATH，不读取旧关系 JSON。本地 demo/test 仅在全新数据库首次初始化时使用虚构 fixture；之后同样以数据库为准。测试入口仍由私有 TEST_LOGIN_CONFIG_PATH 控制，关闭 enabled 后重启会拒绝旧测试会话，不影响正式 UIS。

## 升级已有服务器

先停止服务并备份数据库。由迁移账号执行 005-request-withdrawals.mysql.sql、006-directory-audits.mysql.sql、007-database-directory.mysql.sql；部署新源码后，用新 release 的虚拟环境运行一次旧名单迁移：

```sh
cd /opt/ask4leave/current
.venv/bin/python -m app.import_directory /etc/ask4leave/relationships.json --test-roster /etc/ask4leave/relationships.test.json --env-file /etc/ask4leave/ask4leave.env
```

迁移工具不会打印名单或凭据，不自行建表。相同数据重跑不修改；已有非空数据库名单拒绝覆盖。如果新版本曾先启动、创建了空名单，可明确使用 --replace-empty，只允许替换空名单。将旧文件保留为受控历史备份，删除环境中两个废弃路径设置，之后所有在线修改只写数据库。配置 ADMIN_USER_IDS 和关闭测试入口后重启服务完成权限同步。不需授予服务写 /etc 的权限；MySQL 运行账号仍仅 DML。

全新生产数据库默认空名单，可以直接由配置中的管理员 UIS 登录并录入班级和人员，无需 JSON 文件。

## 在线编辑

在“班级”“辅导员”“学生”页签中添加、修改、删除，然后点击“保存全部更改”。辅导员工号用英文逗号分隔。删班级时同时给学生转班或移除；删辅导员时同时调整班级引用，班级至少一位辅导员。一个学工号可在学生和辅导员名单中各出现一次，姓名一致；学生仅一班，辅导员可多班，包括自己所在班级，允许自己审批。

删除人员停用业务权限，管理员只要仍在 ADMIN_USER_IDS 中就保留管理权限。历史申请、审批、签名和 PDF 保留，班级/辅导员变更只影响新申请。备份 MySQL 即包含名单、审批数据和签名。

## 批量导入学生

在学生页签粘贴 CSV，每行一人，六列：`学号,姓名,班级,学院,专业,年级`。可以带这行中文表头。使用英文逗号，含逗号的内容加双引号；空行忽略，学号前导零保留。班级填已创建的班级编号或唯一名称。

```csv
学号,姓名,班级,学院,专业,年级
STUDENT001,王同学,class-2026-a,管理学院,工商管理,2026
STUDENT002,赵同学,class-2026-a,管理学院,工商管理,2026
```

先保存当前编辑，再“校验并预览导入”。预览显示新增/更新人数、标准化数据与错误行，不写数据库。确认后提交；同学号更新已有学生资料，未出现的其他学生保留。同批学号重复、缺字段、未知或同名歧义班级、非法标识、兼任身份姓名不一致会报错；有任何错误整批不导入。每批最多 5000 人。确认时再次校验名单版本，避免旧预览覆盖新配置。
