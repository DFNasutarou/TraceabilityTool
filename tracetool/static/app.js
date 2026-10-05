import { api, toast, toasts } from "./api.js";
import { route, href } from "./router.js";
import Dashboard from "./views/dashboard.js";
import DocSettings from "./views/docsettings.js";
import ImportWizard from "./views/import.js";
import ItemsView from "./views/items.js";
import VersionsView from "./views/versions.js";
import TraceView from "./views/trace.js";
import SideView from "./views/side.js";

const { createApp, computed, ref, onMounted } = Vue;

const App = {
  components: { Dashboard, DocSettings, ImportWizard, ItemsView, VersionsView, TraceView, SideView },
  setup() {
    const view = computed(() => {
      const p = route.parts;
      if (p[0] === "documents" && p[1] === "new") return { name: "DocSettings", props: { docId: null } };
      if (p[0] === "documents" && p[1]) {
        const docId = Number(p[1]);
        const sub = { settings: "DocSettings", import: "ImportWizard", items: "ItemsView", versions: "VersionsView", side: "SideView" }[p[2]];
        if (sub) return { name: sub, props: { docId } };
      }
      if (p[0] === "trace") return { name: "TraceView", props: { relId: p[1] ? Number(p[1]) : null } };
      return { name: "Dashboard", props: {} };
    });
    // 画面を切り替えたときに状態を作り直すためのキー
    const viewKey = computed(() => route.path);

    // データの保存先（ツールのフォルダとは別の場所。ツールを差し替えてもデータは残る）
    const dataDir = ref("");
    onMounted(async () => {
      dataDir.value = (await api.get("/api/info")).data_dir || "";
    });
    async function openDataDir() {
      await api.post("/api/open-data-dir");
      toast(`保存先フォルダを開きました: ${dataDir.value}`);
    }
    return { view, viewKey, toasts, href, route, dataDir, openDataDir };
  },
  template: `
    <header class="topbar">
      <a class="brand" :href="href('/')">トレーサビリティツール</a>
      <nav>
        <a :href="href('/')" :class="{active: route.parts.length === 0}">文書一覧</a>
        <a :href="href('/trace')" :class="{active: route.parts[0] === 'trace'}">トレース状況</a>
      </nav>
      <span class="spacer"></span>
      <button v-if="dataDir" class="btn small data-dir-btn" @click="openDataDir" :title="'データの保存先: ' + dataDir">
        保存先フォルダを開く
      </button>
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
