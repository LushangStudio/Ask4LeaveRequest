<script setup>
import { computed, onMounted, onBeforeUnmount, ref, watch } from "vue";
import { api, apiUrl } from "../api.js";

const emit = defineEmits(["saved"]);
const info = ref(null);
const source = ref("");
const loaded = ref(null);
const stage = ref(null);
const crop = ref({ x: 0, y: 0, w: 0, h: 0 });
const cropImage = ref("");
const saving = ref(false);
const error = ref("");
let drag = null;
let sourceGeneration = 0;
const cropStyle = computed(() => {
  if (!loaded.value) return {};
  const { width, height } = loaded.value;
  const { x, y, w, h } = crop.value;
  return {
    left: `${(x / width) * 100}%`,
    top: `${(y / height) * 100}%`,
    width: `${(w / width) * 100}%`,
    height: `${(h / height) * 100}%`,
  };
});

async function refresh() {
  info.value = await api("signature");
  emit("saved", info.value);
}
onMounted(() =>
  refresh().catch((e) => {
    error.value = e.message;
  }),
);
onBeforeUnmount(() => {
  sourceGeneration++;
  if (source.value) URL.revokeObjectURL(source.value);
});

async function choose(event) {
  const file = event.target.files[0];
  event.target.value = "";
  if (!file) return;
  error.value = "";
  if (
    !["image/png", "image/jpeg", "image/webp"].includes(file.type) ||
    file.size > 3 * 1024 * 1024
  ) {
    error.value = "请选择不超过 3 MiB 的 PNG、JPEG 或 WebP 图片。";
    return;
  }
  const generation = ++sourceGeneration;
  const url = URL.createObjectURL(file);
  const image = new Image();
  try {
    await new Promise((resolve, reject) => {
      image.onload = resolve;
      image.onerror = reject;
      image.src = url;
    });
    if (generation !== sourceGeneration) {
      URL.revokeObjectURL(url);
      return;
    }
    if (
      image.width * image.height > 12000000 ||
      image.width < 16 ||
      image.height < 16
    )
      throw new Error();
    if (source.value) URL.revokeObjectURL(source.value);
    source.value = url;
    loaded.value = image;
    crop.value = { x: 0, y: 0, w: image.width, h: image.height };
  } catch {
    URL.revokeObjectURL(url);
    error.value =
      "无法读取图片，请使用至少 16×16、至多 1200 万像素的静态截图。";
  }
}

