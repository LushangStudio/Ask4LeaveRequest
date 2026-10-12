// Relative to the page so both / and the Home proxy's /leave/ work.
const apiBase = new URL("api/", window.location.href);

export function apiUrl(path) {
  return new URL(path, apiBase).href;
}

export async function pdfBlob(path) {
  const response = await fetch(apiUrl(path));
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    throw new Error(data?.detail || "预览加载失败，请重试");
  }
  return URL.createObjectURL(await response.blob());
}

export function documentUrl(id) {
  return new URL(`documents/${encodeURIComponent(id)}`, apiBase).href;
}

export async function api(path, body) {
  const response = await fetch(new URL(path, apiBase), {
    method: body === undefined ? "GET" : "POST",
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = data?.detail;
    const message =
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail.map((item) => item.msg).join("\n")
          : `请求失败（${response.status}），请稍后重试`;
    const error = new Error(message);
    error.status = response.status;
    throw error;
  }
  return data;
}
