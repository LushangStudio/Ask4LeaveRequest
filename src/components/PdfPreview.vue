<script setup>
import { nextTick, onBeforeUnmount, ref, watch } from "vue";
import { getDocument, PDFWorker } from "pdfjs-dist/build/pdf.mjs";
import { pdfErrorDetail } from "../pdf-errors.js";
import PdfWorker from "pdfjs-dist/build/pdf.worker.mjs?worker&inline";

const props = defineProps({
  url: { type: String, required: true },
  blob: { type: Blob, required: true },
});
const emit = defineEmits(["loaded", "error"]);
const holder = ref(null);
const pages = ref([]);
const loading = ref(true);
const error = ref("");
const zoom = ref(1);
const canvases = new Map();
const pageSizes = new Map();

function applyZoom() {
  for (const [number, size] of pageSizes) {
    const canvas = canvases.get(number);
    if (!canvas) continue;
    canvas.style.width = `${Math.floor(size.width * zoom.value)}px`;
    canvas.style.height = `${Math.floor(size.height * zoom.value)}px`;
  }
}
let active = null;
let generation = 0;

function dispose(session) {
  if (!session || session.disposed) return;
  session.disposed = true;
  session.renderTask?.cancel();
  const cleanup = session.task ? session.task.destroy() : Promise.resolve();
  cleanup
    .catch(() => {})
    .finally(() => {
      session.worker?.destroy();
      session.port?.terminate();
    });
}

async function render() {
  const version = ++generation;
  const url = props.url;
  const blob = props.blob;
  dispose(active);
  const session = {};
  active = session;
  loading.value = true;
  error.value = "";
  pages.value = [];
  pageSizes.clear();
  zoom.value = 1;
  try {
    await nextTick();
    const data = new Uint8Array(await blob.arrayBuffer());
    if (version !== generation) return;
    // Own each worker: PDF.js caches workers by port, so a shared port can
    // return a worker that a previous component is still destroying.
    session.port = new PdfWorker();
    session.worker = new PDFWorker({ port: session.port });
    session.task = getDocument({
      data,
      worker: session.worker,
      isEvalSupported: false,
    });
    const pdf = await session.task.promise;
    if (version !== generation) return;
    pages.value = Array.from({ length: pdf.numPages }, (_, index) => index + 1);
    await nextTick();
    if (version !== generation || !holder.value) return;
    const width = Math.max(220, Math.min(1100, holder.value.clientWidth - 24));
    for (const number of pages.value) {
      const page = await pdf.getPage(number);
      if (version !== generation) return;
      const initial = page.getViewport({ scale: 1 });
      const viewport = page.getViewport({ scale: width / initial.width });
      // Bound canvas memory on mobile; zoom only changes its display size.
      const ratio = Math.min(
        window.devicePixelRatio || 1,
        2,
        Math.sqrt(3_000_000 / (viewport.width * viewport.height)),
      );
      const canvas = canvases.get(number);
      if (!canvas) throw new Error("PDF canvas unavailable");
      canvas.width = Math.floor(viewport.width * ratio);
      canvas.height = Math.floor(viewport.height * ratio);
      pageSizes.set(number, { width: viewport.width, height: viewport.height });
      applyZoom();
      const context = canvas.getContext("2d");
      if (!context) throw new Error("PDF canvas context unavailable");
      session.renderTask = page.render({
        canvasContext: context,
        viewport,
        transform: [ratio, 0, 0, ratio, 0, 0],
      });
      await session.renderTask.promise;
      session.renderTask = null;
      page.cleanup();
    }
    if (version === generation) {
      loading.value = false;
      emit("loaded", url);
    }
  } catch (e) {
    if (version !== generation) return;
    loading.value = false;
    error.value = `PDF 预览失败：${pdfErrorDetail(e)}。可重试或下载查看；不影响审批。`;
    console.warn("PDF preview failed", pdfErrorDetail(e));
    emit("error", url);
    dispose(session);
  }
}
watch([() => props.url, () => props.blob], render, { immediate: true });
watch(zoom, applyZoom);
onBeforeUnmount(() => {
  generation++;
  dispose(active);
});
</script>

<template>
  <div class="pdf-toolbar">
    <span>{{ pages.length ? `${pages.length} 页` : "请假条 PDF" }}</span>
    <div class="actions">
      <button
        class="light"
        :disabled="loading || zoom <= 0.5"
        aria-label="缩小 PDF"
        @click="zoom -= 0.25"
      >
        −</button
      ><button class="light" :disabled="loading" @click="zoom = 1">
        适应宽度</button
      ><button
        class="light"
        :disabled="loading || zoom >= 2"
        aria-label="放大 PDF"
        @click="zoom += 0.25"
      >
        ＋
      </button>
    </div>
  </div>
  <div
    ref="holder"
    class="pdf-pages"
    role="region"
    aria-label="请假条 PDF 页面"
    :aria-busy="loading"
  >
    <p v-if="loading" class="muted" role="status">正在渲染 PDF 页面…</p>
    <p v-if="error" class="inline-error" role="alert">
      {{ error }}
      <button type="button" class="light" @click="render">重试预览</button>
    </p>
    <figure v-for="number in pages" :key="`${url}-${number}`">
      <canvas
        :ref="
          (element) =>
            element ? canvases.set(number, element) : canvases.delete(number)
        "
        :aria-label="`请假条 PDF 第 ${number} 页`"
      ></canvas>
      <figcaption>第 {{ number }} / {{ pages.length }} 页</figcaption>
    </figure>
  </div>
</template>
