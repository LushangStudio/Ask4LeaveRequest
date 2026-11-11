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
  reviewPage: Object,
  reviewFilters: Object,
});
const emit = defineEmits([
  "decision",
  "retry",
  "withdraw",
  "page",
  "batch-approve",
  "batch-export",
]);
const localPage = ref(1);
const page = computed(() => props.reviewPage?.page ?? localPage.value);
const bulk = ref(false);
const checked = ref([]);
const confirmDialog = ref(null);
const opinion = ref("");
function downloadable(row) {
  return row.status === "approved" && row.file_status === "ready";
}
function eligible(row) {
  return row.status === "pending" || downloadable(row);
}
const eligibleIds = computed(() =>
  visibleRecords.value.filter(eligible).map((row) => row.id),
);
const checkedRows = computed(() =>
  visibleRecords.value.filter(
    (row) => checked.value.includes(row.id) && eligible(row),
  ),
);
const selectedForApproval = computed(() =>
  checkedRows.value.filter((row) => row.status === "pending"),
);
const selectedForDownload = computed(() =>
  checkedRows.value.filter(downloadable),
);
const allChecked = computed(
  () =>
    eligibleIds.value.length > 0 &&
    checkedRows.value.length === eligibleIds.value.length,
);
function toggleAll(event) {
  checked.value = event.target.checked ? [...eligibleIds.value] : [];
}
function changePage(next) {
  if (props.reviewPage) emit("page", next);
  else localPage.value = next;
}
function confirmBatch() {
  if (
    props.busy ||
    !props.signatureVersion ||
    !selectedForApproval.value.length
  )
    return;
  confirmDialog.value.close();
  emit("batch-approve", {
    ids: selectedForApproval.value.map((row) => row.id),
    opinion: opinion.value,
  });
}
watch([bulk, page, () => props.reviewFilters], () => {
  checked.value = [];
  opinion.value = "";
});

const selectedId = ref(null);
const selected = computed(() =>
  props.records.find((row) => row.id === selectedId.value),
);
const pageSize = 10;
const pageCount = computed(
  () =>
    props.reviewPage?.pages ??
    Math.max(1, Math.ceil(props.records.length / pageSize)),
);
const visibleRecords = computed(() =>
  props.reviewPage
    ? props.records
    : props.records.slice((page.value - 1) * pageSize, page.value * pageSize),
);
watch(
  () => props.records,
  (rows, previous) => {
    if (!props.reviewPage) {
      if (rows[0]?.id !== previous?.[0]?.id) localPage.value = 1;
      localPage.value = Math.min(localPage.value, pageCount.value);
    }
    checked.value = checked.value.filter((id) =>
      rows.some((row) => row.id === id && eligible(row)),
    );
    if (!rows.some((row) => row.id === selectedId.value))
      selectedId.value = null;
  },
);
</script>
<template>
  <div v-if="role === 'counselor'" class="batch-toolbar">
    <button
      type="button"
      class="light"
      :disabled="busy"
      :aria-expanded="bulk"
      @click="bulk = !bulk"
    >
      {{ bulk ? "退出批量操作" : "批量操作" }}
    </button>
    <template v-if="bulk">
      <label class="batch-check"
        ><input
          type="checkbox"
          :checked="allChecked"
          :disabled="busy || !eligibleIds.length"
          @change="toggleAll"
        />全选本页可操作申请</label
      >
      <span role="status">
        已选 {{ checkedRows.length }} 份 · 待同意
        {{ selectedForApproval.length }} 份 · 可下载
        {{ selectedForDownload.length }} 份
      </span>
      <button
        type="button"
        :disabled="busy || !selectedForApproval.length || !signatureVersion"
        @click="confirmDialog.showModal()"
      >
        批量同意
      </button>
      <button
        type="button"
        :disabled="busy || !selectedForDownload.length"
        @click="
          emit(
            'batch-export',
            selectedForDownload.map((row) => row.id),
          )
        "
      >
        批量下载
      </button>
      <small v-if="selectedForApproval.length && !signatureVersion"
        >请先保存个人签名。</small
      >
    </template>
  </div>
  <p v-if="!records.length" class="empty">没有符合条件的申请</p>
  <div
    v-if="records.length"
    class="request-table-wrap"
    tabindex="0"
    aria-label="请假申请列表"
  >
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
            <input
              v-if="bulk && eligible(record)"
              v-model="checked"
              class="batch-row-check"
              type="checkbox"
              :value="record.id"
              :disabled="busy"
              :aria-label="`选择申请：${record.student.name}，${firstTitle(record)}`"
              @click.stop
            />
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
  <nav
    v-if="reviewPage || pageCount > 1"
    class="record-pagination"
    aria-label="请假记录分页"
  >
    <button
      class="light"
      :disabled="busy || page === 1"
      @click="changePage(page - 1)"
    >
      上一页
    </button>
    <span role="status"
      >第 {{ page }} / {{ pageCount }} 页 · 共
      {{ reviewPage?.total ?? records.length }} 条</span
    >
    <button
      class="light"
      :disabled="busy || page === pageCount"
      @click="changePage(page + 1)"
    >
      下一页
    </button>
  </nav>
  <dialog
    v-if="role === 'counselor'"
    ref="confirmDialog"
    class="preview-dialog feedback-dialog"
    aria-labelledby="batch-title"
  >
    <h2 id="batch-title">
      确认批量同意 {{ selectedForApproval.length }} 份申请
    </h2>
    <p>请核对所选申请。确认后将使用当前签名逐份签署。</p>
    <ul>
      <li v-for="row in selectedForApproval" :key="row.id">
        {{ row.student.name }} · {{ row.student.student_number }} ·
        {{ firstTitle(row) }} · {{ firstDate(row) }}
        <p class="caption">请假原因 {{ row.reason }}</p>
      </li>
    </ul>
    <label
      >统一审批意见（可选）<textarea
        v-model="opinion"
        rows="2"
        maxlength="2000"
        :disabled="busy"
      />
    </label>
    <div class="actions">
      <button
        type="button"
        :disabled="busy || !selectedForApproval.length || !signatureVersion"
        @click="confirmBatch"
      >
        确认同意并签署
      </button>
      <button type="button" class="light" @click="confirmDialog.close()">
        取消
      </button>
    </div>
  </dialog>
</template>
