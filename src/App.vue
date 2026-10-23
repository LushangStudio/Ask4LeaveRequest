<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";
import { api, apiUrl } from "./api.js";
import LeaveForm from "./components/LeaveForm.vue";
import RequestList from "./components/RequestList.vue";
import SignatureEditor from "./components/SignatureEditor.vue";
import AccountMenu from "./components/AccountMenu.vue";
import FeedbackDialog from "./components/FeedbackDialog.vue";

const user = ref(null);
const viewRole = ref("student");
const identity = ref("student-a");
const records = ref([]);
const message = ref("");
const formMessage = ref("");
const busy = ref(false);
const formVersion = ref(0);
const studentTab = ref("apply");
const identities = ref([]);
const signatureVersion = ref(null);
const runtime = ref({
  mode: "test",
  demo_login: false,
  uis_login: false,
  app_list_url: "/",
});
const loginHint = computed(() =>
  runtime.value.demo_login
    ? "请选择演示身份开始体验。"
    : runtime.value.uis_login
      ? "请使用复旦UIS登录。"
      : "请通过运维提供的测试登录链接进入。",
);
const profile = computed(() =>
  user.value
    ? [
        user.value.name,
        ...["college", "major", "grade", "class_name", "student_number"].map(
          (key) => user.value.profile[key],
        ),
      ]
        .filter(Boolean)
        .join(" · ")
    : "",
);

async function loadRecords() {
  try {
    const currentUser = await api("me");
    const roles = currentUser.roles || [currentUser.role];
    if (!roles.includes(viewRole.value)) viewRole.value = roles[0] || "";
    const rows = roles.length
      ? await api(`requests?view=${viewRole.value}`)
      : [];
    user.value = currentUser;
    identity.value = currentUser.id;
    records.value = rows;
  } catch (error) {
    // Never retain another identity's records after the session changes or expires.
    user.value = null;
    records.value = [];
    signatureVersion.value = null;
    throw error;
  }
}
async function run(
  action,
  { messageTarget = message, silentUnauthorized = false } = {},
) {
  if (busy.value) return;
  busy.value = true;
  messageTarget.value = "";
  try {
    await action();
  } catch (error) {
    if (!(silentUnauthorized && error.status === 401))
      messageTarget.value =
        error.status === 401 ? loginHint.value : error.message;
  } finally {
    busy.value = false;
  }
}
function login() {
  return run(async () => {
    await api("demo/login", { person_id: identity.value });
    user.value = null;
    records.value = [];
    signatureVersion.value = null;
    formMessage.value = "";
    formVersion.value++;
    studentTab.value = "apply";
    await loadRecords();
  });
}
function submit(payload) {
  return run(
    async () => {
      await api("requests", payload);
      formVersion.value++;
      await loadRecords();
      studentTab.value = "records";
      message.value = "申请已提交，等待辅导员审批。";
    },
    { messageTarget: formMessage },
  );
}
function decide({ id, outcome, opinion, preview_id }) {
  return run(async () => {
    await api(`requests/${id}/decision`, { outcome, opinion, preview_id });
    await loadRecords();
    message.value = "审批结果已保存";
  });
}
function retry(id) {
  return run(async () => {
    await api(`requests/${id}/retry`, {});
    await loadRecords();
  });
}
function withdraw({ id, reason, approval_at }) {
  return run(async () => {
    await api(`requests/${id}/withdraw`, {
      reason,
      role: viewRole.value,
      approval_at,
    });
    await loadRecords();
    message.value =
      viewRole.value === "counselor"
        ? "已退回待审批，原 PDF 失效，历史记录保留。"
        : "已撤回，历史记录保留。";
  });
}
function logout() {
  return run(async () => {
    await api("logout", {});
    user.value = null;
    records.value = [];
    signatureVersion.value = null;
    formMessage.value = "";
    message.value = loginHint.value;
  });
}
let pollTimer;
onUnmounted(() => clearInterval(pollTimer));
onMounted(async () => {
  pollTimer = setInterval(() => {
    if (
      document.visibilityState === "visible" &&
      user.value &&
      !busy.value &&
      records.value.some((row) => row.file_status === "generating")
    ) {
      run(loadRecords);
    }
  }, 3000);
  try {
    runtime.value = await api("runtime");
    if (runtime.value.demo_login) {
      identities.value = await api("demo/identities");
      if (identities.value.length) identity.value = identities.value[0].id;
    }
  } catch (error) {
    message.value = error.message;
  }
  await run(loadRecords, { silentUnauthorized: true });
});
</script>

