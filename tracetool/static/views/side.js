// 横並び表示: 上位の項目 ｜ この文書の項目（全件を順番どおりに縦に並べる） ｜ 下位の項目
// 中央の列で項目を選ぶと、左右の列がその項目の上位・下位に切り替わる。
// カードの中は、カラム定義の並び順のとおりに、列の幅に応じて欄を横に並べる
// （1 行に 小 = 4 個、中 = 3 個、大 = 2 個、自動・全幅 = 1 個）。重要度で文字の大きさを変える（低 = 小さく / 中 = 普通 / 高 = 大きく太字）。

import { api, STATUS_LABEL, ORIGIN_LABEL } from "../api.js";
import { route, href, navigate } from "../router.js";
import { FieldGrid, storedFlag, storedChoice } from "./cells.js";

const { ref, computed, watch, nextTick, onMounted, onBeforeUnmount } = Vue;

// 一度に描画する件数（項目が多い文書でも重くならないよう、選んだ項目の前後だけを描画し、スクロールで広げる）
const WINDOW = 100;

// 1 項目分のカード（ID と全列の値）
const ItemCard = {
  components: { FieldGrid },
  props: {
    docId: { type: Number, required: true },
    schema: { type: Object, required: true },
    entry: { type: Object, required: true }, // { item_id, data, invalid, status?, origin? }
    current: { type: Boolean, default: false },
    selectable: { type: Boolean, default: false }, // 中央の列: 押すとその項目を選ぶ
    wrap: { type: Boolean, default: true }, // 長い値を折り返して全文を表示する
    minImportance: { type: String, default: "low" }, // この重要度以上の列だけを表示する
  },
  emits: ["select"],
  setup() {
    return { href, STATUS_LABEL, ORIGIN_LABEL };
  },
  template: `
    <div class="side-card" :class="{current, broken: !entry.data, selectable}" @click="selectable && $emit('select', entry.item_id)">
      <div class="side-card-head">
        <span v-if="current || selectable" class="side-card-id">{{ entry.item_id }}</span>
        <a v-else-if="entry.data" class="side-card-id" :href="href('/documents/' + docId + '/side', {item: entry.item_id})"
           title="この項目を中心にして見る">{{ entry.item_id }}</a>
        <span v-else class="side-card-id err-text">{{ entry.item_id }}</span>
        <span v-if="entry.status" class="badge" :class="entry.status">{{ STATUS_LABEL[entry.status] }}</span>
        <span v-if="entry.origin" class="sub">{{ ORIGIN_LABEL[entry.origin] }}</span>
      </div>
      <p v-if="!entry.data" class="err-text small">最新版に存在しない ID です（リンク切れ）。</p>
      <FieldGrid v-else :columns="schema.columns" :data="entry.data" :invalid="entry.invalid" :wrap="wrap" :min-importance="minImportance" />
    </div>
  `,
};

