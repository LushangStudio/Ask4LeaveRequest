import { createApp, defineAsyncComponent } from "vue";
import App from "./App.vue";
import "./style.css";

const page = window.location.pathname.endsWith("/class-management/")
  ? defineAsyncComponent(() => import("./ClassManagement.vue"))
  : App;
createApp(page).mount("#app");
