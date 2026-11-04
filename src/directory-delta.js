function classRecord(row) {
  return {
    class_id: row.class_id,
    name: row.name,
    grade: row.grade,
    department: row.department,
    counselor_ids: row.counselor_ids_text
      .split(",")
      .map((id) => id.trim())
      .filter(Boolean),
  };
}
function studentRecord({ user_id, major, class_id }) {
  return { user_id, major, class_id };
}
function changes(previous, current, key, normalize) {
  const before = new Map(previous.map((row) => [row[key], normalize(row)]));
  const after = current.map(normalize);
  const ids = new Set(after.map((row) => row[key]));
  if (ids.size !== after.length)
    throw new Error("班级或学号重复，请修正后保存");
  return {
    upsert: after.filter(
      (row) => JSON.stringify(row) !== JSON.stringify(before.get(row[key])),
    ),
    deleted: [...before.keys()].filter((id) => !ids.has(id)),
  };
}
export function directoryDelta(previous, current, revision) {
  const classes = changes(
    previous.classes,
    current.classes,
    "class_id",
    classRecord,
  );
  const students = changes(
    previous.students,
    current.students,
    "user_id",
    studentRecord,
  );
  return {
    revision,
    classes: classes.upsert,
    deleted_classes: classes.deleted,
    students: students.upsert,
    deleted_students: students.deleted,
  };
}
