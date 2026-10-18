"""Operator-owned directory. Never accept roster edits from a browser."""
import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Identifier = Annotated[str, Field(min_length=1, max_length=40, pattern=r'^[A-Za-z0-9_-]+$')]
Name = Annotated[str, Field(min_length=1, max_length=80)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, str_strip_whitespace=True)


class CounselorConfig(StrictModel):
    user_id: Identifier
    name: Name


class StudentConfig(StrictModel):
    user_id: Identifier
    class_id: Identifier
    college: Name
    major: Name
    grade: Annotated[str, Field(min_length=1, max_length=20)]

    @model_validator(mode='before')
    @classmethod
    def discard_legacy_name(cls, data):
        # Read old rosters safely, but never serialize or persist their names.
        if isinstance(data, dict):
            return {key: value for key, value in data.items() if key != 'name'}
        return data


class ClassConfig(StrictModel):
    class_id: Identifier
    name: Name
    counselor_ids: list[Identifier] = Field(min_length=1)


class DirectoryConfig(StrictModel):
    version: Literal[1]
    counselors: list[CounselorConfig]
    classes: list[ClassConfig]
    students: list[StudentConfig]

    @model_validator(mode='after')
    def check_relationships(self):
        for members in (self.counselors,self.students):
            ids=[p.user_id for p in members]
            if len(ids)!=len(set(ids)):raise ValueError('同一角色中的学工号不得重复')
        counselors = {p.user_id for p in self.counselors}
        classes = {c.class_id for c in self.classes}
        if len(classes) != len(self.classes):
            raise ValueError('班级编号不得重复')
        for group in self.classes:
            if len(set(group.counselor_ids)) != len(group.counselor_ids):
                raise ValueError('同一班级的辅导员不得重复')
            if not set(group.counselor_ids) <= counselors:
                raise ValueError('班级引用了未配置的辅导员')
        if any(p.class_id not in classes for p in self.students):
            raise ValueError('学生引用了未配置的班级')
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
    if any(not p.user_id.startswith('test-') for p in test.counselors+test.students) or any(not c.class_id.startswith('test-') for c in test.classes):
        raise ValueError('附加测试名单只接受 test- 身份与班级')
    return DirectoryConfig.model_validate({'version':1,
        'counselors':[p.model_dump() for p in base.counselors+test.counselors],
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
