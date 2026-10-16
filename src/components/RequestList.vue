<script setup>
import { computed, ref, watch } from "vue";
import RequestCard from "./RequestCard.vue";

const props = defineProps({
  records: { type: Array, required: true },
  role: String,
  busy: Boolean,
  signatureVersion: String,
});
const emit = defineEmits(["decision", "retry", "withdraw"]);
const page = ref(1);
const pageSize = 10;
const overrides = ref(new Map());
const pageCount = computed(() =>
  Math.max(1, Math.ceil(props.records.length / pageSize)),
);
const visibleRecords = computed(() =>
  props.records.slice((page.value - 1) * pageSize, page.value * pageSize),
);
// A status transition restores the default; ordinary polling keeps manual choices.
const stateKey = (record) =>
  `${record.id}:${record.status}:${record.file_status}`;
function isExpanded(record) {
  return (
    overrides.value.get(stateKey(record)) ??
    (props.role === "student"
      ? record.id === props.records[0]?.id
      : record.status === "pending" ||
        (record.status === "approved" && record.file_status === "failed"))
  );
}
function toggle(record) {
  overrides.value.set(stateKey(record), !isExpanded(record));
}
watch(
  () => props.records,
  (rows, previous) => {
    const keys = new Set(rows.map(stateKey));
    for (const key of overrides.value.keys())
      if (!keys.has(key)) overrides.value.delete(key);
    // A newly submitted request should be immediately visible on the first page.
    if (rows[0]?.id !== previous?.[0]?.id) page.value = 1;
    page.value = Math.min(page.value, pageCount.value);
  },
);
</script>

<template>
  <p class="muted caption">
    {{
      role === "student"
        ? "默认展开最新一条申请，其他记录可点击展开。"
        : "默认展开待审批及生成失败的申请，其他记录可点击展开。"
    }}
  </p>
  <RequestCard
    v-for="record in visibleRecords"
    :key="record.id"
    :request="record"
    :role="role"
    :busy="busy"
    :signature-version="signatureVersion"
    :expanded="isExpanded(record)"
    @toggle="toggle(record)"
    @decision="emit('decision', $event)"
    @retry="emit('retry', $event)"
    @withdraw="emit('withdraw', $event)"
  />
  <nav v-if="pageCount > 1" class="record-pagination" aria-label="请假记录分页">
    <button class="light" :disabled="busy || page === 1" @click="page--">
      上一页
    </button>
    <span role="status"
      >第 {{ page }} / {{ pageCount }} 页 · 共 {{ records.length }} 条</span
    >
    <button
      class="light"
      :disabled="busy || page === pageCount"
      @click="page++"
    >
      下一页
    </button>
  </nav>
</template>

<style>
.record-toggle {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
  width: 100%;
  text-align: left;
}
.record-pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 16px;
}
</style>
