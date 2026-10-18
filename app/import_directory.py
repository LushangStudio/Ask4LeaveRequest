"""One-time operator migration from retired JSON files into MySQL directory state."""
import argparse
from datetime import datetime,timezone
import os
from pathlib import Path
import shlex

def main():
    parser=argparse.ArgumentParser(description='一次性迁入旧JSON名单；不打印个人资料或凭据')
    parser.add_argument('path');parser.add_argument('--test-roster');parser.add_argument('--env-file')
    parser.add_argument('--replace-empty',action='store_true',help='允许替换初始化后的空名单，不覆盖非空数据库名单')
    args=parser.parse_args()
    if args.env_file:
        for line in Path(args.env_file).read_text().splitlines():
            line=line.strip()
            if not line or line.startswith('#'):continue
            key,separator,value=line.partition('=')
            if not separator:parser.exit(1,'环境配置格式不合法\n')
            parts=shlex.split(value,comments=False)
            if len(parts)!=1:parser.exit(1,'环境配置格式不合法\n')
            os.environ[key]=parts[0]
    from app.directory import read_directories
    from app.main import DirectoryState,engine,directory_digest
    from sqlalchemy.orm import Session
    try:
        directory=read_directories(args.path,args.test_roster).model_dump()
        digest=directory_digest(directory)
        with Session(engine) as db:
            state=db.get(DirectoryState,1)
            if state and state.digest==digest:print('名单已迁入，未作修改');return
            if state and (not args.replace_empty or any(state.directory.get(key,[]) for key in ['students','class_counselors','counselors','classes'])):
                parser.exit(1,'数据库已有名单，拒绝覆盖；请使用管理员页面管理\n')
            if state:state.directory,state.digest,state.updated=directory,digest,datetime.now(timezone.utc).isoformat()
            else:db.add(DirectoryState(id=1,directory=directory,digest=digest,updated=datetime.now(timezone.utc).isoformat()))
            db.commit()
    except Exception:parser.exit(1,'迁移失败，请检查名单、数据库环境和新表迁移；未输出凭据\n')
    print('旧名单已迁入数据库，请重启应用完成权限同步；之后JSON文件不再生效')

if __name__=='__main__':main()
