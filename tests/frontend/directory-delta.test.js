import test from "node:test";
import assert from "node:assert/strict";
import { directoryDelta } from "../../src/directory-delta.js";
const before = {
  classes: [
    {
      class_id: "class-1",
      name: "一班",
      grade: "2026",
      department: "管理学院",
      counselor_ids_text: "staff-1",
    },
  ],
  students: Array.from({ length: 600 }, (_, i) => ({
    user_id: `student-${i}`,
    major: "管理",
    class_id: "class-1",
  })),
};
test("one edit in 600 students sends only the changed student", () => {
  const after = structuredClone(before);
  after.students[105].major = "会计";
  const delta = directoryDelta(before, after, "revision");
  assert.deepEqual(delta.students, [after.students[105]]);
  assert.deepEqual(delta.classes, []);
  assert.deepEqual(delta.deleted_students, []);
  assert.ok(JSON.stringify(delta).length < 300);
});
test("tracks identity changes as delete/add and counselor-only edits", () => {
  const after = structuredClone(before);
  after.students[0].user_id = "new-id";
  after.classes[0].counselor_ids_text = "staff-1, staff-2";
  const delta = directoryDelta(before, after, "revision");
  assert.deepEqual(delta.deleted_students, ["student-0"]);
  assert.equal(delta.students.length, 1);
  assert.deepEqual(delta.classes[0].counselor_ids, ["staff-1", "staff-2"]);
});
test("does not silently discard duplicate identities", () => {
  const after = structuredClone(before);
  after.students.push({ ...after.students[0] });
  assert.throws(() => directoryDelta(before, after, "revision"), /重复/);
});
