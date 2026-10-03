import { toasts } from "./api.js";
import { route, href } from "./router.js";
import Dashboard from "./views/dashboard.js";
import DocSettings from "./views/docsettings.js";
import ImportWizard from "./views/import.js";
import ItemsView from "./views/items.js";
import VersionsView from "./views/versions.js";
import TraceView from "./views/trace.js";

const { createApp, computed } = Vue;

const App = {
  components: { Dashboard, DocSettings, ImportWizard, ItemsView, VersionsView, TraceView },
  setup() {
    const view = computed(() => {
      const p = route.parts;
      if (p[0] === "documents" && p[1] === "new") return { name: "DocSettings", props: { docId: null } };
      if (p[0] === "documents" && p[1]) {
        const docId = Number(p[1]);
        const sub = { settings: "DocSettings", import: "ImportWizard", items: "ItemsView", versions: "VersionsView" }[p[2]];
        if (sub) return { name: sub, props: { docId } };
      }
      if (p[0] === "trace") return { name: "TraceView", props: { relId: p[1] ? Number(p[1]) : null } };
      return { name: "Dashboard", props: {} };
    });
    // 画面を切り替えたときに状態を作り直すためのキー
    const viewKey = computed(() => route.path);
    return { view, viewKey, toasts, href, route };
  },
  template: `
    <header class="topbar">
      <a class="brand" :href="href('/')">トレーサビリティツール</a>
      <nav>
        <a :href="href('/')" :class="{active: route.parts.length === 0}">文書一覧</a>
        <a :href="href('/trace')" :class="{active: route.parts[0] === 'trace'}">トレース状況</a>
      </nav>
    </header>
    <main class="main">
      <component :is="view.name" v-bind="view.props" :key="viewKey" />
    </main>
    <div class="toasts">
      <div v-for="t in toasts" :key="t.id" class="toast" :class="t.kind">{{ t.message }}</div>
    </div>
  `,
};

createApp(App).mount("#app");
