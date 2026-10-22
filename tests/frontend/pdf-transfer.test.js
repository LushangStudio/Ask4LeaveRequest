import { test } from "node:test";
import assert from "node:assert/strict";
import { readPdf } from "../../src/pdf-transfer.js";
function response(headers = {}) {
  return new Response(
    new ReadableStream({
      start(c) {
        c.enqueue(new TextEncoder().encode("%PDF-"));
        c.enqueue(new TextEncoder().encode("test"));
        c.close();
      },
    }),
    { headers: { "content-type": "application/pdf", ...headers } },
  );
}
test("streams complete bytes and reports actual progress", async () => {
  const events = [];
  const blob = await readPdf(response({ "content-length": "9" }), (p) =>
    events.push(p),
  );
  assert.equal(await blob.text(), "%PDF-test");
  assert.equal(blob.type, "application/pdf");
  assert.deepEqual(
    events.map((p) => p.loaded),
    [0, 5, 9, 9],
  );
  assert.ok(events.every((p) => p.total === 9));
});
test("unknown or compressed length remains indeterminate until complete", async () => {
  for (const headers of [
    {},
    { "content-length": "4", "content-encoding": "gzip" },
  ]) {
    const events = [];
    await readPdf(response(headers), (p) => events.push(p));
    assert.equal(events[1].total, null);
    assert.deepEqual(events.at(-1), { loaded: 9, total: 9 });
  }
});
test("rejects auth errors, HTML login pages and empty PDFs", async () => {
  await assert.rejects(
    readPdf(new Response('{"detail":"请重新登录"}', { status: 401 })),
    /请重新登录/,
  );
  await assert.rejects(
    readPdf(new Response("<html>login</html>")),
    /未返回 PDF/,
  );
  await assert.rejects(
    readPdf(
      new Response("", { headers: { "content-type": "application/pdf" } }),
    ),
    /文件为空/,
  );
});
test("interrupted transfers fail without returning a partial PDF", async () => {
  const body = new ReadableStream({
    pull(c) {
      c.error(new DOMException("Canceled", "AbortError"));
    },
  });
  await assert.rejects(
    readPdf(
      new Response(body, { headers: { "content-type": "application/pdf" } }),
    ),
    { name: "AbortError" },
  );
  assert.equal(body.locked, false);
});
