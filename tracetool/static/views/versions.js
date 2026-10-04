import { api, download, fmtDate, fmtValue, toast } from "../api.js";
import { route, href, replaceQuery } from "../router.js";
import { diffSegments } from "../textdiff.js";

const { ref, computed, onMounted } = Vue;

const COLUMN_CHANGE = { added: "列の追加", removed: "列の削除", renamed: "列名の変更", type_changed: "型の変更" };

export default {
  props: { docId: { type: Number, required: true } },
  setup(props) {
    const doc = ref(null);
    const versions = ref([]);
    const fromId = ref("");
    const toId = ref("");
    const diff = ref(null);
    const tab = ref("changed");

    async function loadVersions() {
      versions.value = await api.get(`/api/documents/${props.docId}/versions`);
    }

    onMounted(async () => {
      doc.value = await api.get(`/api/documents/${props.docId}`);
      await loadVersions();
      // 既定は「1 つ前の版 → 最新版」
      fromId.value = Number(route.query.from) || versions.value[1]?.id || "";
      toId.value = Number(route.query.to) || versions.value[0]?.id || "";
      if (fromId.value && toId.value) runDiff();
    });

    async function runDiff() {
      if (!fromId.value || !toId.value) return;
      replaceQuery({ from: fromId.value, to: toId.value });
      const d = await api.get("/api/diff", { from: fromId.value, to: toId.value });
      // 変わった部分を文字単位でハイライトするため、セルごとに差分を求めておく
      for (const it of d.changed) for (const c of it.cells) c.segs = diffSegments(fmtValue(c.old), fmtValue(c.new));
      diff.value = d;
      tab.value = diff.value.changed.length ? "changed" : diff.value.added.length ? "added" : "removed";
    }

    async function removeVersion(v) {
      const latest = versions.value[0]?.id === v.id;
      const msg = `v${v.version_no}（${v.label || v.source_filename}）を削除します。元に戻せません。` +
        (latest ? "\n最新版を削除すると、1 つ前の版が最新版になり、自動リンクが作り直されます。" : "") + "\nよろしいですか？";
      if (!confirm(msg)) return;
      await api.del(`/api/versions/${v.id}`);
      toast("版を削除しました");
      diff.value = null;
      await loadVersions();
    }

    const name = (key) => diff.value?.column_names[key] || key;
    const summary = computed(() =>
      diff.value ? { changed: diff.value.changed.length, added: diff.value.added.length, removed: diff.value.removed.length } : null
    );

    return { doc, versions, fromId, toId, diff, tab, summary, COLUMN_CHANGE, runDiff, removeVersion, name, fmtDate, fmtValue, href, download };
  },
  template: `
    <section class="page" v-if="doc">
      <div class="page-head">
        <h1>版・差分: {{ doc.name }}</h1>
        <div class="actions">
          <a class="btn" :href="href('/documents/' + docId + '/items')">項目一覧</a>
          <a class="btn" :href="href('/documents/' + docId + '/import')">取り込み</a>
        </div>
      </div>

      <table class="grid">
        <thead><tr><th>版</th><th>ラベル</th><th>取り込み日時</th><th>元ファイル</th><th class="num">行数</th><th></th></tr></thead>
        <tbody>
          <tr v-for="(v, i) in versions" :key="v.id">
            <td>v{{ v.version_no }} <span v-if="i === 0" class="badge ok">最新</span></td>
            <td>{{ v.label }}</td>
            <td>{{ fmtDate(v.imported_at) }}</td>
            <td>{{ v.source_filename }}</td>
            <td class="num">{{ v.row_count }}</td>
            <td class="row-actions">
              <a class="btn small" :href="href('/documents/' + docId + '/items', {version: v.id})">閲覧</a>
              <button class="btn small danger-ghost" @click="removeVersion(v)">削除</button>
            </td>
          </tr>
        </tbody>
      </table>

      <h2>差分</h2>
      <div class="inline-form" v-if="versions.length >= 2">
        <label>比較元（旧）
          <select v-model="fromId"><option v-for="v in versions" :key="v.id" :value="v.id">v{{ v.version_no }} {{ v.label }}</option></select>
        </label>
        <span>→</span>
        <label>比較先（新）
          <select v-model="toId"><option v-for="v in versions" :key="v.id" :value="v.id">v{{ v.version_no }} {{ v.label }}</option></select>
        </label>
        <button class="btn primary" @click="runDiff">比較</button>
        <template v-if="diff">
          <!-- 出力は、セレクトの現在値ではなく表示中の差分の版を使う -->
          <button class="btn" @click="download('/api/export/diff', {from: diff.from.id, to: diff.to.id, format: 'xlsx'})">Excel 出力</button>
          <button class="btn" @click="download('/api/export/diff', {from: diff.from.id, to: diff.to.id, format: 'csv'})">CSV 出力</button>
        </template>
      </div>
      <p v-else class="empty">差分を見るには版が 2 つ以上必要です。</p>

      <template v-if="diff">
        <div v-if="diff.columns.length" class="card">
          <h3>列の変更</h3>
          <ul>
            <li v-for="c in diff.columns" :key="c.key + c.kind">
              {{ COLUMN_CHANGE[c.kind] }}: <b>{{ c.name }}</b>
              <span v-if="c.kind === 'renamed'">（旧: {{ c.old_name }}）</span>
              <span v-if="c.kind === 'type_changed'">（{{ c.old_type }} → {{ c.new_type }}）</span>
            </li>
          </ul>
        </div>

        <div class="tabs">
          <button :class="{active: tab === 'changed'}" @click="tab = 'changed'">変更（{{ summary.changed }}）</button>
          <button :class="{active: tab === 'added'}" @click="tab = 'added'">追加（{{ summary.added }}）</button>
          <button :class="{active: tab === 'removed'}" @click="tab = 'removed'">削除（{{ summary.removed }}）</button>
          <span class="sub tab-note">変更なし {{ diff.unchanged }} 件</span>
        </div>

        <table v-if="tab === 'changed'" class="grid compact">
          <thead><tr><th>ID</th><th>列</th><th>変更前</th><th>変更後</th></tr></thead>
          <tbody>
            <template v-for="it in diff.changed" :key="it.item_id">
              <tr v-for="(c, j) in it.cells" :key="c.key">
                <td v-if="j === 0" :rowspan="it.cells.length" class="idcell">
                  <a :href="href('/documents/' + docId + '/items', {version: diff.to.id, item: it.item_id})">{{ it.item_id }}</a>
                </td>
                <td class="nowrap">{{ c.name }}</td>
                <td class="pre del"><span v-for="(s, k) in c.segs.old" :key="k" :class="{'hl-del': s.changed}">{{ s.text }}</span></td>
                <td class="pre ins"><span v-for="(s, k) in c.segs.new" :key="k" :class="{'hl-ins': s.changed}">{{ s.text }}</span></td>
              </tr>
            </template>
          </tbody>
        </table>

        <table v-if="tab !== 'changed'" class="grid compact">
          <thead><tr><th>ID</th><th v-for="k in diff.column_order" :key="k">{{ name(k) }}</th></tr></thead>
          <tbody>
            <tr v-for="it in (tab === 'added' ? diff.added : diff.removed)" :key="it.item_id" :class="tab === 'added' ? 'ins' : 'del'">
              <td class="idcell">{{ it.item_id }}</td>
              <td v-for="k in diff.column_order" :key="k">{{ fmtValue(it.data[k]) }}</td>
            </tr>
          </tbody>
        </table>
      </template>
    </section>
  `,
};
