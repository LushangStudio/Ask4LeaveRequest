"""Apply explicit roster changes; omitted rows are never deleted."""
from pydantic import Field, model_validator
from app.directory import StrictModel, ClassConfig, StudentConfig, Identifier, DirectoryConfig


class ClassChange(ClassConfig):
    counselor_ids: list[Identifier] = Field(min_length=1)


class DirectoryDelta(StrictModel):
    revision: str = Field(pattern=r'^[a-f0-9]{64}$')
    classes: list[ClassChange] = Field(default_factory=list, max_length=5000)
    deleted_classes: list[str] = Field(default_factory=list, max_length=5000)
    students: list[StudentConfig] = Field(default_factory=list, max_length=20000)
    deleted_students: list[Identifier] = Field(default_factory=list, max_length=20000)

    @model_validator(mode='after')
    def unique_operations(self):
        for rows, deleted, key in [(self.classes,self.deleted_classes,'class_id'),(self.students,self.deleted_students,'user_id')]:
            ids=[getattr(row,key) for row in rows]
            if len(ids)!=len(set(ids)) or len(deleted)!=len(set(deleted)) or set(ids)&set(deleted):
                raise ValueError('同一班级或学生不能重复修改或同时修改和删除')
        return self

    def apply(self, directory):
        classes={c['class_id']:dict(c) for c in directory['classes']}
        students={s['user_id']:dict(s) for s in directory['students']}
        for key in self.deleted_classes:
            if key not in classes:raise ValueError('要删除的班级不存在')
            del classes[key]
        for key in self.deleted_students:
            if key not in students:raise ValueError('要删除的学生不存在')
            del students[key]
        changed={c.class_id for c in self.classes}
        relations=[dict(r) for r in directory['class_counselors'] if r['class_id'] not in changed|set(self.deleted_classes)]
        for row in self.classes:
            classes[row.class_id]=row.model_dump(exclude={'counselor_ids'})
            relations.extend({'class_id':row.class_id,'user_id':uid} for uid in row.counselor_ids)
        for row in self.students:students[row.user_id]=row.model_dump()
        return DirectoryConfig.model_validate(dict(version=2,classes=list(classes.values()),students=list(students.values()),class_counselors=relations))
