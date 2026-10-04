import { createPinia } from "pinia";
import { createApp } from "vue";
import App from "./App.vue";
import { router } from "./router/index.js";
import "./styles.css";

const app = createApp(App);
app.config.errorHandler = (error, instance, info) => {
  console.error("Renderer error", error instanceof Error ? error.stack || error.message : String(error), info, instance?.$options.name || "");
};
app.use(createPinia());
app.use(router);
app.mount("#app");
