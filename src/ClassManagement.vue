<script setup>
import { computed, onMounted, ref } from "vue";
import { api, apiUrl } from "./api.js";
import AccountMenu from "./components/AccountMenu.vue";
import FeedbackDialog from "./components/FeedbackDialog.vue";

const user = ref(null),
  runtime = ref({}),
  directory = ref(null),
  revision = ref("");
const busy = ref(false),
  message = ref(""),
  status = ref(""),
  active = ref("classes");
const original = ref(""),
  refreshDialog = ref(null);
const importText = ref(""),
  importPreview = ref(null),
  importDialog = ref(null);
const dirty = computed(
  () => directory.value && JSON.stringify(directory.value) !== original.value,
);
const workspaceUrl = new URL("../", window.location.href).href;
const studentFields = {
  user_id: "学号",
  college: "学院",
  major: "专业",
  grade: "年级",
};
const tabs = [
  { key: "classes", label: "班级" },
  { key: "counselors", label: "辅导员" },
  { key: "students", label: "学生" },
];
function accept(result) {
  directory.value = result.directory;
  directory.value.classes.forEach(
    (c) => (c.counselor_ids_text = c.counselor_ids.join(", ")),
  );
  revision.value = result.revision;
  original.value = JSON.stringify(directory.value);
}
async function refresh() {
  busy.value = true;
  status.value = "";
  try {
    accept(await api("admin/directory"));
  } catch (e) {
    message.value = e.message;
  } finally {
    busy.value = false;
  }
}
function requestRefresh() {
  if (dirty.value) refreshDialog.value.showModal();
  else refresh();
}
function add() {
  const blank =
    active.value === "classes"
      ? { class_id: "", name: "", counselor_ids: [], counselor_ids_text: "" }
      : active.value === "counselors"
        ? { user_id: "" }
        : {
            user_id: "",
            class_id: directory.value.classes[0]?.class_id || "",
            college: "",
            major: "",
            grade: "",
          };
  directory.value[active.value].push(blank);
  status.value = "";
}
function remove(index) {
  directory.value[active.value].splice(index, 1);
  status.value = "";
}
async function save() {
  busy.value = true;
  status.value = "";
  const payload = {
    version: 1,
    counselors: directory.value.counselors.map(({ user_id }) => ({
      user_id,
    })),
    classes: directory.value.classes.map(
      ({ class_id, name, counselor_ids_text }) => ({
        class_id,
        name,
        counselor_ids: counselor_ids_text
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
      }),
    ),
    students: directory.value.students.map(
      ({ user_id, class_id, college, major, grade }) => ({
        user_id,
        class_id,
        college,
        major,
        grade,
      }),
    ),
  };
  try {
    accept(
      await api("admin/directory", {
        directory: payload,
        revision: revision.value,
      }),
    );
    status.value = "已保存并生效，无需重启。";
  } catch (e) {
    status.value = e.message;
  } finally {
    busy.value = false;
  }
}
async function logout() {
  await api("logout", {});
  window.location.assign(workspaceUrl);
}
async function previewStudents() {
  busy.value = true;
  status.value = "";
  try {
    importPreview.value = await api("admin/students/import/preview", {
      text: importText.value,
      revision: revision.value,
    });
    importDialog.value.showModal();
  } catch (e) {
    status.value = e.message;
  } finally {
    busy.value = false;
  }
}
async function commitStudents() {
  busy.value = true;
  try {
    const result = await api("admin/students/import", {
      text: importText.value,
      revision: revision.value,
    });
    accept(result);
    importDialog.value.close();
    importText.value = "";
    importPreview.value = null;
    status.value = `导入完成：新增${result.created}人，更新${result.updated}人。`;
  } catch (e) {
    message.value = e.message;
  } finally {
    busy.value = false;
  }
}
onMounted(async () => {
  busy.value = true;
  try {
    runtime.value = await api("runtime");
    user.value = await api("me");
    if (user.value.is_admin) await refresh();
  } catch (e) {
    message.value =
      e.status === 401 ? "请先通过复旦UIS登录管理员账号。" : e.message;
  } finally {
    busy.value = false;
  }
});
</script>

