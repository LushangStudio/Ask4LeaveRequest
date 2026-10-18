"""Operator-owned directory. Never accept roster edits from a browser."""
import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Identifier = Annotated[str, Field(min_length=1, max_length=40, pattern=r'^[A-Za-z0-9_-]+$')]
Name = Annotated[str, Field(min_length=1, max_length=80)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, str_strip_whitespace=True)


def class_uuid(value):
    from uuid import UUID, uuid5, NAMESPACE_URL
    try:return str(UUID(value))
    except ValueError:return str(uuid5(NAMESPACE_URL, 'ask4leave:class:'+value))


class CounselorConfig(StrictModel):
    user_id: Identifier


class StudentConfig(StrictModel):
    user_id: Identifier
    major: Name
    class_id: str = Field(pattern=r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')


class ClassConfig(StrictModel):
    class_id: str = Field(pattern=r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
    name: Name
    grade: Annotated[str, Field(min_length=1, max_length=20)]
    department: Name


class ClassCounselorConfig(StrictModel):
    class_id: str
    user_id: Identifier


class DirectoryConfig(StrictModel):
    version: Literal[2]
    classes: list[ClassConfig]
    class_counselors: list[ClassCounselorConfig]
    students: list[StudentConfig]

    @property
    def counselors(self):
        return [CounselorConfig(user_id=uid) for uid in sorted({r.user_id for r in self.class_counselors})]

    def counselors_for(self, class_id):
        return [r.user_id for r in self.class_counselors if r.class_id==class_id]

    @model_validator(mode='before')
    @classmethod
    def migrate_v1(cls,data):
        if not isinstance(data,dict) or data.get('version')!=1:return data
        # Deterministic IDs keep migration/retries and existing references stable.
        ids={c['class_id']:class_uuid(c['class_id']) for c in data['classes']}
        known={c['user_id'] for c in data['counselors']}
        if len(known)!=len(data['counselors']):raise ValueError('辅导员学工号重复')
        classes=[];relations=[]
        for group in data['classes']:
            members=[s for s in data['students'] if s['class_id']==group['class_id']]
            grades={s['grade'] for s in members};departments={s['college'] for s in members}
            if len(grades)>1 or len(departments)>1:raise ValueError('旧班级的年级或院系不一致，请先统一旧名单资料')
            classes.append(dict(class_id=ids[group['class_id']],name=group['name'],
                grade=next(iter(grades),'待完善'),department=next(iter(departments),'待完善')))
            for uid in group['counselor_ids']:
                if uid not in known:raise ValueError('旧班级引用未知辅导员')
                relations.append(dict(class_id=ids[group['class_id']],user_id=uid))
        students=[]
        for student in data['students']:
            if set(student)-{'user_id','name','class_id','college','major','grade'}:raise ValueError('未知学生字段')
            if not isinstance(student['class_id'],str) or student['class_id'] not in ids:raise ValueError('学生引用未知班级')
            students.append(dict(user_id=student['user_id'],major=student['major'],class_id=ids[student['class_id']]))
        return dict(version=2,classes=classes,class_counselors=relations,students=students)

    @model_validator(mode='after')
    def check_relationships(self):
        classes={c.class_id for c in self.classes}
        if len(classes)!=len(self.classes):raise ValueError('班级重复')
        students=[s.user_id for s in self.students]
        if len(students)!=len(set(students)):raise ValueError('学号重复')
        relations=[(r.class_id,r.user_id) for r in self.class_counselors]
        if len(relations)!=len(set(relations)):raise ValueError('班级辅导员关系重复')
        if any(r.class_id not in classes for r in self.class_counselors):raise ValueError('辅导员关系引用未知班级')
        if any(not self.counselors_for(c) for c in classes):raise ValueError('班级至少需要一位辅导员')
        if any(s.class_id not in classes for s in self.students):raise ValueError('学生引用未知班级')
        return self


def read_directory(path: str) -> DirectoryConfig:
    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('JSON 对象包含重复字段')
            result[key] = value
        return result
    source = Path(path)
    if source.stat().st_size > 5 * 1024 * 1024:
        raise ValueError('师生关系配置不得超过 5 MiB')
    return DirectoryConfig.model_validate(json.loads(source.read_text(encoding='utf-8'), object_pairs_hook=unique_keys))


def read_directories(path: str, test_path: str | None = None) -> DirectoryConfig:
    base=read_directory(path)
    if not test_path:return base
    test=read_directory(test_path)
    return merge_directories(base,test)

def merge_directories(base: DirectoryConfig,test: DirectoryConfig) -> DirectoryConfig:
    if any(not p.user_id.startswith('test-') for p in test.counselors+test.students):
        raise ValueError('附加测试名单只接受 test- 身份与班级')
    return DirectoryConfig.model_validate({'version':2,
        'class_counselors':[p.model_dump() for p in base.class_counselors+test.class_counselors],
        'classes':[p.model_dump() for p in base.classes+test.classes],
        'students':[p.model_dump() for p in base.students+test.students]})


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='校验运维师生关系 JSON；不修改数据库，不打印个人信息')
    parser.add_argument('path')
    parser.add_argument('--test-roster',help='附加 test- 班级名单，校验合并后的引用和重复项')
    args = parser.parse_args()
    try:
        roster = read_directories(args.path,args.test_roster)
    except Exception:
        parser.exit(1, '配置校验失败：检查格式、必填字段、重复学工号、班级及辅导员引用。\n')
    print(f'配置有效：{len(roster.classes)} 个班级，{len(roster.counselors)} 位辅导员，{len(roster.students)} 位学生')
