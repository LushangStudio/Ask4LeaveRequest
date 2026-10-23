<script setup>
import {
  computed,
  defineAsyncComponent,
  onBeforeUnmount,
  onMounted,
  ref,
  watch,
} from "vue";
import { api, apiUrl, pdfBlob, documentUrl } from "../api.js";
import { statuses, timestamp } from "../request-display.js";
import SavePdf from "./SavePdf.vue";
const PdfPreview = defineAsyncComponent(() => import("./PdfPreview.vue"));

const props = defineProps({
  request: { type: Object, required: true },
  role: String,
  busy: Boolean,
  signatureVersion: String,
});
const emit = defineEmits(["decision", "retry", "withdraw", "close"]);
const opinion = ref("");
const dialog = ref(null);
const preview = ref(null);
const preparedOpinion = ref(null);
const pendingReview = computed(
  () => props.role === "counselor" && props.request.status === "pending",
);
const canWithdraw = computed(
  () =>
    (props.role === "student" && props.request.status === "pending") ||
    (props.role === "counselor" && props.request.status === "approved"),
);
const previewUrls = ref([]);
const previewBlobs = ref([]);
const transfer = ref(null);
let previewController;
function transferProgress(generation, index, count) {
  return (progress) => {
    if (generation === previewGeneration)
      transfer.value = { ...progress, index: index + 1, count };
  };
}
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
    pendingReview.value &&
    preparedOpinion.value === opinion.value.trim() &&
    preview.value &&
    !viewingDocument.value &&
    !previewBusy.value &&
    confirmed.value &&
    seen.value.size === previewUrls.value.length &&
    previewUrls.value.length > 0,
);
function clearPreview() {
  previewGeneration++;
  previewController?.abort();
  previewBusy.value = false;
  transfer.value = null;
  previewBlobs.value = [];
  previewUrls.value.forEach((url) => URL.revokeObjectURL(url));
  previewUrls.value = [];
  preview.value = null;
  viewingDocument.value = null;
  confirmed.value = false;
  seen.value = new Set();
}
watch(opinion, () => {
  confirmed.value = false;
});
watch(
  () => props.signatureVersion,
  () => {
    clearPreview();
  },
);
onMounted(() => {
  if (!dialog.value.open) dialog.value.showModal();
  if (pendingReview.value && props.signatureVersion) openPreview();
  else if (props.request.documents.length)
    viewDocument(props.request.documents[0]);
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
  const controller = new AbortController();
  previewController = controller;
  previewError.value = "";
  previewBusy.value = true;
  selected.value = 0;
  if (!dialog.value.open) dialog.value.showModal();
  const urls = [];
  const blobs = [];
  try {
    const sentOpinion = opinion.value.trim();
    const result = await api(`requests/${props.request.id}/preview`, {
      opinion: sentOpinion,
    });
    if (generation !== previewGeneration) return;
    for (let i = 0; i < result.count; i++) {
      const file = await pdfBlob(`previews/${result.id}/${i}`, {
        signal: controller.signal,
        onProgress: transferProgress(generation, i, result.count),
      });
      urls.push(file.url);
      blobs.push(file.blob);
    }
    if (generation !== previewGeneration) {
      urls.forEach((url) => URL.revokeObjectURL(url));
      return;
    }
    preview.value = result;
    preparedOpinion.value = sentOpinion;
    previewUrls.value = urls;
    previewBlobs.value = blobs;
    seen.value = new Set();
  } catch (error) {
    urls.forEach((url) => URL.revokeObjectURL(url));
    if (generation === previewGeneration && error.name !== "AbortError")
      previewError.value = error.message;
  } finally {
    if (generation === previewGeneration) previewBusy.value = false;
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
  const controller = new AbortController();
  previewController = controller;
  viewingDocument.value = document;
  previewError.value = "";
  previewBusy.value = true;
  selected.value = 0;
  if (!dialog.value.open) dialog.value.showModal();
  try {
    const { url, blob } = await pdfBlob(`documents/${document.id}`, {
      signal: controller.signal,
      onProgress: transferProgress(generation, 0, 1),
    });
    if (generation !== previewGeneration) {
      URL.revokeObjectURL(url);
      return;
    }
    previewUrls.value = [url];
    previewBlobs.value = [blob];
  } catch (error) {
    if (generation === previewGeneration && error.name !== "AbortError")
      previewError.value = error.message;
  } finally {
    if (generation === previewGeneration) previewBusy.value = false;
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
}
const fileStatuses = {
  not_started: "等待审批",
  generating: "文件生成中",
  ready: "文件已生成",
  failed: "审批已通过，文件生成失败",
  cancelled: "已撤回，不能继续操作",
};
</script>

<template>
  <dialog
    ref="dialog"
    class="preview-dialog request-dialog"
    aria-labelledby="request-detail-title"
    @close="
      clearPreview();
      emit('close');
    "
  >
    <div class="dialog-header">
      <h2 id="request-detail-title">
        {{ pendingReview ? "请假条审批预览" : "请假申请详情" }}
        <span class="status" :class="request.status">{{
          statuses[request.status]
        }}</span>
      </h2>
      <button
        class="light"
        aria-label="关闭详情"
        :disabled="busy"
        @click="dialog.close()"
      >
        关闭
      </button>
    </div>
    <div class="dialog-body request-detail-body">
      <section class="request-metadata">
        <h3>
          {{ request.student.name }} · {{ request.student.student_number }}
        </h3>
        <p>
          {{ request.student.class_name || "历史班级记录" }} ·
          {{ request.student.major }}
        </p>
        <p v-if="!request.items.length">
          {{ request.starts }} 至 {{ request.ends }}（历史起止日期申请）
        </p>
        <p><strong>请假原因：</strong>{{ request.reason }}</p>
        <ol>
          <li v-for="(item, index) in request.items" :key="index">
            {{ item.day }} · {{ item.time }}<br />{{ item.title }}
          </li>
        </ol>
        <p>
          生成方式：{{
            request.layout === "combined" ? "合并生成" : "分别生成"
          }}
        </p>
        <p>提交时间：{{ timestamp(request.created) }}</p>
        <p v-if="request.approval">
          审批人：{{ request.approval.approver }} ·
          {{ timestamp(request.approval.at) }}<br />审批意见：{{
            request.approval.opinion ||
            (request.approval.outcome === "approved" ? "同意" : "未填写")
          }}
        </p>
        <details v-if="request.history?.length">
          <summary>历史审批与撤回（{{ request.history.length }} 次）</summary>
          <p v-for="entry in request.history" :key="entry.withdrawal.at">
            {{ entry.approval.approver }} 于
            {{ timestamp(entry.approval.at) }} 通过：{{
              entry.approval.opinion || "同意"
            }}<br />
            {{ entry.withdrawal.actor }} 于
            {{ timestamp(entry.withdrawal.at) }} 撤回至待审批：{{
              entry.withdrawal.reason || "未填写原因"
            }}
          </p>
        </details>
        <p v-if="request.withdrawal">
          撤回人：{{ request.withdrawal.actor }} ·
          {{ timestamp(request.withdrawal.at) }}<br />撤回原因：{{
            request.withdrawal.reason || "未填写"
          }}
        </p>
        <p>{{ fileStatuses[request.file_status] }}</p>
        <div v-if="request.attachments?.length">
          <h3>申请附件</h3>
          <p class="caption">
            保留至 {{ request.attachments_retained_through }}
          </p>
          <ul>
            <li v-for="attachment in request.attachments" :key="attachment.id">
              <a
                class="attachment-link"
                :href="
                  apiUrl(`attachments/${encodeURIComponent(attachment.id)}`)
                "
                target="_blank"
                rel="noopener"
                >{{ attachment.name }}</a
              >
              · {{ Math.ceil(attachment.size / 1024) }} KB
            </li>
          </ul>
        </div>
        <p v-else-if="request.attachments_expired" class="caption">
          已超过附件保留期限。
        </p>
      </section>
      <section
        class="request-pdf"
        v-if="pendingReview || request.documents.length"
      >
        <div v-if="request.documents.length > 1" class="preview-tabs">
          <button
            v-for="doc in request.documents"
            :key="doc.id"
            :class="{ light: viewingDocument?.id !== doc.id }"
            :disabled="previewBusy"
            @click="viewDocument(doc)"
          >
            查看 PDF {{ request.documents.indexOf(doc) + 1 }}
          </button>
        </div>
        <p v-if="pendingReview && !signatureVersion" class="caption">
          请先保存个人签名，再预览和通过申请。驳回无需签名。
        </p>
        <div v-if="previewBusy" role="status">
          <p v-if="!transfer">正在准备请假条…</p>
          <template v-else
            ><p>
              正在接收 PDF {{ transfer.index }}/{{ transfer.count }} ·
              {{ Math.ceil(transfer.loaded / 1024) }} KB
            </p>
            <progress
              aria-label="PDF 接收进度"
              :value="transfer.total ? transfer.loaded : undefined"
              :max="transfer.total || 1"
          /></template>
        </div>
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
          <PdfPreview
            :url="previewUrls[selected]"
            :blob="previewBlobs[selected]"
            @loaded="rendered"
          />
          <SavePdf
            :source-url="
              viewingDocument
                ? documentUrl(viewingDocument.id)
                : apiUrl(`previews/${preview.id}/${selected}`)
            "
            :blob="previewBlobs[selected]"
            :filename="
              viewingDocument?.name ||
              preview?.filenames?.[selected] ||
              '请假条.pdf'
            "
          />
          <p v-if="preview?.watermark" class="caption">
            签名水印：{{ preview.watermark }}
          </p>
        </template>
      </section>
    </div>
    <div class="dialog-footer">
      <template v-if="pendingReview">
        <label class="opinion-field"
          >审批意见（驳回时必填）<textarea
            v-model="opinion"
            maxlength="2000"
            rows="2"
            :disabled="busy"
            aria-label="审批意见"
          ></textarea>
        </label>
        <div class="approval-controls">
          <label class="radio"
            ><input
              v-model="confirmed"
              type="checkbox"
              :disabled="
                busy ||
                !preview ||
                preparedOpinion !== opinion.trim() ||
                seen.size !== previewUrls.length
              "
            />我已核对全部请假条及签名</label
          >
          <div class="actions">
            <button
              v-if="
                !preview || preparedOpinion !== opinion.trim() || previewError
              "
              class="light"
              :disabled="busy || previewBusy || !signatureVersion"
              @click="openPreview"
            >
              {{ preview ? "更新审批预览" : "加载审批预览" }}
            </button>
            <button :disabled="busy || !canApprove" @click="approve">
              确认通过并签署
            </button>
            <button
              class="danger"
              :disabled="busy || !opinion.trim()"
              @click="
                emit('decision', {
                  id: request.id,
                  outcome: 'rejected',
                  opinion: opinion.trim(),
                })
              "
            >
              驳回申请
            </button>
          </div>
        </div>
      </template>
      <div class="actions" v-else>
        <button
          v-if="
            request.status === 'approved' && request.file_status === 'failed'
          "
          :disabled="busy"
          @click="emit('retry', request.id)"
        >
          重新生成文件
        </button>
        <button
          v-if="canWithdraw"
          class="danger"
          :disabled="busy"
          @click="withdrawalDialog.showModal()"
        >
          {{ role === "student" ? "撤回申请" : "撤回" }}
        </button>
        <span
          v-if="!canWithdraw && request.file_status !== 'failed'"
          class="caption"
          >当前申请只读</span
        >
      </div>
    </div>
    <dialog
      ref="withdrawalDialog"
      class="preview-dialog feedback-dialog"
      aria-labelledby="withdraw-title"
    >
      <h2 id="withdraw-title">
        {{ role === "student" ? "撤回申请" : "撤回请假条" }}
      </h2>
      <p>
        {{
          role === "student"
            ? "撤回后保留记录，不能继续审批。"
            : "撤回后回到待审批，可重新通过或驳回；保留历史审批记录，原 PDF 立即失效。"
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
            emit('withdraw', {
              id: request.id,
              reason: withdrawalReason,
              approval_at: request.approval?.at,
            });
          "
        >
          确认撤回</button
        ><button class="light" @click="withdrawalDialog.close()">取消</button>
      </div>
    </dialog>
  </dialog>
</template>
