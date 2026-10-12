"""Validate one student per CSV line without changing persisted data."""
import csv
import io
from app.directory import DirectoryConfig,StudentConfig
from pydantic import ValidationError

HEADER=['学号','姓名','班级','学院','专业','年级']

def preview_import(text,directory):
    data=directory.model_dump()
    classes={c.class_id:c.class_id for c in directory.classes}
    names={}
    for group in directory.classes:names.setdefault(group.name,[]).append(group.class_id)
    existing={s.user_id:s for s in directory.students}
    counselors={c.user_id:c.name for c in directory.counselors}
    imported=[];errors=[];seen=set();created=updated=0
    reader=csv.reader(io.StringIO(text.lstrip('\ufeff')),strict=True)
    try:
        for fields in reader:
            line=reader.line_num
            fields=[s.strip() for s in fields]
            if not fields or all(not s for s in fields):continue
            if line==1 and fields==HEADER:continue
            if len(imported)+len(errors)>=5000:
                errors.append({'line':line,'message':'每次最多导入5000人'});break
            if len(fields)!=6:
                errors.append({'line':line,'message':'须填写六列：学号,姓名,班级,学院,专业,年级'});continue
            uid,name,group,college,major,grade=fields
            if uid in seen:
                errors.append({'line':line,'message':'本次导入学号重复'});continue
            seen.add(uid)
            class_id=classes.get(group)
            if not class_id:
                matches=names.get(group,[])
                if len(matches)!=1:
                    errors.append({'line':line,'message':'班级不存在或名称不唯一，请使用班级编号'});continue
                class_id=matches[0]
            try:student=StudentConfig(user_id=uid,name=name,class_id=class_id,college=college,major=major,grade=grade)
            except ValidationError:
                errors.append({'line':line,'message':'必填内容为空或格式/长度不合法'});continue
            if uid in counselors and counselors[uid]!=name:
                errors.append({'line':line,'message':'兼任辅导员的学工号必须使用相同姓名'});continue
            if uid in existing:updated+=1
            else:created+=1
            imported.append(student.model_dump())
    except csv.Error:errors.append({'line':reader.line_num,'message':'CSV引号或分隔格式不合法'})
    if not imported and not errors:errors.append({'line':1,'message':'请至少填写一名学生'})
    result={s['user_id']:s for s in data['students']}
    for student in imported:result[student['user_id']]=student
    data['students']=list(result.values())
    return {'students':imported,'errors':errors,'created':created,'updated':updated},DirectoryConfig.model_validate(data)
