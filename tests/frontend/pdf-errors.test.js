import test from "node:test";
import assert from "node:assert/strict";
import { pdfErrorDetail } from "../../src/pdf-errors.js";

test("shows the renderer's actual diagnostic", () => {
  assert.equal(
    pdfErrorDetail({
      name: "InvalidPDFException",
      message: "Invalid PDF structure.",
    }),
    "InvalidPDFException：Invalid PDF structure.",
  );
});
test("redacts download credentials and handles missing details", () => {
  assert.equal(
    pdfErrorDetail(
      new Error("Failed https://example.test/api/public-pdfs/secret"),
    ),
    "Error：Failed [文件地址]",
  );
  assert.match(pdfErrorDetail(null), /浏览器未提供详细错误信息/);
  assert.equal(pdfErrorDetail("x".repeat(1000)).length, 500);
});
