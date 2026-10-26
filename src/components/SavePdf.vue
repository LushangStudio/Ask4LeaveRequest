<script setup>
import { ref, watch } from "vue";
import { api, apiUrl } from "../api.js";
const props = defineProps({
  blob: Blob,
  filename: String,
  sourceUrl: String,
  resource: Object,
});
const message = ref("");
watch(
  () => props.blob,
  () => {
    message.value = "";
  },
);
const busy = ref(false);
async function download() {
  busy.value = true;
  message.value = "";
  try {
    const result = await api("download-links", props.resource);
    // Navigate to a real HTTP URL so WeChat can hand it to the system browser.
    // The URL itself grants PDF access for 3 minutes, without a login cookie.
    window.location.assign(apiUrl(result.path));
    message.value = "下载链接 3 分钟内有效，可重复下载。";
  } catch (error) {
    message.value = error.message;
  } finally {
    busy.value = false;
  }
}
</script>
<template>
  <div>
    <button
      type="button"
      class="download-primary"
      :disabled="!blob || busy"
      @click="download"
    >
      {{ busy ? "正在生成下载链接…" : "普通下载" }}
    </button>
    <a class="file" :href="sourceUrl" target="_blank" rel="noopener"
      >在新标签页打开 PDF</a
    >
    <p class="caption">
      普通下载链接 3 分钟内免登录、可重复下载；请勿转发给他人。
    </p>
    <p v-if="message" class="caption" role="status">{{ message }}</p>
  </div>
</template>