function point(event) {
  const rect = stage.value.getBoundingClientRect();
  return {
    x: Math.round(
      Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)) *
        loaded.value.width,
    ),
    y: Math.round(
      Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height)) *
        loaded.value.height,
    ),
  };
}
function start(event) {
  if (!loaded.value || saving.value) return;
  const p = point(event);
  const mode =
    event.target.dataset.handle ||
    (event.target.classList.contains("crop-box") ? "move" : "select");
  drag = { p, mode, original: { ...crop.value } };
  stage.value.setPointerCapture(event.pointerId);
  if (mode === "select") crop.value = { x: p.x, y: p.y, w: 0, h: 0 };
}
function move(event) {
  if (!drag) return;
  const p = point(event);
  const { original: c, mode } = drag;
  const width = loaded.value.width,
    height = loaded.value.height;
  if (mode === "move") {
    crop.value = {
      ...c,
      x: Math.max(0, Math.min(width - c.w, c.x + p.x - drag.p.x)),
      y: Math.max(0, Math.min(height - c.h, c.y + p.y - drag.p.y)),
    };
  } else if (mode === "select") {
    crop.value = {
      x: Math.min(p.x, drag.p.x),
      y: Math.min(p.y, drag.p.y),
      w: Math.abs(p.x - drag.p.x),
      h: Math.abs(p.y - drag.p.y),
    };
  } else {
    const left = mode.includes("w") ? Math.min(p.x, c.x + c.w - 16) : c.x;
    const top = mode.includes("n") ? Math.min(p.y, c.y + c.h - 16) : c.y;
    const right = mode.includes("e") ? Math.max(p.x, c.x + 16) : c.x + c.w;
    const bottom = mode.includes("s") ? Math.max(p.y, c.y + 16) : c.y + c.h;
    crop.value = { x: left, y: top, w: right - left, h: bottom - top };
  }
}
function end() {
  drag = null;
  clamp();
}
function clamp() {
  if (!loaded.value) return;
  const width = loaded.value.width,
    height = loaded.value.height;
  const c = crop.value;
  const x = Math.max(0, Math.min(width - 16, Math.round(Number(c.x) || 0)));
  const y = Math.max(0, Math.min(height - 16, Math.round(Number(c.y) || 0)));
  crop.value = {
    x,
    y,
    w: Math.max(16, Math.min(width - x, Math.round(Number(c.w) || 16))),
    h: Math.max(16, Math.min(height - y, Math.round(Number(c.h) || 16))),
  };
}
function reset() {
  crop.value = { x: 0, y: 0, w: loaded.value.width, h: loaded.value.height };
}
watch(
  crop,
  () => {
    if (!loaded.value || crop.value.w < 16 || crop.value.h < 16) {
      cropImage.value = "";
      return;
    }
    const c = crop.value;
    const scale = Math.min(1, 1200 / c.w, 600 / c.h);
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(16, Math.round(c.w * scale));
    canvas.height = Math.max(16, Math.round(c.h * scale));
    const context = canvas.getContext("2d");
    context.fillStyle = "white";
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.drawImage(
      loaded.value,
      c.x,
      c.y,
      c.w,
      c.h,
      0,
      0,
      canvas.width,
      canvas.height,
    );
    cropImage.value = canvas.toDataURL("image/png");
  },
  { deep: true },
);
async function save() {
  if (saving.value || !cropImage.value) return;
  saving.value = true;
  error.value = "";
  try {
    await api("signature", { image: cropImage.value.split(",")[1] });
    await refresh();
    URL.revokeObjectURL(source.value);
    source.value = "";
    loaded.value = null;
    cropImage.value = "";
  } catch (e) {
    error.value = e.message;
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <section class="panel signature-panel">
    <div class="section-title">
      <div>
        <small>COUNSELOR SIGNATURE</small>
        <h2>我的审批签名</h2>
      </div>
      <span class="status" :class="{ approved: info?.configured }">{{
        info?.configured ? "已设置" : "待设置"
      }}</span>
    </div>
    <p class="muted">
      上传手写签名截图，拖动选区自由裁切。每次审批会自动加入请假人、起始日期和请假天数的纯黑点阵水印。
    </p>
    <img
      v-if="info?.configured && !source"
      class="saved-signature"
      :src="apiUrl(`signature/image?v=${info.version}`)"
      alt="当前保存的个人签名"
    />
    <label class="upload-label"
      >{{ info?.configured ? "更换签名截图" : "选择签名截图"
      }}<input
        type="file"
        accept="image/png,image/jpeg,image/webp"
        :disabled="saving"
        @change="choose"
    /></label>
    <p class="muted caption">
      PNG / JPEG / WebP · 最大 3 MiB · 仅保存裁切后的图片
    </p>
    <template v-if="source">
      <p class="caption">
        拖动空白处重新选区；拖动框内移动；拖动四角调整。也可输入像素坐标。
      </p>
      <div
        ref="stage"
        class="crop-stage"
        @pointerdown.prevent="start"
        @pointermove="move"
        @pointerup="end"
        @pointercancel="end"
      >
        <img :src="source" alt="待裁切的签名截图" draggable="false" />
        <div class="crop-box" :style="cropStyle">
          <span
            v-for="corner in ['nw', 'ne', 'sw', 'se']"
            :key="corner"
            class="crop-handle"
            :class="corner"
            :data-handle="corner"
          ></span>
        </div>
      </div>
      <div class="crop-values">
        <label
          v-for="(label, key) in {
            x: '左边距',
            y: '上边距',
            w: '宽度',
            h: '高度',
          }"
          :key="key"
          >{{ label
          }}<input
            v-model.number="crop[key]"
            type="number"
            min="0"
            :disabled="saving"
            @change="clamp"
        /></label>
      </div>
      <p class="caption">裁切结果</p>
      <img
        v-if="cropImage"
        class="cropped-signature"
        :src="cropImage"
        alt="裁切后的签名"
      />
      <div class="actions">
        <button :disabled="saving || !cropImage" @click="save">
          {{ saving ? "保存中…" : "保存裁切签名" }}</button
        ><button class="light" :disabled="saving" @click="reset">
          重置选区
        </button>
      </div>
    </template>
    <p v-if="info?.updated" class="muted caption">
      最近保存：{{
        new Date(info.updated).toLocaleString("zh-CN", {
          timeZone: "Asia/Shanghai",
        })
      }}
      · 更换签名不影响历史审批
    </p>
    <p v-if="error" role="alert" class="inline-error">{{ error }}</p>
  </section>
</template>
