<script setup>
import { computed, reactive, ref } from "vue";

const props = defineProps({
  busy: Boolean,
  profile: String,
  message: String,
  maxEndDate: String,
});
const attachments = ref([]);
const confirmation = ref(null);
const preparing = ref(false);
const preparationMessage = ref("");
function chooseFiles(event) {
  const additions = Array.from(event.target.files || []);
  event.target.value = "";
  if (attachments.value.length + additions.length > 3)
    return emit("message", "每份申请最多上传 3 个附件");
  if (additions.some((file) => !file.size || file.size > 5 * 1024 * 1024))
    return emit("message", "附件不能为空，每个附件最多 5 MB");
  if (additions.some((file) => file.name.length > 180))
    return emit("message", "附件文件名过长，请缩短后重试");
  attachments.value.push(...additions);
  emit("message", "");
}
function encodeFile(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () =>
      resolve({ name: file.name, data: reader.result.split(",")[1] });
    reader.onerror = () => reject(new Error("无法读取附件，请重新选择文件"));
    reader.onabort = () => reject(new Error("附件读取已取消"));
    reader.readAsDataURL(file);
  });
}
const emit = defineEmits(["submit", "message"]);
const newItem = () => ({
  id: crypto.randomUUID(),
  title: "",
  day: "",
  time: "",
});
const form = reactive({
  reason: "",
  layout: "combined",
  items: [newItem()],
});
const reasonPreview = computed(() => {
  const reason = form.reason.trim().replace(/[。.!！?？;；]+$/u, "");
  return `将呈现为：该生因${reason || "【请假原因】"}……`;
});
// Keep the same key after network failures so retrying does not duplicate a request.
const idempotencyKey = crypto.randomUUID();
function addItem() {
  if (form.items.length >= 30) return emit("message", "每次最多填写 30 个事项");
  form.items.push(newItem());
}
function removeItem(index) {
  if (form.items.length === 1) return emit("message", "至少保留一个请假事项");
  form.items.splice(index, 1);
}
function review() {
  if (
    !form.reason.trim() ||
    form.items.some((item) => !item.title.trim() || !item.time.trim())
  ) {
    return emit(
      "message",
      "请填写请假原因、事项名称和时间或节次，不能只输入空格",
    );
  }
  emit("message", "");
  confirmation.value.showModal();
}
async function submit() {
  if (props.busy || preparing.value) return;
  preparing.value = true;
  try {
    const files = [];
    for (const [index, file] of attachments.value.entries()) {
      preparationMessage.value = `正在读取附件 ${index + 1}/${attachments.value.length}…`;
      files.push(await encodeFile(file));
    }
    confirmation.value.close();
    emit("submit", {
      attachments: files,
      mode: "items",
      reason: form.reason.trim(),
      layout: form.layout,
      idempotency_key: idempotencyKey,
      items: form.items.map(({ title, day, time }) => ({
        title: title.trim(),
        day,
        time: time.trim(),
      })),
    });
  } catch (error) {
    emit("message", error.message);
  } finally {
    preparing.value = false;
    preparationMessage.value = "";
  }
}
</script>

