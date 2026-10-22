// Progress measures transfer to this page, not completion of the OS save dialog.
export async function readPdf(response, onProgress = () => {}) {
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    throw new Error(
      typeof data?.detail === "string" ? data.detail : "PDF 加载失败，请重试",
    );
  }
  if (!response.headers.get("content-type")?.includes("application/pdf")) {
    throw new Error("服务器未返回 PDF，请刷新页面并重新登录后重试");
  }
  const length = Number(response.headers.get("content-length"));
  const total =
    length > 0 && !response.headers.get("content-encoding") ? length : null;
  let loaded = 0;
  onProgress({ loaded, total });
  if (!response.body?.getReader) {
    const blob = await response.blob();
    onProgress({ loaded: blob.size, total: blob.size });
    return blob;
  }
  const reader = response.body.getReader();
  const chunks = [];
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      chunks.push(value);
      loaded += value.byteLength;
      onProgress({ loaded, total: total && loaded <= total ? total : null });
    }
  } finally {
    reader.releaseLock();
  }
  if (!loaded) throw new Error("PDF 文件为空，请重试");
  onProgress({ loaded, total: loaded });
  return new Blob(chunks, { type: "application/pdf" });
}
