<script setup>
import {
  computed,
  defineAsyncComponent,
  onBeforeUnmount,
  ref,
  watch,
} from "vue";
import { api, pdfBlob, documentUrl } from "../api.js";
const PdfPreview = defineAsyncComponent(() => import("./PdfPreview.vue"));

const props = defineProps({
  request: { type: Object, required: true },
  role: String,
  busy: Boolean,
  signatureVersion: String,
});
const emit = defineEmits(["decision", "retry", "withdraw"]);
const opinion = ref("");
const dialog = ref(null);
const preview = ref(null);
const previewUrls = ref([]);
const previewBusy = ref(false);
const previewError = ref("");
const selected = ref(0);
const seen = ref(new Set());
const confirmed = ref(false);
const viewingDocument = ref(null);
const withdrawalDialog = ref(null);
const withdrawalReason = ref("");
let previewGeneration = 0;
const canApprove = computed(
  () =>
    preview.value &&
    !viewingDocument.value &&
    !previewBusy.value &&
    confirmed.value &&
    seen.value.size === previewUrls.value.length &&
    previewUrls.value.length > 0,
);
function clearPreview() {
  previewGeneration++;
  previewUrls.value.forEach((url) => URL.revokeObjectURL(url));
  previewUrls.value = [];
  preview.value = null;
  viewingDocument.value = null;
  confirmed.value = false;
  seen.value = new Set();
}
watch([opinion, () => props.signatureVersion], () => {
  clearPreview();
  dialog.value?.close();
});
onBeforeUnmount(clearPreview);
watch(
  () => props.request.status,
  () => {
    clearPreview();
    dialog.value?.close();
    withdrawalDialog.value?.close();
  },
);
async function openPreview() {
  if (previewBusy.value) return;
  clearPreview();
  const generation = previewGeneration;
  previewError.value = "";
  previewBusy.value = true;
  selected.value = 0;
  dialog.value.showModal();
  const urls = [];
  try {
    const result = await api(`requests/${props.request.id}/preview`, {
      opinion: opinion.value,
    });
    for (let i = 0; i < result.count; i++)
      urls.push(await pdfBlob(`previews/${result.id}/${i}`));
    if (generation !== previewGeneration) {
      urls.forEach((url) => URL.revokeObjectURL(url));
      return;
    }
    preview.value = result;
    previewUrls.value = urls;
    seen.value = new Set();
  } catch (error) {
    urls.forEach((url) => URL.revokeObjectURL(url));
    previewError.value = error.message;
  } finally {
    previewBusy.value = false;
  }
}
function choosePreview(index) {
  selected.value = index;
}
function rendered(url) {
  const index = previewUrls.value.indexOf(url);
  if (index >= 0) seen.value = new Set([...seen.value, index]);
}
async function viewDocument(document) {
  if (previewBusy.value) return;
  clearPreview();
  const generation = previewGeneration;
  viewingDocument.value = document;
  previewError.value = "";
  previewBusy.value = true;
  selected.value = 0;
  dialog.value.showModal();
  try {
    const url = await pdfBlob(`documents/${document.id}`);
    if (generation !== previewGeneration) {
      URL.revokeObjectURL(url);
      return;
    }
    previewUrls.value = [url];
  } catch (error) {
    previewError.value = error.message;
  } finally {
    previewBusy.value = false;
  }
}
function approve() {
  if (!canApprove.value || props.busy) return;
  emit("decision", {
    id: props.request.id,
    outcome: "approved",
    opinion: opinion.value,
    preview_id: preview.value.id,
  });
  dialog.value.close();
}
const statuses = {
  pending: "待审批",
  approved: "已通过",
  rejected: "已驳回",
  withdrawn: "学生已撤回",
  revoked: "辅导员已撤回",
};
const fileStatuses = {
  not_started: "等待审批",
  generating: "文件生成中",
  ready: "文件已生成",
  failed: "审批已通过，文件生成失败",
  cancelled: "已撤回，不能继续操作",
};
const kinds = { course: "课程", activity: "活动", other: "其他" };
</script>