export default {
  components: { ItemCard },
  props: { docId: { type: Number, required: true } },
  setup(props) {
    const all = ref(null); // この文書の全項目 { schema, items }
    const view = ref(null); // 選んだ項目の上位・下位
    const range = ref([0, 0]); // 中央の列で描画している範囲 [開始, 終了)
    const listEl = ref(null);
    const wrap = storedFlag("sideWrap", true);
    // 表示する列: 重要度がこれ以上の列だけをカードに出す（ブラウザに記憶する）
    const minImportance = storedChoice("sideMinImportance", "low", ["low", "mid", "high"]);

    const selectedId = computed(() => route.query.item || all.value?.items[0]?.item_id);
    const selectedIndex = computed(() => (all.value ? all.value.items.findIndex((i) => i.item_id === selectedId.value) : -1));
    const visible = computed(() => (all.value ? all.value.items.slice(range.value[0], range.value[1]) : []));

    function centerRange(idx) {
      const n = all.value.items.length;
      range.value = [Math.max(0, idx - WINDOW), Math.min(n, idx + WINDOW)];
    }
    function showMore(dir) {
      const n = all.value.items.length;
      const [s, e] = range.value;
      range.value = dir < 0 ? [Math.max(0, s - WINDOW), e] : [s, Math.min(n, e + WINDOW)];
    }

    async function scrollToSelected() {
      await nextTick();
      listEl.value?.querySelector(".side-card.current")?.scrollIntoView({ block: "center" });
    }

    async function loadNeighborhood() {
      if (!selectedId.value) return;
      view.value = await api.get(`/api/documents/${props.docId}/neighborhood`, { id: selectedId.value });
    }

    onMounted(async () => {
      all.value = await api.get(`/api/documents/${props.docId}/latest-items`);
      centerRange(Math.max(0, selectedIndex.value));
      await loadNeighborhood();
      scrollToSelected();
    });

    // 中央の列で選んだとき（scroll: false）と、前後の移動・キー操作で選んだとき（scroll: true）
    let scrollOnChange = true;
    function select(id, scroll = false) {
      if (!id || id === selectedId.value) return;
      scrollOnChange = scroll;
      navigate(`/documents/${props.docId}/side`, { item: id });
    }
    watch(selectedId, async () => {
      if (!all.value) return;
      const idx = selectedIndex.value;
      if (idx >= 0 && (idx < range.value[0] || idx >= range.value[1])) centerRange(idx);
      await loadNeighborhood();
      if (scrollOnChange) scrollToSelected();
      scrollOnChange = true;
    });

    const prevId = computed(() => (selectedIndex.value > 0 ? all.value.items[selectedIndex.value - 1].item_id : null));
    const nextId = computed(() =>
      all.value && selectedIndex.value >= 0 && selectedIndex.value + 1 < all.value.items.length
        ? all.value.items[selectedIndex.value + 1].item_id
        : null
    );

    // Alt + ← / → で前後の項目へ移動する
    function onKey(e) {
      if (!all.value || !e.altKey) return;
      if (e.key === "ArrowLeft") select(prevId.value, true);
      if (e.key === "ArrowRight") select(nextId.value, true);
    }
    onMounted(() => window.addEventListener("keydown", onKey));
    onBeforeUnmount(() => window.removeEventListener("keydown", onKey));

    const count = (groups) => groups.reduce((n, g) => n + g.items.length, 0);

    return { all, view, range, visible, listEl, wrap, minImportance, selectedId, selectedIndex, prevId, nextId, select, showMore, count, href };
  },
  template: `
    <section class="page side-page" v-if="all">
      <div class="page-head">
        <h1>{{ view ? view.document.name : '' }}: {{ selectedId }}</h1>
        <div class="actions">
          <button class="btn" :disabled="!prevId" @click="select(prevId, true)" title="前の項目（Alt + ←）">‹ 前の項目</button>
          <label class="inline" title="列の重要度（文書の設定で列ごとに決めます）が高い方から、どこまでの列をカードに表示するかを選びます">表示する列
            <select v-model="minImportance">
              <option value="low">すべて（重要度 低 以上）</option>
              <option value="mid">重要度 中 以上</option>
              <option value="high">重要度 高 のみ</option>
            </select>
          </label>
          <label class="check" title="長い値を折り返して全文を表示します。外すと 1 行に収まる分だけ表示します"><input type="checkbox" v-model="wrap"> 折り返して全文を表示</label>
          <span class="sub">{{ selectedIndex + 1 }} / {{ all.items.length }}</span>
          <button class="btn" :disabled="!nextId" @click="select(nextId, true)" title="次の項目（Alt + →）">次の項目 ›</button>
          <a class="btn" :href="href('/documents/' + docId + '/items', {item: selectedId})">項目一覧に戻る</a>
        </div>
      </div>

      <div class="side-grid">
        <div class="side-col">
          <h2 class="side-col-head">上位 <span class="sub" v-if="view">（{{ count(view.upper) }} 件）</span></h2>
          <div class="side-scroll" v-if="view">
            <p v-if="!view.upper.length" class="empty">上位の文書がありません。</p>
            <div v-for="g in view.upper" :key="g.relation_id" class="side-group">
              <h3>{{ g.document.name }}</h3>
              <p v-if="!g.items.length" class="warn-text small">リンクがありません（上位なし）</p>
              <ItemCard v-for="e in g.items" :key="e.link_id" :doc-id="g.document.id" :schema="g.schema" :entry="e" :wrap="wrap" :min-importance="minImportance" />
            </div>
          </div>
        </div>

        <div class="side-col">
          <h2 class="side-col-head">この文書の項目 <span class="sub">（押すと左右が切り替わります）</span></h2>
          <div class="side-scroll" ref="listEl">
            <button v-if="range[0] > 0" class="btn small side-more" @click="showMore(-1)">前の項目を表示（あと {{ range[0] }} 件）</button>
            <ItemCard v-for="e in visible" :key="e.item_id" :doc-id="docId" :schema="all.schema" :entry="e"
                      :current="e.item_id === selectedId" selectable :wrap="wrap" :min-importance="minImportance" @select="select" />
            <button v-if="range[1] < all.items.length" class="btn small side-more" @click="showMore(1)">次の項目を表示（あと {{ all.items.length - range[1] }} 件）</button>
          </div>
        </div>

        <div class="side-col">
          <h2 class="side-col-head">下位 <span class="sub" v-if="view">（{{ count(view.lower) }} 件）</span></h2>
          <div class="side-scroll" v-if="view">
            <p v-if="!view.lower.length" class="empty">下位の文書がありません。</p>
            <div v-for="g in view.lower" :key="g.relation_id" class="side-group">
              <h3>{{ g.document.name }}</h3>
              <p v-if="!g.items.length" class="warn-text small">リンクがありません（下位なし）</p>
              <ItemCard v-for="e in g.items" :key="e.link_id" :doc-id="g.document.id" :schema="g.schema" :entry="e" :wrap="wrap" :min-importance="minImportance" />
            </div>
          </div>
        </div>
      </div>
    </section>
  `,
};
