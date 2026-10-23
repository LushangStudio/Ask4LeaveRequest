<script setup>
import { ref, watch } from "vue";
const props = defineProps({ blob: Blob, filename: String, sourceUrl: String });
const message = ref("");
watch(
  () => props.blob,
  () => {
    message.value = "";
  },
);
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
    "已交给浏览器处理。若没有出现下载，请使用“在新标签页打开 PDF”后通过浏览器保存。";
}
</script>
<template>
  <div>
    <button
      type="button"
      class="download-primary"
      :disabled="!blob"
      @click="download"
    >
      普通下载
    </button>
    <a class="file" :href="sourceUrl" target="_blank" rel="noopener"
      >在新标签页打开 PDF</a
    >
    <p class="caption">
      下载无响应时，可在新标签页打开后使用浏览器的保存功能。
    </p>
    <p v-if="message" class="caption" role="status">{{ message }}</p>
  </div>
</template>
