import { test } from "node:test";
import assert from "node:assert/strict";
import { firstTitle, firstTime, latestOpinion } from "../../src/request-display.js";
test("summarizes the first item and preserves full data for the detail dialog", () => {
  const row = { items: [{title:"组织行为学课程",day:"2026-10-22",time:"第1-2节"},{title:"才萃团校活动",day:"2026-10-23",time:"14:00"}] };
  assert.equal(firstTitle(row), "组织行为学课程等");
  assert.equal(firstTime(row), "2026年10月22日第1-2节等");
  assert.equal(row.items.length, 2);
  row.items.pop();
  assert.equal(firstTime(row), "2026年10月22日第1-2节");
});
test("shows the latest withdrawal opinion instead of an older approval", () => {
  const row = {approval:{opinion:"同意",outcome:"approved"},withdrawal:{reason:"时间已调整"}};
  assert.equal(latestOpinion(row), "时间已调整");
  row.withdrawal.reason="";
  assert.equal(latestOpinion(row), "未填写撤回原因");
});
test("historical date-range applications remain readable", () => {
  const row={items:[],starts:"2026-10-22",ends:"2026-10-23"};
  assert.equal(firstTitle(row), "起止日期请假（历史记录）");
  assert.equal(firstTime(row), "2026-10-22 至 2026-10-23");
  assert.equal(latestOpinion(row), "—");
});

test("compact dates omit times for both new and historical records", async () => {
  const { firstDate } = await import("../../src/request-display.js");
  assert.equal(firstDate({items:[{day:"2026-10-22",time:"第1-2节"}]}), "2026年10月22日");
  assert.equal(firstDate({items:[{day:"2026-10-22"},{day:"2026-10-23"}]}), "2026年10月22日等");
  assert.equal(firstDate({items:[],starts:"2026-10-22",ends:"2026-10-23"}), "2026年10月22日等");
});

test("a new approval opinion supersedes an earlier counselor withdrawal", () => {
  assert.equal(latestOpinion({approval:{opinion:"重新审核通过",at:"2026-10-23T02:00:00Z"},withdrawal:{reason:"修正",at:"2026-10-23T01:00:00Z"}}), "重新审核通过");
});
