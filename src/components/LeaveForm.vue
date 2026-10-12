<script setup>
import { reactive } from "vue";

defineProps({ busy: Boolean, profile: String });
const emit = defineEmits(["submit", "message"]);
const newItem = () => ({
  id: crypto.randomUUID(),
  kind: "course",
  title: "",
  day: "",
  time: "",
});
const form = reactive({
  starts: "",
  ends: "",
  reason: "",
  layout: "combined",
  items: [newItem()],
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
function submit() {
  emit("submit", {
    starts: form.starts,
    ends: form.ends,
    reason: form.reason,
    layout: form.layout,
    idempotency_key: idempotencyKey,
    items: form.items.map(({ kind, title, day, time }) => ({
      kind,
      title,
      day,
      time,
    })),
  });
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
      <fieldset class="form-fields" :disabled="busy">
        <div class="two">
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
              required
          /></label>
        </div>
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
        <div class="section-title">
          <h3>请假事项</h3>
          <button id="add" type="button" class="light" @click="addItem">
            ＋ 添加事项
          </button>
        </div>
        <div id="items">
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
                >日期<input v-model="item.day" name="day" type="date" required
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
        <fieldset>
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
        <button id="submit" class="primary" :disabled="busy">
          {{ busy ? "正在处理…" : "提交申请" }}
        </button>
      </fieldset>
    </form>
  </section>
</template>
