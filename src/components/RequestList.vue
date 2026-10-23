<script setup>
import { computed, ref, watch } from "vue";
import RequestCard from "./RequestCard.vue";
import {
  statuses,
  firstTitle,
  firstTime,
  firstDate,
  latestOpinion,
  timestamp,
} from "../request-display.js";
const props = defineProps({
  records: { type: Array, required: true },
  role: String,
  busy: Boolean,
  signatureVersion: String,
});
const emit = defineEmits(["decision", "retry", "withdraw"]);
const page = ref(1);
const selectedId = ref(null);
const selected = computed(() =>
  props.records.find((row) => row.id === selectedId.value),
);
const pageSize = 10;
const pageCount = computed(() =>
  Math.max(1, Math.ceil(props.records.length / pageSize)),
);
const visibleRecords = computed(() =>
  props.records.slice((page.value - 1) * pageSize, page.value * pageSize),
);
watch(
  () => props.records,
  (rows, previous) => {
    if (rows[0]?.id !== previous?.[0]?.id) page.value = 1;
    page.value = Math.min(page.value, pageCount.value);
    if (!rows.some((row) => row.id === selectedId.value))
      selectedId.value = null;
  },
);
</script>
<template>
  <div class="request-table-wrap" tabindex="0" aria-label="请假申请列表">
    <table class="request-table">
      <thead>
        <tr>
          <th>申请状态</th>
          <th>事项名称</th>
          <th>
            <span class="wide-only">事项时间</span
            ><span class="compact-only">日期</span>
          </th>
          <th>请假原因</th>
          <th>提交时间</th>
          <th>审批意见</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="record in visibleRecords"
          :key="record.id"
          class="request-row"
          :tabindex="busy ? -1 : 0"
          :aria-label="`查看申请详情：${record.student.name}，${firstTitle(record)}`"
          :aria-disabled="busy"
          @click="!busy && (selectedId = record.id)"
          @keydown.enter.self.prevent="!busy && (selectedId = record.id)"
          @keydown.space.self.prevent="!busy && (selectedId = record.id)"
        >
          <td>
            <span class="status" :class="record.status">{{
              statuses[record.status]
            }}</span
            ><small v-if="role === 'counselor'" class="row-student"
              >{{ record.student.name }} ·
              {{ record.student.student_number }}</small
            >
          </td>
          <td>
            <button
              class="name-link cell-ellipsis"
              :title="firstTitle(record)"
              :aria-label="`打开申请：${record.student.name}，${firstTitle(record)}`"
              :disabled="busy"
              @click.stop="selectedId = record.id"
            >
              {{ firstTitle(record) }}
            </button>
          </td>
          <td>
            <span class="cell-ellipsis wide-only" :title="firstTime(record)">{{
              firstTime(record)
            }}</span
            ><span class="compact-only compact-date">{{
              firstDate(record)
            }}</span>
          </td>
          <td>
            <span class="cell-ellipsis" :title="record.reason">{{
              record.reason
            }}</span>
          </td>
          <td>{{ timestamp(record.created) }}</td>
          <td>
            <span class="cell-ellipsis" :title="latestOpinion(record)">{{
              latestOpinion(record)
            }}</span>
          </td>
          <td>
            <button
              class="light"
              :disabled="busy"
              :aria-label="`查看详情：${record.student.name}，${firstTitle(record)}`"
              @click.stop="selectedId = record.id"
            >
              查看详情
            </button>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
  <RequestCard
    v-if="selected"
    :key="selected.id"
    :request="selected"
    :role="role"
    :busy="busy"
    :signature-version="signatureVersion"
    @close="selectedId = null"
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
