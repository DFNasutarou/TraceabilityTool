import { api, download, fmtDate, fmtPct, toast } from "../api.js";
import { href } from "../router.js";

const { ref, onMounted } = Vue;

export default {
  setup() {
    const docs = ref([]);
    const relations = ref([]);
    const newRel = ref({ upper: "", lower: "" });
    const loading = ref(true);
    const loaded = ref(false); // 初回の読み込みが終わったか

    async function load() {
      loading.value = true;
      try {
        [docs.value, relations.value] = await Promise.all([api.get("/api/documents"), api.get("/api/relations")]);
        loaded.value = true;
      } finally {
        loading.value = false;
      }
    }

    async function addRelation() {
      if (!newRel.value.upper || !newRel.value.lower) return;
      await api.post("/api/relations", { upper_doc_id: newRel.value.upper, lower_doc_id: newRel.value.lower });
      newRel.value = { upper: "", lower: "" };
      toast("トレース関係を追加しました");
      load();
    }

    async function deleteRelation(r) {
      if (!confirm(`「${r.upper_name} → ${r.lower_name}」の関係を削除します。\nこの関係のリンク（手動リンクを含む）もすべて削除されます。よろしいですか？`)) return;
      await api.del(`/api/relations/${r.relation.id}`);
      toast("トレース関係を削除しました");
      load();
    }

    const dataDir = ref("");
    onMounted(load);
    onMounted(async () => {
      dataDir.value = (await api.get("/api/info")).data_dir || "";
    });
    async function openDataDir() {
      await api.post("/api/open-data-dir");
      toast(`保存先フォルダを開きました: ${dataDir.value}`);
    }
    return { dataDir, openDataDir, docs, relations, newRel, loading, loaded, addRelation, deleteRelation, href, fmtDate, fmtPct, download };
  },
  template: `
    <section class="page">
      <div class="page-head">
        <h1>文書一覧</h1>
        <div class="actions"><a class="btn primary" :href="href('/documents/new')">＋ 文書を追加</a></div>
      </div>

      <p v-if="!loaded" class="sub">読み込み中…</p>
      <p v-else-if="docs.length === 0" class="empty">
        文書がまだありません。「文書を追加」から仕様書・設計書を登録し、表を取り込んでください。
      </p>
      <table v-else class="grid">
        <thead>
          <tr>
            <th>文書</th><th>最新版</th><th class="num">項目数</th>
            <th class="num" title="上位文書があるのに、上位へのリンクが無い項目">上位なし</th>
            <th class="num" title="下位文書があるのに、下位へのリンクが無い項目">下位なし</th>
            <th class="num">要確認</th><th class="num">リンク切れ</th><th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="d in docs" :key="d.id">
            <td>
              <a v-if="d.latest" :href="href('/documents/' + d.id + '/items')"><b>{{ d.name }}</b></a>
              <b v-else>{{ d.name }}</b>
              <div class="sub">{{ d.description }}</div>
            </td>
            <td>
              <template v-if="d.latest">
                v{{ d.latest.version_no }} <span class="sub">{{ d.latest.label }}</span>
                <div class="sub">{{ fmtDate(d.latest.imported_at) }}</div>
              </template>
              <span v-else class="sub">未取り込み</span>
            </td>
            <td class="num">{{ d.latest ? d.latest.row_count : '' }}</td>
            <td class="num"><a v-if="d.trace && d.trace.no_upper" class="warn-text" :href="href('/documents/' + d.id + '/items', {trace: 'no_upper'})">{{ d.trace.no_upper }}</a><span v-else-if="d.trace">0</span></td>
            <td class="num"><a v-if="d.trace && d.trace.no_lower" class="warn-text" :href="href('/documents/' + d.id + '/items', {trace: 'no_lower'})">{{ d.trace.no_lower }}</a><span v-else-if="d.trace">0</span></td>
            <td class="num"><a v-if="d.trace && d.trace.suspect_items" class="warn-text" :href="href('/documents/' + d.id + '/items', {trace: 'suspect'})">{{ d.trace.suspect_items }}</a><span v-else-if="d.trace">0</span></td>
            <td class="num"><a v-if="d.trace && d.trace.broken_items" class="err-text" :href="href('/documents/' + d.id + '/items', {trace: 'broken'})">{{ d.trace.broken_items }}</a><span v-else-if="d.trace">0</span></td>
            <td class="row-actions">
              <a class="btn" :href="href('/documents/' + d.id + '/import')">取り込み</a>
              <a class="btn" :href="href('/documents/' + d.id + '/versions')" :class="{disabled: !d.version_count}">版・差分</a>
              <a class="btn" :href="href('/documents/' + d.id + '/settings')">設定</a>
            </td>
          </tr>
        </tbody>
      </table>
    </section>

    <section class="page">
      <div class="page-head">
        <h2>トレース関係（上位 → 下位）</h2>
        <div class="actions" v-if="relations.length">
          <button class="btn" @click="download('/api/export/untraced', {format: 'xlsx'})">未トレース一覧（全関係）Excel</button>
          <button class="btn" @click="download('/api/export/untraced', {format: 'csv'})">CSV</button>
        </div>
      </div>
      <p v-if="!loaded" class="sub">読み込み中…</p>
      <table class="grid relations-table" v-else-if="relations.length">
        <thead>
          <tr>
            <th>関係（上位 → 下位）</th>
            <th class="num">上位の網羅率</th><th class="num">下位の網羅率</th>
            <th class="num">リンク</th><th class="num">要確認</th><th class="num">リンク切れ</th><th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in relations" :key="r.relation.id">
            <td>
              <a :href="href('/trace/' + r.relation.id)" title="トレース状況を開く"><b>{{ r.upper_name }} → {{ r.lower_name }}</b></a>
            </td>
            <td class="num">
              {{ fmtPct(r.upper_coverage) }}
              <div class="meter"><span :style="{width: ((r.upper_coverage ?? 0) * 100) + '%'}"></span></div>
              <div class="sub">下位なし {{ r.upper_untraced }}</div>
            </td>
            <td class="num">
              {{ fmtPct(r.lower_coverage) }}
              <div class="meter"><span :style="{width: ((r.lower_coverage ?? 0) * 100) + '%'}"></span></div>
              <div class="sub">上位なし {{ r.lower_untraced }}</div>
            </td>
            <td class="num">{{ r.links }}</td>
            <td class="num" :class="{'warn-text': r.suspect}">{{ r.suspect }}</td>
            <td class="num" :class="{'err-text': r.broken}">{{ r.broken }}</td>
            <td class="row-actions">
              <a class="btn" :href="href('/trace/' + r.relation.id)">詳細</a>
              <button class="btn danger-ghost" @click="deleteRelation(r)">削除</button>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-else-if="docs.length >= 2" class="empty">トレース関係がありません。下のフォームで「上位文書 → 下位文書」を登録してください。</p>
      <p v-else class="empty">トレース関係がありません。文書を 2 つ以上登録すると、ここで「上位文書 → 下位文書」の関係を登録できます（取り込み画面で参照先を選んだときにも登録できます）。</p>

      <div class="inline-form" v-if="docs.length >= 2">
        <label>上位
          <select v-model="newRel.upper"><option value="">選択…</option><option v-for="d in docs" :key="d.id" :value="d.id">{{ d.name }}</option></select>
        </label>
        <span>→</span>
        <label>下位
          <select v-model="newRel.lower"><option value="">選択…</option><option v-for="d in docs" :key="d.id" :value="d.id" :disabled="d.id === newRel.upper">{{ d.name }}</option></select>
        </label>
        <button class="btn primary" :disabled="!newRel.upper || !newRel.lower" @click="addRelation">関係を追加</button>
      </div>

      <div v-if="dataDir" class="data-dir">
        <span class="sub">データの保存先（ツールのフォルダとは別の場所です。ツールを差し替えてもデータは残ります）:</span>
        <code>{{ dataDir }}</code>
        <button class="btn small" @click="openDataDir">フォルダを開く</button>
      </div>
    </section>
  `,
};
