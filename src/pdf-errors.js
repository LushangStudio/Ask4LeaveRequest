// Keep diagnostics useful without exposing temporary capability URLs or stacks.
export function pdfErrorDetail(error) {
  const name = typeof error?.name === "string" ? error.name : "Error";
  const message =
    typeof error?.message === "string"
      ? error.message
      : typeof error === "string"
        ? error
        : "浏览器未提供详细错误信息";
  return `${name}：${message}`
    .replace(/(?:https?:\/\/|blob:)[^\s"'<>]+/g, "[文件地址]")
    .slice(0, 500);
}