<template>
  <header class="app-header">
    <div class="header-inner">
      <div class="brand">
        <div class="brand-icon">
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="1.8"
            aria-hidden="true"
          >
            <path
              d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"
            />
            <path d="M14 2v6h6M8 13h8M8 17h5" />
          </svg>
        </div>
        <div>
          <p>STUDENT AFFAIRS DESK</p>
          <h1>电子请假工作台</h1>
        </div>
      </div>
      <div class="header-actions">
        <a v-if="user?.is_admin" class="button outline" href="class-management/"
          >班级管理</a
        >
        <a class="button outline" :href="runtime.app_list_url"
          >← 返回应用列表</a
        >
        <label v-if="user?.roles?.length > 1" class="role-switch"
          >当前视角
          <select
            v-model="viewRole"
            :disabled="busy"
            @change="run(loadRecords)"
          >
            <option value="student">学生</option>
            <option value="counselor">辅导员</option>
          </select>
        </label>
        <AccountMenu v-if="user" :user="user" :busy="busy" @logout="logout" />
        <a
          v-else-if="runtime.uis_login"
          class="button"
          :href="apiUrl('auth/login')"
          >使用复旦UIS登录</a
        >
        <span v-else class="tag">{{
          runtime.demo_login ? "本地演示" : "测试联调"
        }}</span>
      </div>
    </div>
  </header>
  <main>
    <section class="hero">
      <div>
        <small>{{
          viewRole === "counselor" ? "APPROVAL WORKSPACE" : "LEAVE REQUEST"
        }}</small>
        <h2>{{ viewRole === "counselor" ? "审批与签署" : "申请与进度" }}</h2>
        <p>课程、活动与其他事项统一申请，审批后生成签名文书。</p>
      </div>
      <div v-if="runtime.demo_login" class="identity">
        <label for="identity">当前演示身份</label>
        <select id="identity" v-model="identity" :disabled="busy">
          <option
            v-for="person in identities"
            :key="person.id"
            :value="person.id"
          >
            {{ person.name }} ·
            {{
              person.role === "both"
                ? "学生兼辅导员"
                : person.role === "student"
                  ? "学生"
                  : "辅导员"
            }}
          </option>
        </select>
        <button id="login" :disabled="busy" @click="login">切换身份</button>
      </div>
      <div v-else-if="user" class="workspace-summary">
        <strong>{{ records.length }}</strong
        ><span>{{
          viewRole === "counselor" ? "份班级申请" : "份我的申请"
        }}</span>
      </div>
    </section>
    <div
      v-if="runtime.mode !== 'production' || user?.auth_provider === 'test'"
      class="notice"
    >
      {{
        user?.auth_provider === "test" || runtime.mode === "test"
          ? "测试联调环境"
          : "演示环境"
      }}仅使用虚构数据，生成文件不是正式请假凭证。
    </div>
    <FeedbackDialog :message="message" @close="message = ''" />
    <SignatureEditor
      v-if="user && viewRole === 'counselor'"
      :key="user.id"
      @saved="signatureVersion = $event.version"
    />
    <nav
      v-if="user && viewRole === 'student'"
      class="student-tabs"
      role="tablist"
      aria-label="学生工作台"
    >
      <button
        id="apply-tab"
        role="tab"
        :aria-selected="studentTab === 'apply'"
        aria-controls="apply-panel"
        :tabindex="studentTab === 'apply' ? 0 : -1"
        @keydown.right.prevent="
          studentTab = 'records';
          $event.currentTarget.nextElementSibling.focus();
        "
        @click="studentTab = 'apply'"
      >
        新建请假申请
      </button>
      <button
        id="records-tab"
        role="tab"
        :aria-selected="studentTab === 'records'"
        aria-controls="records-panel"
        :tabindex="studentTab === 'records' ? 0 : -1"
        @keydown.left.prevent="
          studentTab = 'apply';
          $event.currentTarget.previousElementSibling.focus();
        "
        @click="studentTab = 'records'"
      >
        我的申请（{{ records.length }}）
      </button>
    </nav>
    <div class="workspace single-column" :aria-busy="busy">
      <div
        v-if="user && viewRole === 'student'"
        v-show="studentTab === 'apply'"
        id="apply-panel"
        role="tabpanel"
        aria-labelledby="apply-tab"
      >
        <LeaveForm
          v-if="user && viewRole === 'student'"
          :key="`${user.id}-${formVersion}`"
          :profile="profile"
          :busy="busy"
          :message="formMessage"
          :max-end-date="runtime.max_end_date"
          @submit="submit"
          @message="formMessage = $event"
        />
      </div>
      <section
        v-show="!user || viewRole !== 'student' || studentTab === 'records'"
        id="records-panel"
        :role="user && viewRole === 'student' ? 'tabpanel' : undefined"
        :aria-labelledby="viewRole === 'student' ? 'records-tab' : 'list-title'"
        class="panel"
      >
        <div class="section-title">
          <h2 id="list-title">
            {{ viewRole === "counselor" ? "我负责的申请" : "我的申请" }}
          </h2>
          <button
            id="refresh"
            class="light"
            :disabled="busy"
            @click="run(loadRecords)"
          >
            刷新
          </button>
        </div>
        <div id="records" class="records">
          <div v-if="!user" class="empty">
            <p>{{ loginHint }}</p>
            <a
              v-if="runtime.uis_login"
              class="button"
              :href="apiUrl('auth/login')"
              >使用复旦UIS登录</a
            >
          </div>
          <div v-else-if="!records.length" class="empty">
            暂时没有申请<br /><small>提交后可在这里查看处理进度</small>
          </div>
          <RequestList
            v-else
            :key="`${user.id}-${viewRole}`"
            :records="records"
            :role="viewRole"
            :busy="busy"
            :signature-version="signatureVersion"
            @decision="decide"
            @retry="retry"
            @withdraw="withdraw"
          />
        </div>
      </section>
    </div>
  </main>
  <footer>路上工作室 · Lushang Studio</footer>
</template>