<template>
  <article class="record">
    <div class="section-title">
      <h3>{{ request.student.name }}</h3>
      <span class="status" :class="request.status">{{
        statuses[request.status]
      }}</span>
    </div>
    <p>
      {{ request.starts }} 至 {{ request.ends }} ·
      {{ request.layout === "combined" ? "合并生成" : "分别生成" }}
    </p>
    <p class="muted">
      {{ request.student.class_name || "历史班级记录" }} ·
      {{ request.student.student_number }}
    </p>
    <p>{{ request.reason }}</p>
    <ul>
      <li v-for="(item, index) in request.items" :key="index">
        {{ kinds[item.kind] }} · {{ item.title }}<br />{{ item.day }}
        {{ item.time }}
      </li>
    </ul>
    <p v-if="request.approval" class="muted">
      {{ request.approval.approver }} ·
      {{ new Date(request.approval.at).toLocaleString() }}<br />审批意见：{{
        request.approval.opinion || "同意"
      }}
    </p>
    <p class="muted">{{ fileStatuses[request.file_status] }}</p>
    <p v-if="request.withdrawal" class="muted">
      {{ request.withdrawal.actor }} ·
      {{ new Date(request.withdrawal.at).toLocaleString() }}<br />
      撤回原因：{{ request.withdrawal.reason || "未填写" }}
    </p>
    <a
      v-for="document in request.documents"
      :key="document.id"
      class="file"
      target="_blank"
      rel="noopener"
      :href="documentUrl(document.id)"
      @click.prevent="viewDocument(document)"
      >查看 PDF · {{ document.name }}</a
    >
    <template v-if="role === 'counselor' && request.status === 'pending'">
      <textarea
        v-model="opinion"
        placeholder="审批意见（驳回时必填）"
        maxlength="2000"
        aria-label="审批意见"
        :disabled="busy"
      ></textarea>
      <div class="actions">
        <button
          :disabled="busy || previewBusy || !signatureVersion"
          @click="openPreview"
        >
          预览并审批
        </button>
        <button
          :disabled="busy"
          @click="
            emit('decision', { id: request.id, outcome: 'rejected', opinion })
          "
        >
          驳回申请
        </button>
      </div>
      <p v-if="!signatureVersion" class="muted caption">
        请先在上方保存个人签名，再预览和通过申请。驳回无需签名。
      </p>
    </template>
    <button
      v-if="request.status === 'approved' && request.file_status === 'failed'"
      :disabled="busy"
      @click="emit('retry', request.id)"
    >
      重新生成文件
    </button>
    <button
      v-if="
        (role === 'student' && request.status === 'pending') ||
        (role === 'counselor' && request.status === 'approved')
      "
      class="danger"
      :disabled="busy"
      @click="withdrawalDialog.showModal()"
    >
      {{ role === "student" ? "撤回申请" : "撤回请假条" }}
    </button>
    <dialog
      ref="withdrawalDialog"
      class="preview-dialog feedback-dialog"
      :aria-labelledby="`withdraw-title-${request.id}`"
    >
      <h2 :id="`withdraw-title-${request.id}`">
        {{ role === "student" ? "撤回申请" : "撤回请假条" }}
      </h2>
      <p>
        {{
          role === "student"
            ? "撤回后双方仍可查看记录，但不能再审批或操作。"
            : "撤回后保留审批记录，系统中的 PDF 将失效，不能再查看、下载或生成。"
        }}
      </p>
      <label
        >撤回原因（选填）<textarea
          v-model="withdrawalReason"
          maxlength="2000"
          :disabled="busy"
        ></textarea>
      </label>
      <div class="actions">
        <button
          class="danger"
          :disabled="busy"
          @click="
            withdrawalDialog.close();
            emit('withdraw', { id: request.id, reason: withdrawalReason });
          "
        >
          确认撤回
        </button>
        <button class="light" @click="withdrawalDialog.close()">取消</button>
      </div>
    </dialog>
    <dialog ref="dialog" class="preview-dialog" @close="clearPreview">
      <div class="section-title">
        <div>
          <small>{{
            viewingDocument ? "SIGNED LEAVE DOCUMENT" : "REVIEW BEFORE APPROVAL"
          }}</small>
          <h2>{{ viewingDocument ? "已签署请假条" : "请假条审批预览" }}</h2>
        </div>
        <button class="light" aria-label="关闭预览" @click="dialog.close()">
          关闭
        </button>
      </div>
      <p v-if="!viewingDocument" class="muted caption">
        核对申请内容与签名。预览有效期 15 分钟，通过后会留存本次签名快照。
      </p>
      <p v-else class="muted caption">
        {{ request.student.name }} · {{ viewingDocument.name }} ·
        已保存的审批文件
      </p>
      <p v-if="previewBusy" role="status">正在加载带签名的请假条…</p>
      <p v-if="previewError" role="alert" class="inline-error">
        {{ previewError }}
      </p>
      <template v-if="previewUrls.length">
        <div v-if="previewUrls.length > 1" class="preview-tabs">
          <button
            v-for="(_, index) in previewUrls"
            :key="index"
            :class="{ light: selected !== index }"
            @click="choosePreview(index)"
          >
            请假条 {{ index + 1 }} {{ seen.has(index) ? "✓" : "" }}
          </button>
        </div>
        <PdfPreview :url="previewUrls[selected]" @loaded="rendered" />
        <a
          class="file"
          :href="previewUrls[selected]"
          target="_blank"
          rel="noopener"
          >在新窗口查看当前 PDF</a
        >
        <p v-if="preview?.watermark" class="caption">
          签名水印：{{ preview.watermark }}
        </p>
        <label v-if="!viewingDocument" class="radio"
          ><input
            v-model="confirmed"
            type="checkbox"
            :disabled="busy"
          />我已核对全部请假条及签名，确认通过申请</label
        >
        <div v-if="!viewingDocument" class="actions">
          <button :disabled="busy || !canApprove" @click="approve">
            确认通过并签署</button
          ><button class="light" @click="dialog.close()">返回修改</button>
        </div>
      </template>
    </dialog>
  </article>
</template>
