<script setup>
import { computed, ref, watch } from "vue";
const props = defineProps({ blob: Blob, filename: String, sourceUrl: String });
const saving = ref(false);
const message = ref("");
const file = computed(
  () =>
    props.blob &&
    new File([props.blob], props.filename, { type: "application/pdf" }),
);
const canShare = computed(() => {
  try {
    return (
      !!file.value &&
      !!navigator.share &&
      !!navigator.canShare?.({ files: [file.value] })
    );
  } catch {
    return false;
  }
});
watch(
  () => props.blob,
  () => {
    message.value = "";
  },
);
async function share() {
  saving.value = true;
  message.value = "";
  try {
    // No fetch/await before share: mobile browsers require a fresh user gesture.
    await navigator.share({ files: [file.value] });
  } catch (error) {
    if (error.name !== "AbortError")
      message.value =
        "无法打开系统保存菜单，请尝试普通下载，或在 Safari / Chrome 中打开本页面。";
  } finally {
    saving.value = false;
  }
}
function download() {
  const url = URL.createObjectURL(props.blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = props.filename;
  document.body.append(link);
  link.click();
  link.remove();
  // Independent of the preview URL: closing the dialog must not revoke a pending download.
  setTimeout(() => URL.revokeObjectURL(url), 60000);
  message.value =
    "已交给浏览器处理。若没有出现下载，请尝试保存/分享，或在 Safari / Chrome 中打开本页面。";
}
</script>
<template>
  <div>
    <button v-if="canShare" type="button" :disabled="saving" @click="share">
      保存 / 分享 PDF
    </button>
    <button
      type="button"
      class="light"
      :disabled="saving || !blob"
      @click="download"
    >
      {{ canShare ? "普通下载" : "下载 PDF" }}
    </button>
    <a class="file" :href="sourceUrl" target="_blank" rel="noopener"
      >在新标签页打开 PDF</a
    >
    <p class="caption">
      下载无响应时，可在新标签页打开后使用浏览器的保存功能。
    </p>
    <p v-if="canShare" class="caption">
      可在系统菜单中选择存储到文件或发送到其他应用。
    </p>
    <p v-if="message" class="caption" role="status">{{ message }}</p>
  </div>
</template>
