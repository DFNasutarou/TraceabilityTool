// 横並び表示: 上位の項目 ｜ 今見ている項目 ｜ 下位の項目
// 上位・下位が複数ある場合は縦に並べ、列ごとにスクロールして見る。

import { api, fmtValue, STATUS_LABEL, ORIGIN_LABEL } from "../api.js";
import { route, href, navigate } from "../router.js";

const { ref, watch, onMounted, onBeforeUnmount } = Vue;

// 1 項目分のカード（ID と全列の値）
const ItemCard = {
  props: {
    docId: { type: Number, required: true },
    schema: { type: Object, required: true },
    entry: { type: Object, required: true }, // { item_id, data, invalid, status?, origin? }
    current: { type: Boolean, default: false },
  },
  setup() {
    return { fmtValue, href, STATUS_LABEL, ORIGIN_LABEL };
  },
  template: `
    <div class="side-card" :class="{current, broken: !entry.data}">
      <div class="side-card-head">
        <span v-if="current" class="side-card-id">{{ entry.item_id }}</span>
        <a v-else-if="entry.data" class="side-card-id" :href="href('/documents/' + docId + '/side', {item: entry.item_id})"
           title="この項目を中心にして見る">{{ entry.item_id }}</a>
        <span v-else class="side-card-id err-text">{{ entry.item_id }}</span>
        <span v-if="entry.status" class="badge" :class="entry.status">{{ STATUS_LABEL[entry.status] }}</span>
        <span v-if="entry.origin" class="sub">{{ ORIGIN_LABEL[entry.origin] }}</span>
      </div>
      <p v-if="!entry.data" class="err-text small">最新版に存在しない ID です（リンク切れ）。</p>
      <table v-else class="kv">
        <tr v-for="c in schema.columns.filter(c => c.type !== 'id')" :key="c.key">
          <th>{{ c.name }}</th>
          <td class="pre" :class="{invalid: entry.invalid.includes(c.key)}">{{ fmtValue(entry.data[c.key]) }}</td>
        </tr>
      </table>
    </div>
  `,
};

export default {
  components: { ItemCard },
  props: { docId: { type: Number, required: true } },
  setup(props) {
    const view = ref(null);
    const loading = ref(false);

    async function load() {
      const id = route.query.item;
      if (!id) return;
      loading.value = true;
      try {
        view.value = await api.get(`/api/documents/${props.docId}/neighborhood`, { id });
      } finally {
        loading.value = false;
      }
    }
    onMounted(load);
    watch(() => route.query.item, load);

    function go(id) {
      if (id) navigate(`/documents/${props.docId}/side`, { item: id });
    }
    // Alt + ← / → で前後の項目へ移動する
    function onKey(e) {
      if (!view.value || !e.altKey) return;
      if (e.key === "ArrowLeft") go(view.value.prev);
      if (e.key === "ArrowRight") go(view.value.next);
    }
    onMounted(() => window.addEventListener("keydown", onKey));
    onBeforeUnmount(() => window.removeEventListener("keydown", onKey));

    const count = (groups) => groups.reduce((n, g) => n + g.items.length, 0);

    return { view, loading, go, count, href, route };
  },
  template: `
    <section class="page side-page" v-if="view">
      <div class="page-head">
        <h1>{{ view.document.name }}: {{ view.item.item_id }}</h1>
        <div class="actions">
          <button class="btn" :disabled="!view.prev" @click="go(view.prev)" title="前の項目（Alt + ←）">‹ 前の項目</button>
          <span class="sub">{{ view.position }} / {{ view.total }}</span>
          <button class="btn" :disabled="!view.next" @click="go(view.next)" title="次の項目（Alt + →）">次の項目 ›</button>
          <a class="btn" :href="href('/documents/' + docId + '/items', {item: view.item.item_id})">項目一覧に戻る</a>
        </div>
      </div>

      <div class="side-grid">
        <div class="side-col">
          <h2 class="side-col-head">上位 <span class="sub">（{{ count(view.upper) }} 件）</span></h2>
          <div class="side-scroll">
            <p v-if="!view.upper.length" class="empty">上位の文書がありません。</p>
            <div v-for="g in view.upper" :key="g.relation_id" class="side-group">
              <h3>{{ g.document.name }}</h3>
              <p v-if="!g.items.length" class="warn-text small">リンクがありません（上位なし）</p>
              <ItemCard v-for="e in g.items" :key="e.link_id" :doc-id="g.document.id" :schema="g.schema" :entry="e" />
            </div>
          </div>
        </div>

        <div class="side-col">
          <h2 class="side-col-head">この項目</h2>
          <div class="side-scroll">
            <ItemCard :doc-id="docId" :schema="view.schema" :entry="view.item" current />
          </div>
        </div>

        <div class="side-col">
          <h2 class="side-col-head">下位 <span class="sub">（{{ count(view.lower) }} 件）</span></h2>
          <div class="side-scroll">
            <p v-if="!view.lower.length" class="empty">下位の文書がありません。</p>
            <div v-for="g in view.lower" :key="g.relation_id" class="side-group">
              <h3>{{ g.document.name }}</h3>
              <p v-if="!g.items.length" class="warn-text small">リンクがありません（下位なし）</p>
              <ItemCard v-for="e in g.items" :key="e.link_id" :doc-id="g.document.id" :schema="g.schema" :entry="e" />
            </div>
          </div>
        </div>
      </div>
    </section>
    <p v-else-if="!route.query.item" class="empty">項目が指定されていません。</p>
  `,
};
