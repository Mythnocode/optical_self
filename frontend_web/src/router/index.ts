import { createRouter, createWebHashHistory } from "vue-router";

export const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    {
      path: "/",
      name: "home",
      component: () => import("../pages/HomePage.vue"),
    },
    {
      path: "/teaching-three",
      name: "teaching-three",
      component: () => import("../pages/TeachingThreePoc.vue"),
    },
    {
      path: "/tasks",
      name: "tasks",
      component: () => import("../pages/JobsPage.vue"),
    },
    {
      path: "/workbench/:module/:kind?",
      name: "workbench",
      component: () => import("../pages/WorkbenchPage.vue"),
    },
  ],
});