<template>
  <section id="apply" class="panel">
    <div class="section-title">
      <h2>新建请假申请</h2>
    </div>
    <p id="profile" class="muted">{{ profile }}</p>
    <form id="form" @submit.prevent="review">
      <fieldset class="form-fields" :disabled="busy || preparing">
        <div class="application-columns">
          <section class="reason-section">
            <h3>请假原因</h3>
            <label class="sr-only" for="reason">请假原因</label
            ><textarea
              id="reason"
              v-model="form.reason"
              name="reason"
              placeholder="请简要说明请假原因"
              maxlength="50"
              rows="2"
              required
            ></textarea>
            <p class="caption reason-count" aria-live="polite">
              {{ form.reason.length }}/50
            </p>
            <p class="caption reason-preview" aria-live="polite">
              {{ reasonPreview }}
            </p>
          </section>
          <section class="items-section">
            <div class="section-title">
              <h3>请假事项</h3>
              <button id="add" type="button" class="light" @click="addItem">
                ＋ 添加事项
              </button>
            </div>
            <div id="items">
              <div
                v-for="(item, index) in form.items"
                :key="item.id"
                class="item"
              >
                <div class="item-head">
                  <b>请假事项 {{ index + 1 }}</b
                  ><button
                    type="button"
                    aria-label="删除此事项"
                    @click="removeItem(index)"
                  >
                    删除
                  </button>
                </div>
                <div class="item-fields">
                  <label
                    >日期<input
                      v-model="item.day"
                      name="day"
                      type="date"
                      :max="maxEndDate"
                      required
                  /></label>
                  <label
                    >时间或节次<input
                      v-model="item.time"
                      name="time"
                      placeholder="例如：14:00–16:00"
                      maxlength="120"
                      required
                  /></label>
                  <label
                    >事项名称<input
                      v-model="item.title"
                      name="title"
                      placeholder="例如：组织行为学课程，才萃团校活动"
                      maxlength="200"
                      required
                  /></label>
                </div>
              </div>
            </div>
          </section>
        </div>
        <fieldset class="layout-options">
          <legend>请假条生成方式</legend>
          <label class="radio"
            ><input
              v-model="form.layout"
              type="radio"
              name="layout"
              value="combined"
            />合并生成 · 所有事项放在同一份请假条</label
          >
          <label class="radio"
            ><input
              v-model="form.layout"
              type="radio"
              name="layout"
              value="separate"
            />分别生成 · 每个事项一份请假条</label
          >
        </fieldset>
        <fieldset class="attachment-fields">
          <legend>附件（选填，{{ attachments.length }}/3）</legend>
          <p class="caption">
            最多 3 个，每个 5 MB。最晚事项日期一个自然月后自动删除，仅用于审批。
          </p>
          <input
            type="file"
            multiple
            aria-label="选择附件"
            :disabled="attachments.length >= 3"
            @change="chooseFiles"
          />
          <ul>
            <li v-for="(file, index) in attachments" :key="index">
              {{ file.name }} · {{ Math.ceil(file.size / 1024) }} KB
              <button
                type="button"
                class="light"
                :aria-label="`移除附件 ${file.name}`"
                @click="attachments.splice(index, 1)"
              >
                移除
              </button>
            </li>
          </ul>
          <p v-if="preparationMessage" role="status">
            {{ preparationMessage }}
          </p>
        </fieldset>
        <p class="muted">由系统分配给负责你的辅导员，审批通过后自动生成。</p>
        <button id="submit" class="primary" :disabled="busy || preparing">
          {{ busy || preparing ? "正在处理…" : "预览并提交" }}
        </button>
        <p
          v-if="message"
          id="submit-message"
          class="inline-error"
          role="status"
          aria-live="polite"
        >
          {{ message }}
        </p>
      </fieldset>
    </form>
    <dialog
      ref="confirmation"
      class="preview-dialog submission-dialog"
      aria-labelledby="submit-preview-title"
    >
      <div class="dialog-header">
        <h2 id="submit-preview-title">提交前预览</h2>
        <button
          type="button"
          class="light"
          :disabled="busy || preparing"
          @click="confirmation.close()"
        >
          关闭
        </button>
      </div>
      <div class="dialog-body">
        <p>{{ profile }}</p>
        <p class="caption">
          以下为申请内容预览，尚未提交，也不是审批通过的请假凭证。
        </p>
        <p>
          该生因{{
            form.reason.trim().replace(/[。.!！?？;；]+$/u, "")
          }}，<template v-for="(item, index) in form.items" :key="item.id"
            >{{ index ? "；" : "" }}于{{ item.day }}{{ item.time }}请假{{
              item.title
            }}</template
          >。
        </p>
        <ol>
          <li v-for="item in form.items" :key="item.id">
            {{ item.day }} · {{ item.time }} · {{ item.title }}
          </li>
        </ol>
        <p>
          生成方式：{{
            form.layout === "combined" ? "合并生成" : "每个事项分别生成"
          }}
        </p>
        <p>
          附件：{{ attachments.map((file) => file.name).join("、") || "无" }}
        </p>
      </div>
      <div class="dialog-footer">
        <button type="button" :disabled="busy || preparing" @click="submit">
          {{ preparing ? preparationMessage || "正在准备…" : "确认提交申请" }}
        </button>
      </div>
    </dialog>
  </section>
</template>
