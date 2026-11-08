<script setup>
import { ref, watch } from "vue";
import { api } from "../api.js";
const props = defineProps({
  modelValue: String,
  label: String,
  initialLabel: String,
  placeholder: String,
  kind: { default: "classes" },
  disabled: Boolean,
  required: Boolean,
  classId: String,
});
const emit = defineEmits(["update:modelValue"]);
const query = ref(""),
  page = ref(1),
  pages = ref(1),
  options = ref([]),
  busy = ref(false),
  error = ref("");
const selectedLabel = ref("");
const selectedValue = ref("");
let generation = 0;
async function load() {
  const version = ++generation;
  busy.value = true;
  error.value = "";
  try {
    const params = new URLSearchParams({
      page: String(page.value),
      q: query.value,
    });
    if (props.kind === "classes") params.set("view", "classes");
    if (props.kind === "majors" && props.classId)
      params.set("class_id", props.classId);
    const result = await api(
      `${props.kind === "classes" ? "admin/directory" : "admin/majors"}?${params}`,
    );
    if (version !== generation) return;
    page.value = result.page;
    pages.value = result.pages;
    options.value =
      props.kind === "classes"
        ? result.directory.classes.map((row) => ({
            value: row.class_id,
            label: `${row.name} · ${row.grade} · ${row.department}`,
          }))
        : result.items.map((value) => ({ value, label: value }));
  } catch (e) {
    if (version === generation) error.value = e.message;
  } finally {
    if (version === generation) busy.value = false;
  }
}
function choose(event) {
  selectedValue.value = event.target.value;
  selectedLabel.value =
    options.value.find((row) => row.value === event.target.value)?.label || "";
  emit("update:modelValue", event.target.value);
}
function search() {
  page.value = 1;
  load();
}
watch(() => props.classId, search);
watch(
  () => props.modelValue,
  () => {
    if (props.modelValue !== selectedValue.value) selectedLabel.value = "";
  },
);
load();
</script>
<template>
  <div class="directory-picker">
    <label
      >{{ label
      }}<select
        :value="modelValue || ''"
        :disabled="disabled || busy"
        :required="required"
        @change="choose"
      >
        <option value="">
          {{ placeholder || (required ? "请选择班级" : "全部") }}
        </option>
        <option
          v-if="modelValue && !options.some((row) => row.value === modelValue)"
          :value="modelValue"
        >
          {{
            selectedLabel ||
            initialLabel ||
            (kind === "majors" ? modelValue : "已选班级")
          }}
        </option>
        <option v-for="row in options" :key="row.value" :value="row.value">
          {{ row.label }}
        </option>
      </select></label
    >
    <details>
      <summary>搜索 / 翻页选择</summary>
      <div class="actions">
        <input
          v-model="query"
          :aria-label="'搜索' + label"
          :disabled="disabled"
          placeholder="输入名称搜索"
          @keydown.enter.prevent="search"
        /><button
          type="button"
          class="light"
          :disabled="disabled || busy"
          @click="search"
        >
          搜索
        </button>
      </div>
      <div class="actions">
        <button
          type="button"
          class="light"
          :disabled="disabled || busy || page === 1"
          @click="
            page--;
            load();
          "
        >
          上一页</button
        ><span>{{ page }} / {{ pages }}</span
        ><button
          type="button"
          class="light"
          :disabled="disabled || busy || page === pages"
          @click="
            page++;
            load();
          "
        >
          下一页
        </button>
      </div>
    </details>
    <p v-if="error" class="inline-error" role="alert">{{ error }}</p>
  </div>
</template>
