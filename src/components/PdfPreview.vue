<script setup>
import { nextTick, onBeforeUnmount, ref, watch } from "vue";
import { getDocument, GlobalWorkerOptions } from "pdfjs-dist/build/pdf.mjs";
import PdfWorker from "pdfjs-dist/build/pdf.worker.mjs?worker&inline";

// A bundled classic Blob worker avoids WebVPN rewriting a module worker.
// Initialize lazily so opening the app does not allocate a PDF worker.
function ensurePdfWorker() {
  if (!GlobalWorkerOptions.workerPort) {
    GlobalWorkerOptions.workerPort = new PdfWorker();
  }
}
const props = defineProps({ url: { type: String, required: true } });
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
let task = null;
let generation = 0;

async function render() {
  const version = ++generation;
  const url = props.url;
  if (task) {
    await task.destroy();
    task = null;
  }
  if (version !== generation) return;
  loading.value = true;
  error.value = "";
  pages.value = [];
  pageSizes.clear();
  zoom.value = 1;
  await nextTick();
  try {
    ensurePdfWorker();
    const loadingTask = getDocument({ url, isEvalSupported: false });
    task = loadingTask;
    const pdf = await loadingTask.promise;
    if (version !== generation) return;
    pages.value = Array.from({ length: pdf.numPages }, (_, index) => index + 1);
    await nextTick();
    const width = Math.max(220, Math.min(1100, holder.value.clientWidth - 24));
    for (const number of pages.value) {
      const page = await pdf.getPage(number);
      if (version !== generation) return;
      const initial = page.getViewport({ scale: 1 });
      const viewport = page.getViewport({ scale: width / initial.width });
      const ratio = Math.min(
        // Render once for the maximum 200% zoom; cap memory per page.
        (window.devicePixelRatio || 1) * 2,
        4,
        Math.sqrt(8_000_000 / (viewport.width * viewport.height)),
      );
      const canvas = canvases.get(number);
      canvas.width = Math.floor(viewport.width * ratio);
      canvas.height = Math.floor(viewport.height * ratio);
      pageSizes.set(number, { width: viewport.width, height: viewport.height });
      applyZoom();
      await page.render({
        canvasContext: canvas.getContext("2d"),
        viewport,
        transform: [ratio, 0, 0, ratio, 0, 0],
      }).promise;
    }
    if (version === generation) {
      loading.value = false;
      emit("loaded", url);
    }
  } catch (e) {
    if (version !== generation) return;
    loading.value = false;
    error.value = "PDF 页面加载失败，请重新预览或下载 PDF 查看。";
    emit("error", url);
  }
}
watch(() => props.url, render, { immediate: true });
watch(zoom, applyZoom);
onBeforeUnmount(() => {
  generation++;
  if (task) task.destroy();
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
    <p v-if="error" class="inline-error" role="alert">{{ error }}</p>
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
