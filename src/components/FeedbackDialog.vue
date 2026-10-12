<script setup>
import { nextTick, ref, watch } from "vue";
const props = defineProps({ message: String });
const emit = defineEmits(["close"]);
const dialog = ref(null);
watch(
  () => props.message,
  async (message) => {
    await nextTick();
    if (message && !dialog.value.open) dialog.value.showModal();
    else if (!message && dialog.value.open) dialog.value.close();
  },
);
</script>

<template>
  <dialog
    ref="dialog"
    class="preview-dialog feedback-dialog"
    aria-labelledby="feedback-title"
    @close="emit('close')"
  >
    <h2 id="feedback-title">提示</h2>
    <p class="inline-error" role="status">{{ message }}</p>
    <div class="actions">
      <button autofocus @click="dialog.close()">知道了</button>
    </div>
  </dialog>
</template>
