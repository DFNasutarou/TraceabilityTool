import { api, fmtValue, toast, STATUS_LABEL, ORIGIN_LABEL } from "../api.js";
import { route, href, navigate, replaceQuery } from "../router.js";
import { CellValue, ChoiceFilter, widthStyle, storedFlag } from "./cells.js";
import ItemEditor from "./item-editor.js";

const { ref, computed, watch, onMounted } = Vue;

const PAGE_SIZE = 500;

const TRACE_FILTERS = [
  ["", "すべて"],
  ["no_upper", "上位なし"],
  ["no_lower", "下位なし"],
  ["suspect", "要確認あり"],
  ["broken", "リンク切れあり"],
];

export default {
  components: { CellValue, ChoiceFilter, ItemEditor },
  props: { docId: { type: Number, required: true } },
  setup(props) {
    const doc = ref(null);
    const versions = ref([]);
    const result = ref(null);
    const detail = ref(null);
    const loading = ref(false);
    const search = ref({}); // relation_id -> { q, results }（リンク追加の候補検索）

    const versionId = computed(() => Number(route.query.version) || doc.value?.latest_version_id || null);
    const q = ref(route.query.q || "");
    const trace = ref(route.query.trace || "");
    const invalidOnly = ref(false);
    const filters = ref({});
    const choices = ref({}); // enum・bool の列: 列キー → 選んだ選択肢
    const wrap = storedFlag("itemsWrap", false); // 長い値を折り返して全文を表示する
    const sort = ref("");
    const desc = ref(false);
    const page = ref(1);
    const editing = ref(false); // 編集モード（最新版のみ）

    const columns = computed(() => result.value?.schema.columns || []);
    const isLatest = computed(() => result.value?.is_latest);
    const pages = computed(() => (result.value ? Math.max(1, Math.ceil(result.value.total / result.value.size)) : 1));

    let loadSeq = 0;
    async function load() {
      if (!versionId.value) return;
      const seq = ++loadSeq;
      loading.value = true;
      try {
        const params = { q: q.value, trace: trace.value, sort: sort.value, desc: desc.value ? "true" : "", page: page.value, size: PAGE_SIZE };
        for (const [k, v] of Object.entries(filters.value)) if (v) params["f." + k] = v;
        for (const [k, v] of Object.entries(choices.value)) if (v?.length) params["m." + k] = v;
        if (invalidOnly.value) params["f.__invalid"] = "1";
        const res = await api.get(`/api/versions/${versionId.value}/items`, params);
        // 後から出した要求の結果を、先に出した要求の遅れた応答で上書きしない
        if (seq === loadSeq) result.value = res;
      } finally {
        if (seq === loadSeq) loading.value = false;
      }
    }

    async function loadDetail() {
      const id = route.query.item;
      if (!id || !versionId.value) {
        detail.value = null;
        return;
      }
      try {
        detail.value = await api.get(`/api/versions/${versionId.value}/item`, { id });
      } catch {
        detail.value = null;
        return;
      }
      search.value = Object.fromEntries(detail.value.relations.map((g) => [g.relation_id, { q: "", results: [] }]));
      if (window.matchMedia("(max-width: 900px)").matches) {
        await Vue.nextTick();
        document.querySelector(".split-side")?.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    }

    onMounted(async () => {
      [doc.value, versions.value] = await Promise.all([
        api.get(`/api/documents/${props.docId}`),
        api.get(`/api/documents/${props.docId}/versions`),
      ]);
      await load();
      await loadDetail();
    });

    let timer = null;
    function reloadSoon() {
      clearTimeout(timer);
      timer = setTimeout(() => {
        page.value = 1;
        load();
      }, 250);
    }
    watch([q, filters, choices], reloadSoon, { deep: true });
    watch([trace, invalidOnly], () => {
      page.value = 1;
      replaceQuery({ trace: trace.value });
      load();
    });
    watch(() => route.query.item, loadDetail);
    // ブラウザの戻る・進むなどで query だけが変わった場合も、絞り込みを合わせる
    watch(() => route.query.trace, (v) => {
      if ((v || "") !== trace.value) trace.value = v || "";
    });
    watch(() => route.query.version, () => {
      page.value = 1;
      load();
      loadDetail();
    });

    function setSort(key) {
      if (sort.value === key) desc.value = !desc.value;
      else {
        sort.value = key;
        desc.value = false;
      }
      load();
    }
    function goPage(p) {
      page.value = Math.min(Math.max(1, p), pages.value);
      load();
    }
    function selectItem(id) {
      replaceQuery({ item: id });
    }
    function changeVersion(e) {
      replaceQuery({ version: e.target.value, item: route.query.item });
    }

    // --- リンク操作 ---
    async function findCandidates(group) {
      const s = search.value[group.relation_id];
      s.results = await api.get(`/api/documents/${group.document.id}/find`, { q: s.q });
    }
    async function addLink(group, otherId) {
      const mine = detail.value.item.item_id;
      const [upper, lower] = group.direction === "lower" ? [mine, otherId] : [otherId, mine];
      await api.post("/api/links", { relation_id: group.relation_id, upper_item_id: upper, lower_item_id: lower });
      toast("リンクを追加しました");
      await Promise.all([loadDetail(), load()]);
    }
    async function removeLink(link) {
      // 確認ダイアログは出さない（自動リンクは「元に戻す」で戻せ、手動リンクは追加し直せるため）
      await api.del(`/api/links/${link.id}`);
      toast(link.auto ? `${link.item_id} へのリンクを無効化しました（「元に戻す」で戻せます）` : `${link.item_id} へのリンクを削除しました`);
      await Promise.all([loadDetail(), load()]);
    }
    async function restoreLink(link) {
      await api.post(`/api/links/${link.id}/restore`);
      await Promise.all([loadDetail(), load()]);
    }
    async function ackLink(link) {
      await api.post("/api/links/ack", { ids: [link.id] });
      toast("確認済みにしました");
      await Promise.all([loadDetail(), load()]);
    }

    function startEdit() {
      selectItem("");
      editing.value = true;
    }
    async function onEditClose(e) {
      editing.value = false;
      if (!e?.saved) return;
      versions.value = await api.get(`/api/documents/${props.docId}/versions`);
      doc.value = await api.get(`/api/documents/${props.docId}`);
      if (route.query.version) replaceQuery({ version: "" }); // 最新版の表示に戻す（query の変更で読み直す）
      else await load();
    }

    function traceBadges(t) {
      if (!t) return [];
      const b = [];
      if (t.no_upper) b.push(["warn", "上位なし"]);
      if (t.no_lower) b.push(["warn", "下位なし"]);
      if (t.suspect) b.push(["suspect", "要確認"]);
      if (t.broken) b.push(["err", "リンク切れ"]);
      return b;
    }

    return {
      doc, versions, result, detail, loading, versionId, q, trace, invalidOnly, filters, choices, wrap, sort, desc, page, pages, widthStyle,
      columns, isLatest, TRACE_FILTERS, STATUS_LABEL, ORIGIN_LABEL, search, route,
      editing, startEdit, onEditClose,
      setSort, goPage, selectItem, changeVersion, findCandidates, addLink, removeLink, restoreLink, ackLink,
      traceBadges, fmtValue, href, navigate,
    };
  },
  template: `
    <section class="page items-page" v-if="doc">
      <div class="page-head">
        <h1>{{ doc.name }}</h1>
        <div class="actions">
          <button v-if="isLatest && !editing" class="btn primary" @click="startEdit" title="セルの修正、行・列の追加ができます">編集</button>
          <label class="inline" v-if="!editing">版
            <select :value="versionId" @change="changeVersion">
              <option v-for="(v, i) in versions" :key="v.id" :value="v.id">v{{ v.version_no }} {{ v.label }}{{ i === 0 ? '（最新）' : '' }}</option>
            </select>
          </label>
          <template v-if="!editing">
            <a class="btn" :href="href('/documents/' + docId + '/import')">取り込み</a>
            <a class="btn" :href="href('/documents/' + docId + '/versions')">版・差分</a>
            <a class="btn" :href="href('/documents/' + docId + '/settings')">設定</a>
          </template>
        </div>
      </div>

      <ItemEditor v-if="editing" :doc-id="docId" @close="onEditClose" />

      <p v-if="!doc.latest_version_id" class="empty">まだ取り込まれていません。</p>
      <p v-else-if="result && !isLatest" class="notice">過去の版を表示しています（読み取り専用）。トレース情報は最新版でのみ表示します。</p>

      <div class="toolbar" v-if="result && !editing">
        <input class="search" v-model="q" placeholder="全文検索（ID・全列）">
        <label class="inline" v-if="isLatest">トレース
          <select v-model="trace"><option v-for="[v, l] in TRACE_FILTERS" :key="v" :value="v">{{ l }}</option></select>
        </label>
        <label class="check"><input type="checkbox" v-model="invalidOnly"> 警告のある行のみ</label>
        <label class="check" title="長い値を折り返して、全文を表示します"><input type="checkbox" v-model="wrap"> 折り返して全文を表示</label>
        <span class="spacer"></span>
        <span class="sub">{{ result.total }} 件</span>
        <button class="icon-btn" :disabled="page <= 1" @click="goPage(page - 1)">‹</button>
        <span>{{ page }} / {{ pages }}</span>
        <button class="icon-btn" :disabled="page >= pages" @click="goPage(page + 1)">›</button>
      </div>

      <div class="split" v-if="result && !editing">
        <div class="split-main scroll-both">
          <table class="grid compact items-table" :class="{wrap}">
            <thead>
              <tr>
                <th v-for="c in columns" :key="c.key" class="sortable" :style="widthStyle(c)" @click="setSort(c.key)">
                  {{ c.name }} <span v-if="sort === c.key">{{ desc ? '▼' : '▲' }}</span>
                </th>
                <template v-if="isLatest">
                  <th class="sortable num" @click="setSort('upper_count')">上位 <span v-if="sort === 'upper_count'">{{ desc ? '▼' : '▲' }}</span></th>
                  <th class="sortable num" @click="setSort('lower_count')">下位 <span v-if="sort === 'lower_count'">{{ desc ? '▼' : '▲' }}</span></th>
                  <th>状態</th>
                </template>
              </tr>
              <tr class="filter-row">
                <th v-for="c in columns" :key="c.key">
                  <ChoiceFilter v-if="c.type === 'enum' || c.type === 'bool'" :col="c" v-model="choices[c.key]" />
                  <input v-else v-model="filters[c.key]" placeholder="絞り込み">
                </th>
                <template v-if="isLatest"><th></th><th></th><th></th></template>
              </tr>
            </thead>
            <tbody>
              <tr v-for="it in result.items" :key="it.item_id" @click="selectItem(it.item_id)" :class="{selected: route.query.item === it.item_id}">
                <td v-for="c in columns" :key="c.key" :style="widthStyle(c)" :class="{invalid: it.invalid.includes(c.key), idcell: c.type === 'id'}"><CellValue :value="it.data[c.key]" :col="c" /></td>
                <template v-if="isLatest">
                  <td class="num">{{ result.has_upper ? it.trace?.upper_count : '-' }}</td>
                  <td class="num">{{ result.has_lower ? it.trace?.lower_count : '-' }}</td>
                  <td class="nowrap"><span v-for="[k, l] in traceBadges(it.trace)" :key="l" class="badge" :class="k">{{ l }}</span></td>
                </template>
              </tr>
            </tbody>
          </table>
          <p v-if="result.items.length === 0" class="empty">該当する項目がありません。</p>
        </div>

        <aside class="split-side" v-if="detail">
          <div class="side-head">
            <h2>{{ detail.item.item_id }}</h2>
            <span class="actions">
              <a v-if="detail.is_latest" class="btn small primary" :href="href('/documents/' + docId + '/side', {item: detail.item.item_id})"
                 title="上位の項目 ｜ この項目 ｜ 下位の項目 を横に並べて、全列を見る">上位・下位と横並びで見る</a>
              <button class="icon-btn" title="閉じる" @click="selectItem('')">×</button>
            </span>
          </div>
          <table class="kv">
            <tr v-for="c in detail.schema.columns" :key="c.key">
              <th>{{ c.name }}</th>
              <td :class="{invalid: detail.item.invalid.includes(c.key)}" class="pre">{{ fmtValue(detail.item.data[c.key], c) }}</td>
            </tr>
          </table>

          <div v-for="g in detail.relations" :key="g.relation_id" class="link-group">
            <h3>{{ g.direction === 'upper' ? '上位' : '下位' }}: {{ g.document.name }}</h3>
            <p v-if="!g.links.length" class="warn-text small">リンクがありません</p>
            <ul class="links">
              <li v-for="l in g.links" :key="l.id" :class="{inactive: !l.active}">
                <a v-if="l.status !== 'broken'" :href="href('/documents/' + g.document.id + '/items', {item: l.item_id})">{{ l.item_id }}</a>
                <span v-else class="err-text">{{ l.item_id }}</span>
                <span class="label">{{ l.label }}</span>
                <span class="badge" :class="l.active ? l.status : 'off'">{{ l.active ? STATUS_LABEL[l.status] : '無効化' }}</span>
                <span class="sub">{{ ORIGIN_LABEL[l.origin] }}</span>
                <span class="link-actions">
                  <button v-if="l.active && l.status === 'suspect'" class="btn small" @click="ackLink(l)">確認済み</button>
                  <button v-if="l.active" class="btn small danger-ghost" @click="removeLink(l)">{{ l.origin === 'auto' ? '無効化' : '削除' }}</button>
                  <button v-else class="btn small primary" @click="restoreLink(l)">元に戻す</button>
                </span>
              </li>
            </ul>
            <div class="link-add">
              <input v-if="search[g.relation_id]" v-model="search[g.relation_id].q" @keydown.enter="findCandidates(g)" placeholder="ID・表示列で検索してリンクを追加">
              <button class="btn small" @click="findCandidates(g)">検索</button>
              <ul class="candidates" v-if="search[g.relation_id]?.results?.length">
                <li v-for="c in search[g.relation_id].results" :key="c.item_id">
                  <span>{{ c.item_id }}</span> <span class="label">{{ c.label }}</span>
                  <button class="btn small" :disabled="g.links.some(l => l.item_id === c.item_id && l.active)" @click="addLink(g, c.item_id)">追加</button>
                </li>
              </ul>
            </div>
          </div>
          <p v-if="detail.is_latest && !detail.relations.length" class="sub">この文書にはトレース関係がありません。文書一覧で関係を登録してください。</p>
        </aside>
      </div>
    </section>
  `,
};
