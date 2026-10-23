export const statuses = {
  pending: "待审批",
  approved: "已通过",
  rejected: "已驳回",
  withdrawn: "学生已撤回",
  revoked: "辅导员已撤回",
};
export function firstTitle(row) {
  return row.items?.length
    ? row.items[0].title + (row.items.length > 1 ? "等" : "")
    : "起止日期请假（历史记录）";
}
export function itemDate(value) {
  const [year, month, day] = value.split("-");
  return `${year}年${Number(month)}月${Number(day)}日`;
}
export function firstTime(row) {
  const item = row.items?.[0];
  return item
    ? `${itemDate(item.day)}${item.time}${row.items.length > 1 ? "等" : ""}`
    : `${row.starts} 至 ${row.ends}`;
}
export function latestOpinion(row) {
  return row.withdrawal &&
    (!row.approval || !row.withdrawal.at || row.withdrawal.at > row.approval.at)
    ? row.withdrawal.reason || "未填写撤回原因"
    : row.approval
      ? row.approval.opinion ||
        (row.approval.outcome === "approved" ? "同意" : "未填写")
      : "—";
}
export function timestamp(value) {
  return value
    ? new Date(value).toLocaleString("zh-CN", {
        timeZone: "Asia/Shanghai",
        hour12: false,
      })
    : "—";
}

export function firstDate(row) {
  const item = row.items?.[0];
  return item
    ? `${itemDate(item.day)}${row.items.length > 1 ? "等" : ""}`
    : itemDate(row.starts) + (row.starts !== row.ends ? "等" : "");
}
