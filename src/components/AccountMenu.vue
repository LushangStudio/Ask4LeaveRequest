<script setup>
import { onBeforeUnmount, onMounted, ref } from "vue";
import { apiUrl } from "../api.js";
defineProps({ user: { type: Object, required: true }, busy: Boolean });
const emit = defineEmits(["logout"]);
const open = ref(false);
const block = ref(null);
const button = ref(null);
function dismiss(event) {
  if (event.type === "keydown" && event.key === "Escape") {
    open.value = false;
    button.value?.focus();
  } else if (
    event.type === "pointerdown" &&
    !block.value?.contains(event.target)
  )
    open.value = false;
}
onMounted(() => {
  document.addEventListener("pointerdown", dismiss);
  document.addEventListener("keydown", dismiss);
});
onBeforeUnmount(() => {
  document.removeEventListener("pointerdown", dismiss);
  document.removeEventListener("keydown", dismiss);
});
</script>
<template>
  <div ref="block" class="account-block">
    <button
      ref="button"
      class="account-trigger"
      type="button"
      aria-label="用户菜单"
      :aria-expanded="open"
      aria-controls="leave-account-menu"
      @click="open = !open"
    >
      <svg
        class="account-icon"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="1.8"
        aria-hidden="true"
      >
        <circle cx="12" cy="8" r="4" />
        <path d="M4 21v-2a8 8 0 0 1 16 0v2" />
      </svg>
      <span class="account-copy"
        ><strong>{{ user.name }}</strong
        ><small
          >{{
            user.user_type || (user.role === "counselor" ? "辅导员" : "学生")
          }}
          · {{ user.id }}</small
        ></span
      ><span class="account-chevron" aria-hidden="true">⌄</span>
    </button>
    <div v-if="open" id="leave-account-menu" class="account-dropdown">
      <form
        v-if="user.auth_provider === 'uis'"
        :action="apiUrl('auth/logout')"
        method="post"
      >
        <button class="danger" type="submit" :disabled="busy">
          退出复旦UIS
        </button>
      </form>
      <button
        v-else
        class="danger"
        type="button"
        :disabled="busy"
        @click="
          open = false;
          emit('logout');
        "
      >
        {{ user.auth_provider === "test" ? "退出测试登录" : "退出登录" }}
      </button>
    </div>
  </div>
</template>
