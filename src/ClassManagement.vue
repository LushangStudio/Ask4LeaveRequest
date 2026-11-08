<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { api, apiUrl } from "./api.js";
import { directoryDelta } from "./directory-delta.js";
import DirectoryPicker from "./components/DirectoryPicker.vue";
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
const importClass = ref("");
const importText = ref(""),
  importPreview = ref(null),
  importDialog = ref(null);
const dirty = computed(
  () => directory.value && JSON.stringify(directory.value) !== original.value,
);
const workspaceUrl = new URL("../", window.location.href).href;
const studentClass = ref("");
const studentMajor = ref("");
const studentPage = ref(1);
const studentDialog = ref(null);
const editingStudent = ref(null);
const studentDraft = ref({ user_id: "", major: "", class_id: "" });
const counts = ref({ classes: 0, students: 0 });
const pageMeta = ref({ total: 0, pages: 1, page: 1 });
const studentPages = computed(() => pageMeta.value.pages);
const classPages = computed(() => pageMeta.value.pages);
const visibleStudents = computed(() => directory.value?.students || []);
const visibleClasses = computed(() => directory.value?.classes || []);
watch([studentClass, studentMajor], () => {
  if (studentPage.value !== 1) studentPage.value = 1;
  else refresh();
});
watch([active, studentPage], () => refresh());
function editStudent(row = null) {
  editingStudent.value = row;
  studentDraft.value = row
    ? { ...row }
    : {
        user_id: "",
        major: studentMajor.value,
        class_id: studentClass.value || "",
      };
  studentDialog.value.showModal();
}
async function applyStudent() {
  if (editingStudent.value)
    Object.assign(editingStudent.value, studentDraft.value, {
      class_label:
        studentDraft.value.class_id === editingStudent.value.class_id
          ? editingStudent.value.class_label
          : "待保存班级",
    });
  else {
    directory.value.students.push({ ...studentDraft.value });
  }
  status.value = "学生编辑已加入待保存更改，请点击保存更改。";
  studentDialog.value.close();
}
function removeStudent(row) {
  directory.value.students.splice(directory.value.students.indexOf(row), 1);
  status.value = "";
}
const tabs = [
  { key: "classes", label: "班级" },
  { key: "students", label: "学生" },
];
function accept(result) {
  directory.value = result.directory;
  directory.value.classes.forEach(
    (c) =>
      (c.counselor_ids_text = directory.value.class_counselors
        .filter((r) => r.class_id === c.class_id)
        .map((r) => r.user_id)
        .join(", ")),
  );
  counts.value = result.counts;
  pageMeta.value = {
    total: result.total,
    pages: result.pages,
    page: result.page,
  };
  if (active.value === "classes") classPage.value = result.page;
  else studentPage.value = result.page;
  revision.value = result.revision;
  original.value = JSON.stringify(directory.value);
}
let loadGeneration = 0;
async function refresh() {
  const generation = ++loadGeneration;
  busy.value = true;
  try {
    const params = new URLSearchParams({
      view: active.value,
      page: String(
        active.value === "classes" ? classPage.value : studentPage.value,
      ),
    });
    if (active.value === "students") {
      if (studentClass.value) params.set("class_id", studentClass.value);
      if (studentMajor.value) params.set("major", studentMajor.value);
    }
    const result = await api(`admin/directory?${params}`);
    if (generation === loadGeneration) accept(result);
  } catch (e) {
    if (generation === loadGeneration) message.value = e.message;
  } finally {
    if (generation === loadGeneration) busy.value = false;
  }
}
function requestRefresh() {
  if (dirty.value) refreshDialog.value.showModal();
  else refresh();
}
const classDialog = ref(null);
const editingClass = ref(null);
const classDraft = ref({});
const classPage = ref(1);
watch(classPage, () => refresh());
function editClass(row = null) {
  editingClass.value = row;
  classDraft.value = row
    ? { ...row }
    : {
        class_id: crypto.randomUUID(),
        name: "",
        grade: "",
        department: "",
        counselor_ids_text: "",
      };
  classDialog.value.showModal();
}
function applyClass() {
  if (editingClass.value) Object.assign(editingClass.value, classDraft.value);
  else {
    directory.value.classes.push({ ...classDraft.value });
  }
  status.value = "班级编辑已加入待保存更改，请点击保存更改。";
  classDialog.value.close();
}
function add() {
  if (active.value === "students") editStudent();
  else editClass();
}
function removeClass(row) {
  directory.value.classes.splice(directory.value.classes.indexOf(row), 1);
  status.value = "";
}
async function save() {
  busy.value = true;
  status.value = "";
  try {
    const payload = directoryDelta(
      JSON.parse(original.value),
      directory.value,
      revision.value,
    );
    const saved = await api("admin/directory", payload, "PATCH");
    revision.value = saved.revision;
    original.value = JSON.stringify(directory.value);
    await refresh();
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
      class_id: importClass.value,
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
      class_id: importClass.value,
      revision: revision.value,
    });
    revision.value = result.revision;
    await refresh();
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
              :disabled="busy || dirty"
              @click="active = tab.key"
            >
              {{ tab.label }} · {{ counts[tab.key] }}
            </button>
          </div>
          <button class="light" :disabled="busy" @click="requestRefresh">
            刷新名单
          </button>
        </div>
        <form @submit.prevent="save">
          <fieldset class="form-fields" :disabled="busy">
            <details v-if="active === 'students'" class="item student-import">
              <summary>批量导入学生</summary>
              <p class="caption">
                先选择导入班级，每行一人：学号,专业。使用英文逗号；同学号更新专业及所属班级。先保存当前编辑，再导入。
              </p>
              <DirectoryPicker
                v-model="importClass"
                label="导入班级"
                placeholder="请选择班级"
                :disabled="busy || dirty"
                @update:model-value="importPreview = null"
              />
              <label
                >学生批量名单<textarea
                  v-model="importText"
                  rows="6"
                  placeholder="STUDENT001,工商管理"
                  @input="importPreview = null"
                ></textarea>
              </label>
              <button
                type="button"
                :disabled="busy || dirty || !importClass || !importText.trim()"
                @click="previewStudents"
              >
                校验并预览导入
              </button>
            </details>
            <p class="caption">
              {{
                active === "classes"
                  ? "填写班级名称、年级和院系；多个辅导员学工号用英文逗号分隔。"
                  : "学工号必须与UIS一致。兼任学生和辅导员时，两处填写相同学工号；师生姓名均从UIS登录获取。"
              }}
            </p>
            <section v-if="active === 'classes'" aria-label="班级管理列表">
              <p class="caption">共 {{ counts.classes }} 个班级 · 每页 50 个</p>
              <div class="student-table-wrap">
                <table class="student-table">
                  <thead>
                    <tr>
                      <th scope="col">班级名称</th>
                      <th scope="col">年级</th>
                      <th scope="col">院系</th>
                      <th scope="col">辅导员学工号</th>
                      <th scope="col">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="row in visibleClasses" :key="row.class_id">
                      <td>{{ row.name }}</td>
                      <td>{{ row.grade }}</td>
                      <td>{{ row.department }}</td>
                      <td>{{ row.counselor_ids_text }}</td>
                      <td class="student-row-actions">
                        <button
                          type="button"
                          class="light"
                          :aria-label="'编辑班级 ' + row.name"
                          @click="editClass(row)"
                        >
                          编辑</button
                        ><button
                          type="button"
                          class="danger"
                          :aria-label="'删除班级 ' + row.name"
                          @click="removeClass(row)"
                        >
                          删除
                        </button>
                      </td>
                    </tr>
                    <tr v-if="!visibleClasses.length">
                      <td colspan="5" class="empty">尚无班级</td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <nav class="student-pagination" aria-label="班级名单分页">
                <button
                  type="button"
                  class="light"
                  :disabled="busy || dirty || classPage === 1"
                  @click="classPage--"
                >
                  上一页
                </button>
                <label
                  >页码<select
                    :disabled="busy || dirty"
                    :value="pageMeta.page"
                    @change="classPage = Number($event.target.value)"
                  >
                    <option
                      v-for="page in classPages"
                      :key="page"
                      :value="page"
                    >
                      第 {{ page }} / {{ classPages }} 页
                    </option>
                  </select></label
                >
                <button
                  type="button"
                  class="light"
                  :disabled="busy || dirty || classPage === classPages"
                  @click="classPage++"
                >
                  下一页
                </button>
              </nav>
            </section>
            <section v-else class="student-directory" aria-label="学生管理列表">
              <div class="student-filters">
                <DirectoryPicker
                  v-model="studentClass"
                  label="按班级筛选"
                  :disabled="busy || dirty"
                />
                <DirectoryPicker
                  v-model="studentMajor"
                  label="按专业筛选"
                  kind="majors"
                  :class-id="studentClass"
                  :disabled="busy || dirty"
                />
                <button
                  type="button"
                  class="light"
                  :disabled="busy || dirty"
                  @click="
                    studentClass = '';
                    studentMajor = '';
                  "
                >
                  清除筛选
                </button>
              </div>
              <p class="caption" role="status">
                共 {{ counts.students }} 人 · 筛选结果 {{ pageMeta.total }} 人 ·
                每页 50 人
              </p>
              <div class="student-table-wrap">
                <table class="student-table">
                  <thead>
                    <tr>
                      <th scope="col">学号</th>
                      <th scope="col">专业</th>
                      <th scope="col">班级</th>
                      <th scope="col">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="(row, index) in visibleStudents" :key="index">
                      <td>{{ row.user_id || "未填写" }}</td>
                      <td>{{ row.major || "未填写" }}</td>
                      <td>
                        {{ row.class_label || "待保存班级" }}
                      </td>
                      <td class="student-row-actions">
                        <button
                          type="button"
                          class="light"
                          :aria-label="'编辑学生 ' + row.user_id"
                          @click="editStudent(row)"
                        >
                          编辑</button
                        ><button
                          type="button"
                          class="danger"
                          :aria-label="'删除学生 ' + row.user_id"
                          @click="removeStudent(row)"
                        >
                          删除
                        </button>
                      </td>
                    </tr>
                    <tr v-if="!visibleStudents.length">
                      <td colspan="4" class="empty">没有符合条件的学生</td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <nav class="student-pagination" aria-label="学生名单分页">
                <button
                  type="button"
                  class="light"
                  :disabled="busy || dirty || studentPage === 1"
                  @click="studentPage--"
                >
                  上一页
                </button>
                <label
                  >页码<select
                    :disabled="busy || dirty"
                    :value="pageMeta.page"
                    @change="studentPage = Number($event.target.value)"
                  >
                    <option
                      v-for="page in studentPages"
                      :key="page"
                      :value="page"
                    >
                      第 {{ page }} / {{ studentPages }} 页
                    </option>
                  </select></label
                >
                <button
                  type="button"
                  class="light"
                  :disabled="busy || dirty || studentPage === studentPages"
                  @click="studentPage++"
                >
                  下一页
                </button>
              </nav>
            </section>
            <p v-if="!directory[active].length" class="empty">
              尚无{{
                tabs.find((t) => t.key === active).label
              }}，可点击下方添加。
            </p>
            <button type="button" class="light" @click="add">
              添加{{ tabs.find((t) => t.key === active).label }}
            </button>
            <p v-if="dirty" class="caption">
              请先保存当前页更改，再筛选、切换列表或翻页。
            </p>
            <div class="admin-save">
              <button :disabled="busy || !dirty">
                {{ busy ? "正在保存…" : "保存更改" }}</button
              ><span class="caption">{{
                dirty ? "有未保存更改" : "所有更改已保存"
              }}</span>
            </div>
            <p v-if="status" role="status" class="inline-error">{{ status }}</p>
          </fieldset>
        </form>
      </section>
      <dialog
        ref="classDialog"
        class="preview-dialog feedback-dialog"
        aria-labelledby="class-edit-title"
      >
        <h2 id="class-edit-title">
          {{ editingClass ? "编辑班级" : "添加班级" }}
        </h2>
        <form @submit.prevent="applyClass">
          <label
            >班级名称<input
              v-model.trim="classDraft.name"
              required
              maxlength="80"
          /></label>
          <label
            >年级<input v-model.trim="classDraft.grade" required maxlength="20"
          /></label>
          <label
            >院系<input
              v-model.trim="classDraft.department"
              required
              maxlength="80"
          /></label>
          <label
            >辅导员学工号（英文逗号分隔）<input
              v-model.trim="classDraft.counselor_ids_text"
              required
              placeholder="例如：STAFF001, STAFF002"
          /></label>
          <p class="caption">确认后请保存更改，才会更新服务器名单。</p>
          <div class="actions">
            <button>确认编辑</button
            ><button type="button" class="light" @click="classDialog.close()">
              取消
            </button>
          </div>
        </form>
      </dialog>
      <dialog
        ref="studentDialog"
        class="preview-dialog feedback-dialog"
        aria-labelledby="student-edit-title"
      >
        <h2 id="student-edit-title">
          {{ editingStudent ? "编辑学生" : "添加学生" }}
        </h2>
        <form @submit.prevent="applyStudent">
          <label
            >学号<input
              v-model.trim="studentDraft.user_id"
              required
              maxlength="40"
          /></label>
          <label
            >专业<input
              v-model.trim="studentDraft.major"
              required
              maxlength="80"
          /></label>
          <DirectoryPicker
            v-model="studentDraft.class_id"
            label="所属班级"
            :initial-label="editingStudent?.class_label"
            required
          />
          <p class="caption">确认后请保存更改，才会更新服务器名单。</p>
          <div class="actions">
            <button>确认编辑</button
            ><button type="button" class="light" @click="studentDialog.close()">
              取消
            </button>
          </div>
        </form>
      </dialog>
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
            }}人；错误{{ importPreview.error_count }}行。
          </p>
          <p
            v-for="error in importPreview.errors"
            :key="`${error.line}-${error.message}`"
            class="inline-error"
          >
            第{{ error.line }}行：{{ error.message }}
          </p>
          <p v-if="importPreview.error_count">
            请关闭预览并修正全部错误。此次不会导入任何人员。
          </p>
          <div class="import-table-wrap">
            <table class="import-table">
              <thead>
                <tr>
                  <th>学号</th>
                  <th>班级</th>
                  <th>专业</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="student in importPreview.students"
                  :key="student.user_id"
                >
                  <td>{{ student.user_id }}</td>
                  <td>所选导入班级</td>
                  <td>{{ student.major }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-if="importPreview.total > 50" class="caption">
            预览显示前50人，确认将导入全部{{ importPreview.total }}人。
          </p>
          <div class="actions">
            <button
              :disabled="busy || importPreview.error_count > 0"
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
