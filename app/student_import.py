"""Validate one student per CSV line without changing persisted data."""
import csv
import io
from app.directory import DirectoryConfig,StudentConfig
from pydantic import ValidationError

HEADER=['学号','专业']

def preview_import(text,directory,class_id):
    data=directory.model_dump()
    if class_id not in {c.class_id for c in directory.classes}:
        return {'students':[],'errors':[{'line':0,'message':'请选择有效的导入班级'}],'created':0,'updated':0},directory
    existing={s.user_id:s for s in directory.students}
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
            if len(fields)!=2:
                errors.append({'line':line,'message':'须填写两列：学号,专业'});continue
            uid,major=fields
            if uid in seen:
                errors.append({'line':line,'message':'本次导入学号重复'});continue
            seen.add(uid)
            try:student=StudentConfig(user_id=uid,class_id=class_id,major=major)
            except ValidationError:
                errors.append({'line':line,'message':'必填内容为空或格式/长度不合法'});continue
            if uid in existing:updated+=1
            else:created+=1
            imported.append(student.model_dump())
    except csv.Error:errors.append({'line':reader.line_num,'message':'CSV引号或分隔格式不合法'})
    if not imported and not errors:errors.append({'line':1,'message':'请至少填写一名学生'})
    result={s['user_id']:s for s in data['students']}
    for student in imported:result[student['user_id']]=student
    data['students']=list(result.values())
    return {'students':imported,'errors':errors,'created':created,'updated':updated},DirectoryConfig.model_validate(data)
