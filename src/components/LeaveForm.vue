<script setup>
import { computed, reactive, ref } from "vue";

const props = defineProps({
  busy: Boolean,
  profile: String,
  message: String,
  maxEndDate: String,
});
const attachments = ref([]);
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
  kind: "course",
  title: "",
  day: "",
  time: "",
});
const form = reactive({
  mode: "date_range",
  starts: "",
  ends: "",
  reason: "",
  layout: "combined",
  items: [newItem()],
});
const reasonPreview = computed(() => {
  const reason = form.reason.trim().replace(/[。.!！?？;；]+$/u, "");
  return `将呈现为：该生因${reason || "【请假事由】"}……`;
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
async function submit() {
  if (props.busy || preparing.value) return;
  if (
    form.mode === "date_range" &&
    props.maxEndDate &&
    form.ends > props.maxEndDate
  )
    return emit(
      "message",
      `请假结束日期不得超过当前日期后三个月（最晚 ${props.maxEndDate}）`,
    );
  preparing.value = true;
  try {
    const files = [];
    for (const [index, file] of attachments.value.entries()) {
      preparationMessage.value = `正在读取附件 ${index + 1}/${attachments.value.length}…`;
      files.push(await encodeFile(file));
    }
    emit("submit", {
      attachments: files,
      mode: form.mode,
      ...(form.mode === "date_range"
        ? { starts: form.starts, ends: form.ends }
        : {}),
      reason: form.reason,
      layout: form.mode === "date_range" ? "combined" : form.layout,
      idempotency_key: idempotencyKey,
      items:
        form.mode === "items"
          ? form.items.map(({ kind, title, day, time }) => ({
              kind,
              title,
              day,
              time,
            }))
          : [],
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
      <span>01 — 填写信息</span>
    </div>
    <p id="profile" class="muted">{{ profile }}</p>
    <form id="form" @submit.prevent="submit">
      <fieldset class="form-fields" :disabled="busy || preparing">
        <fieldset>
          <legend>请假方式</legend>
          <label class="radio"
            ><input
              v-model="form.mode"
              type="radio"
              value="date_range"
            />按起止日期请假</label
          >
          <label class="radio"
            ><input
              v-model="form.mode"
              type="radio"
              value="items"
            />按具体事项请假（请假条包含具体课程、活动等）</label
          >
        </fieldset>
        <div v-if="form.mode === 'date_range'" class="two">
          <label
            >开始日期<input
              v-model="form.starts"
              name="starts"
              type="date"
              required
          /></label>
          <label
            >结束日期<input
              v-model="form.ends"
              name="ends"
              type="date"
              :max="maxEndDate"
              required
          /></label>
        </div>
        <p v-if="maxEndDate" class="caption">
          请假日期最晚为 {{ maxEndDate }}，按北京时间加三个自然月计算。
        </p>
        <label
          >请假原因<textarea
            v-model="form.reason"
            name="reason"
            placeholder="请简要说明请假原因"
            maxlength="4000"
            rows="3"
            required
          ></textarea>
        </label>
        <p class="caption" aria-live="polite">{{ reasonPreview }}</p>
        <fieldset>
          <legend>附件（选填，{{ attachments.length }}/3）</legend>
          <p class="caption">
            每个附件最多 5
            MB，作为审批材料单独保存，不合并进请假条。请假结束日期（或最晚事项日期）一个自然月后自动删除附件。
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
        <div v-if="form.mode === 'items'" class="section-title">
          <h3>请假事项</h3>
          <button id="add" type="button" class="light" @click="addItem">
            ＋ 添加事项
          </button>
        </div>
        <div v-if="form.mode === 'items'" id="items">
          <div v-for="(item, index) in form.items" :key="item.id" class="item">
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
            <div class="two">
              <label
                >事项类型<select v-model="item.kind" name="kind">
                  <option value="course">课程</option>
                  <option value="activity">活动</option>
                  <option value="other">其他</option>
                </select></label
              >
              <label
                >事项名称<input
                  v-model="item.title"
                  name="title"
                  placeholder="例如：学术讲座"
                  maxlength="200"
                  required
              /></label>
            </div>
            <div class="two">
              <label
                >日期<input
                  v-model="item.day"
                  name="day"
                  type="date"
                  :max="maxEndDate"
                  required
              /></label>
              <label
                >节次或时间<input
                  v-model="item.time"
                  name="time"
                  placeholder="例如：14:00–16:00"
                  maxlength="120"
                  required
              /></label>
            </div>
          </div>
        </div>
        <fieldset v-if="form.mode === 'items'">
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
        <p class="muted">由系统分配给负责你的辅导员，审批通过后自动生成。</p>
        <button id="submit" class="primary" :disabled="busy || preparing">
          {{ busy || preparing ? "正在处理…" : "提交申请" }}
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
  </section>
</template>