<template>
  <header class="app-header">
    <div class="header-inner">
      <div class="brand">
        <div class="brand-icon">班</div>
        <div>
          <p>CLASS MANAGEMENT</p>
          <h1>班级管理</h1>
        </div>
      </div>
      <div class="header-actions">
        <a class="button outline" :href="workspaceUrl">返回工作台</a
        ><a class="button outline" :href="runtime.app_list_url || '/'"
          >返回应用列表</a
        >
        <AccountMenu v-if="user" :user="user" :busy="busy" @logout="logout" />
      </div>
    </div>
  </header>
  <main>
    <FeedbackDialog :message="message" @close="message = ''" />
    <section v-if="!user?.is_admin" class="panel empty">
      <h2>仅管理员可访问</h2>
      <p>请使用服务器配置中的管理员学工号登录。</p>
      <a v-if="!user" class="button" :href="apiUrl('auth/login')"
        >使用复旦UIS登录</a
      >
    </section>
    <template v-else-if="directory">
      <section class="hero">
        <div>
          <small>DIRECTORY ADMINISTRATION</small>
          <h2>管理班级与人员</h2>
          <p>
            学生仅属一个班级，可兼任辅导员；班级支持多位辅导员，也允许本人担任自己的辅导员。
          </p>
        </div>
      </section>
      <div class="notice">
        名单持久化保存在数据库，保存后立即生效。删除人员会停用其业务权限，历史申请和审批记录保留。更换班级或辅导员只影响新申请。
      </div>
      <section class="panel">
        <div class="section-title">
          <div class="actions admin-tabs">
            <button
              v-for="tab in tabs"
              :key="tab.key"
              :class="{ light: active !== tab.key }"
              :disabled="busy"
              @click="active = tab.key"
            >
              {{ tab.label }} · {{ directory[tab.key].length }}
            </button>
          </div>
          <button class="light" :disabled="busy" @click="requestRefresh">
            刷新名单
          </button>
        </div>
        <form @submit.prevent="save">
          <fieldset class="form-fields" :disabled="busy">
            <section v-if="active === 'students'" class="item">
              <h3>批量导入学生</h3>
              <p class="caption">
                每行一人：学号,班级,学院,专业,年级。班级填写已有班级编号或唯一名称，使用英文逗号；同学号更新资料。先保存当前编辑，再导入。
              </p>
              <label
                >学生批量名单<textarea
                  v-model="importText"
                  rows="6"
                  placeholder="STUDENT001,class-2026-a,管理学院,工商管理,2026"
                  @input="importPreview = null"
                ></textarea>
              </label>
              <button
                type="button"
                :disabled="busy || dirty || !importText.trim()"
                @click="previewStudents"
              >
                校验并预览导入
              </button>
            </section>
            <p class="caption">
              {{
                active === "classes"
                  ? "班级编号及学工号使用字母、数字、下划线或连字符；多个辅导员工号用英文逗号分隔。"
                  : "学工号必须与UIS一致。兼任学生和辅导员时，两处填写相同学工号；师生姓名均从UIS登录获取。"
              }}
            </p>
            <div
              v-for="(row, index) in directory[active]"
              :key="`${active}-${index}`"
              class="item admin-row"
            >
              <div class="item-head">
                <b
                  >{{ tabs.find((t) => t.key === active).label }}
                  {{ index + 1 }}</b
                ><button type="button" class="danger" @click="remove(index)">
                  删除此{{ tabs.find((t) => t.key === active).label }}
                </button>
              </div>
              <template v-if="active === 'classes'"
                ><div class="two">
                  <label
                    >班级编号<input
                      v-model="row.class_id"
                      required
                      maxlength="40" /></label
                  ><label
                    >班级名称<input v-model="row.name" required maxlength="80"
                  /></label>
                </div>
                <label
                  >辅导员工号（英文逗号分隔）<input
                    v-model="row.counselor_ids_text"
                    required
                    placeholder="例如：STAFF001, STAFF002" /></label
              ></template>
              <div v-else-if="active === 'counselors'" class="two">
                <label
                  >工号<input v-model="row.user_id" required maxlength="40"
                /></label>
              </div>
              <template v-else
                ><div class="two">
                  <label v-for="(label, key) in studentFields" :key="key"
                    >{{ label
                    }}<input
                      v-model="row[key]"
                      required
                      :maxlength="
                        key === 'user_id' ? 40 : key === 'grade' ? 20 : 80
                      " /></label
                  ><label
                    >所属班级<select v-model="row.class_id" required>
                      <option value="" disabled>请选择班级</option>
                      <option
                        v-for="group in directory.classes"
                        :key="group.class_id"
                        :value="group.class_id"
                      >
                        {{ group.name }} · {{ group.class_id }}
                      </option>
                    </select></label
                  >
                </div></template
              >
            </div>
            <p v-if="!directory[active].length" class="empty">
              尚无{{
                tabs.find((t) => t.key === active).label
              }}，可点击下方添加。
            </p>
            <button type="button" class="light" @click="add">
              添加{{ tabs.find((t) => t.key === active).label }}
            </button>
            <div class="admin-save">
              <button :disabled="busy || !dirty">
                {{ busy ? "正在保存…" : "保存全部更改" }}</button
              ><span class="caption">{{
                dirty ? "有未保存更改" : "所有更改已保存"
              }}</span>
            </div>
            <p v-if="status" role="status" class="inline-error">{{ status }}</p>
          </fieldset>
        </form>
      </section>
      <dialog
        ref="refreshDialog"
        class="preview-dialog feedback-dialog"
        aria-labelledby="refresh-title"
      >
        <h2 id="refresh-title">放弃未保存更改？</h2>
        <p>刷新将重新读取服务器名单。</p>
        <div class="actions">
          <button
            @click="
              refreshDialog.close();
              refresh();
            "
          >
            放弃并刷新</button
          ><button class="light" @click="refreshDialog.close()">
            继续编辑
          </button>
        </div>
      </dialog>
      <dialog
        ref="importDialog"
        class="preview-dialog"
        aria-labelledby="import-title"
      >
        <h2 id="import-title">批量导入预览</h2>
        <template v-if="importPreview">
          <p>
            新增{{ importPreview.created }}人，更新{{
              importPreview.updated
            }}人；错误{{ importPreview.errors.length }}行。
          </p>
          <p
            v-for="error in importPreview.errors.slice(0, 100)"
            :key="`${error.line}-${error.message}`"
            class="inline-error"
          >
            第{{ error.line }}行：{{ error.message }}
          </p>
          <p v-if="importPreview.errors.length">
            请关闭预览并修正全部错误。此次不会导入任何人员。
          </p>
          <div class="import-table-wrap">
            <table class="import-table">
              <thead>
                <tr>
                  <th>学号</th>
                  <th>班级</th>
                  <th>学院</th>
                  <th>专业</th>
                  <th>年级</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="student in importPreview.students.slice(0, 100)"
                  :key="student.user_id"
                >
                  <td>{{ student.user_id }}</td>
                  <td>{{ student.class_id }}</td>
                  <td>{{ student.college }}</td>
                  <td>{{ student.major }}</td>
                  <td>{{ student.grade }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-if="importPreview.students.length > 100" class="caption">
            预览显示前100人，确认将导入全部{{
              importPreview.students.length
            }}人。
          </p>
          <div class="actions">
            <button
              :disabled="busy || importPreview.errors.length > 0"
              @click="commitStudents"
            >
              确认导入</button
            ><button
              class="light"
              :disabled="busy"
              @click="importDialog.close()"
            >
              返回修改
            </button>
          </div>
        </template>
      </dialog>
    </template>
  </main>
</template>
