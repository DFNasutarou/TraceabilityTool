// 項目一覧・横並び表示・編集で共通に使う、セルの値の表示部品と、選択式の絞り込み部品。

import { fmtValue, query } from "../api.js";

const { ref, computed, watch, onMounted, onBeforeUnmount } = Vue;

// リスト形式の値の切り替え（‹ 1/3 ›）。値の位置（idx）は親が持つ
export const ListNav = {
  props: {
    count: { type: Number, required: true },
    idx: { type: Number, required: true },
    title: { type: String, default: "" },
  },
  emits: ["step"],
  template: `
    <span class="list-nav" @click.stop :title="title">
      <button class="list-btn" @click.stop="$emit('step', -1)" aria-label="前の値">‹</button><span class="list-pos">{{ idx + 1 }}/{{ count }}</span><button class="list-btn" @click.stop="$emit('step', 1)" aria-label="次の値">›</button>
    </span>
  `,
};

// 画像のパスの列の値。画像を表示し、押すと別のタブで元の大きさの画像を開く。表示できなければパスと理由を出す
export const ImageValue = {
  props: {
    docId: { type: Number, required: true },
    col: { type: Object, required: true },
    path: { type: String, required: true },
  },
  setup(props) {
    const failed = ref(false);
    watch(() => props.path, () => (failed.value = false));
    const url = computed(() => "/api/image" + query({ doc: props.docId, key: props.col.key, path: props.path }));
    return { failed, url };
  },
  template: `
    <span v-if="failed" class="img-error" :title="'画像を表示できません（基準フォルダ・パス・ファイルの種類を確認してください）: ' + path">⚠ {{ path }}</span>
    <a v-else :href="url" target="_blank" rel="noopener" @click.stop :title="path + '（押すと元の大きさで開きます）'">
      <img :src="url" :alt="path" class="cell-img" loading="lazy" @error="failed = true">
    </a>
  `,
};

// リスト形式で値が 2 つ以上ある場合に、1 つ目だけを表示して ‹ › で切り替えるための状態
function useListValue(valueRef, colRef) {
  const idx = ref(0);
  const isMulti = computed(() => Array.isArray(valueRef()) && valueRef().length > 1);
  watch(valueRef, () => (idx.value = 0));
  const text = computed(() => {
    const v = valueRef();
    return isMulti.value ? fmtValue(v[Math.min(idx.value, v.length - 1)]) : fmtValue(v, colRef());
  });
  // 今表示している 1 つの値（画像のパスの列で、画像にする値）
  const current = computed(() => {
    const v = valueRef();
    const x = Array.isArray(v) ? v[Math.min(idx.value, v.length - 1)] : v;
    return x === null || x === undefined || x === "" ? "" : String(x);
  });
  const all = computed(() => (isMulti.value ? `全 ${valueRef().length} 件: ` + fmtValue(valueRef(), colRef()) : ""));
  function step(d) {
    const n = valueRef().length;
    idx.value = (idx.value + d + n) % n;
  }
  return { idx, isMulti, text, all, step, current };
}

// セルの値（項目一覧・編集）。リスト形式で値が 2 つ以上ある場合は 1 つ目だけを表示し、末尾の ‹ › で切り替える
export const CellValue = {
  components: { ListNav, ImageValue },
  props: {
    value: { default: null },
    col: { type: Object, default: null },
    docId: { type: Number, default: null }, // 指定すると、画像のパスの列は画像で表示する
  },
  setup(props) {
    const s = useListValue(() => props.value, () => props.col);
    return { ...s, asImage: computed(() => !!(props.docId && props.col?.image && s.current.value)) };
  },
  template: `
    <span v-if="isMulti" class="list-value">
      <ImageValue v-if="asImage" :doc-id="docId" :col="col" :path="current" /><span v-else class="list-text">{{ text }}</span><ListNav :count="value.length" :idx="idx" :title="all" @step="step" />
    </span>
    <ImageValue v-else-if="asImage" :doc-id="docId" :col="col" :path="current" />
    <template v-else>{{ text }}</template>
  `,
};

// 横並び表示のカードの 1 つの欄（列名と値）。
// 列名の後で改行する列は、列名の行に ‹ › を置く。改行しない列は、列名を左に置き（長ければ省略）、‹ › を値の末尾に置く
const FieldItem = {
  components: { ListNav, ImageValue },
  props: {
    col: { type: Object, required: true },
    value: { default: null },
    invalid: { type: Boolean, default: false },
    wrap: { type: Boolean, default: true },
    placeholder: { type: String, default: "" }, // 値が無いときに薄く表示する文字（レイアウトのプレビュー用）
    docId: { type: Number, default: null }, // 指定すると、画像のパスの列は画像で表示する
  },
  setup(props) {
    const s = useListValue(() => props.value, () => props.col);
    return {
      ...s,
      span: computed(() => WIDTH_SPAN[props.col.width] || 12),
      asImage: computed(() => !!(props.docId && props.col.image && s.current.value)),
    };
  },
  template: `
    <div class="field" :class="['span-' + span, 'imp-' + (col.importance || 'low'), col.label_break ? 'break' : 'inline']">
      <template v-if="col.label_break">
        <div class="field-head"><span class="field-name" :title="col.name">{{ col.name }}</span><ListNav v-if="isMulti" :count="value.length" :idx="idx" :title="all" @step="step" /></div>
        <div class="field-value" :class="[wrap ? 'pre' : 'clip', {invalid}]">
          <ImageValue v-if="asImage" :doc-id="docId" :col="col" :path="current" />
          <template v-else-if="text">{{ text }}</template><span v-else-if="placeholder" class="placeholder">{{ placeholder }}</span>
        </div>
      </template>
      <template v-else>
        <span class="field-name" :title="col.name">{{ col.name }}</span>
        <div class="field-value" :class="[wrap ? 'pre' : 'clip', {invalid}]">
          <span v-if="isMulti" class="list-value">
            <ImageValue v-if="asImage" :doc-id="docId" :col="col" :path="current" /><span v-else class="list-text">{{ text }}</span><ListNav :count="value.length" :idx="idx" :title="all" @step="step" />
          </span>
          <ImageValue v-else-if="asImage" :doc-id="docId" :col="col" :path="current" />
          <template v-else-if="text">{{ text }}</template><span v-else-if="placeholder" class="placeholder">{{ placeholder }}</span>
        </div>
      </template>
    </div>
  `,
};

// 横並び表示のカードの中身。カラム定義の並び順のとおりに、列の幅に応じて欄を横に並べる
export const FieldGrid = {
  components: { FieldItem },
  props: {
    columns: { type: Array, required: true },
    data: { type: Object, required: true },
    invalid: { type: Array, default: () => [] },
    wrap: { type: Boolean, default: true },
    placeholder: { type: Boolean, default: false },
    minImportance: { type: String, default: "low" }, // この重要度以上の列だけを表示する
    docId: { type: Number, default: null }, // 画像のパスの列を画像で表示するときの文書
  },
  setup(props) {
    const cols = computed(() =>
      props.columns.filter(
        (c) => c.type !== "id" && IMPORTANCE_RANK[c.importance || "low"] >= IMPORTANCE_RANK[props.minImportance]
      )
    );
    return { cols };
  },
  template: `
    <div class="field-grid">
      <FieldItem v-for="c in cols" :key="c.key" :col="c" :value="data[c.key] ?? null" :invalid="invalid.includes(c.key)"
                 :wrap="wrap" :doc-id="docId" :placeholder="placeholder ? '（' + c.name + 'の値）' : ''" />
    </div>
  `,
};

export const EMPTY = "__empty__";
export const OTHER = "__other__";

// enum・bool の列の選択肢（絞り込み・編集で使う）
export function choiceOptions(col) {
  if (col.type === "bool") return [{ value: "true", label: "○（真）" }, { value: "false", label: "×（偽）" }];
  return (col.enum_values || []).map((v) => ({ value: v, label: v }));
}

// 選択式の絞り込み（複数選択）。押すと選択肢の一覧が開く
export const ChoiceFilter = {
  props: {
    col: { type: Object, required: true },
    modelValue: { type: Array, default: () => [] },
  },
  emits: ["update:modelValue"],
  setup(props, { emit }) {
    const open = ref(false);
    const root = ref(null);
    const options = computed(() => [
      ...choiceOptions(props.col),
      { value: OTHER, label: props.col.type === "bool" ? "（真・偽のどちらでもない値）" : "（選択肢に無い値）", extra: true },
      { value: EMPTY, label: "（空欄）", extra: true },
    ]);
    const summary = computed(() => {
      const sel = props.modelValue;
      if (!sel.length) return "すべて";
      const labels = options.value.filter((o) => sel.includes(o.value)).map((o) => o.label);
      return labels.length <= 2 ? labels.join(", ") : `${labels.length} 個を選択`;
    });
    function toggle(v) {
      const sel = new Set(props.modelValue);
      if (sel.has(v)) sel.delete(v);
      else sel.add(v);
      // 選択肢の並び順で返す
      emit("update:modelValue", options.value.map((o) => o.value).filter((x) => sel.has(x)));
    }
    function clear() {
      emit("update:modelValue", []);
    }
    function onDocClick(e) {
      if (open.value && root.value && !root.value.contains(e.target)) open.value = false;
    }
    onMounted(() => document.addEventListener("mousedown", onDocClick));
    onBeforeUnmount(() => document.removeEventListener("mousedown", onDocClick));
    return { open, root, options, summary, toggle, clear };
  },
  template: `
    <div class="choice-filter" ref="root">
      <button class="choice-btn" :class="{active: modelValue.length}" @click="open = !open" :title="summary">{{ summary }} ▾</button>
      <div v-if="open" class="choice-pop">
        <label v-for="o in options" :key="o.value" class="check" :class="{extra: o.extra}">
          <input type="checkbox" :checked="modelValue.includes(o.value)" @change="toggle(o.value)"> {{ o.label }}
        </label>
        <div class="choice-foot">
          <button class="btn small" :disabled="!modelValue.length" @click="clear">選択を解除</button>
          <button class="btn small" @click="open = false">閉じる</button>
        </div>
      </div>
    </div>
  `,
};

// 列の幅の設定（一覧表示の列幅、px）
export const WIDTH_PX = { s: 90, m: 180, l: 340, full: 560 };

export function widthStyle(col) {
  const px = WIDTH_PX[col?.width];
  return px ? { width: px + "px", minWidth: px + "px", maxWidth: px + "px" } : null;
}

export const IMPORTANCE_RANK = { low: 0, mid: 1, high: 2 };

// 横並び表示のカードで、欄が占める幅（12 分割のうちいくつか）。
// 小 = 1 行に 4 個、中 = 3 個、大 = 2 個、自動・全幅 = 1 個
export const WIDTH_SPAN = { s: 3, m: 4, l: 6, full: 12, auto: 12 };

// 画面ごとの表示の設定（折り返しなど）を、ブラウザに保存しておく
// 選択肢の値（文字列）を記憶する。choices に無い値が保存されていたら既定値にする
export function storedChoice(key, initial, choices) {
  let v = initial;
  try {
    const s = localStorage.getItem("tracetool." + key);
    if (s !== null && choices.includes(s)) v = s;
  } catch {
    // 保存できない環境では既定値のまま
  }
  const r = ref(v);
  watch(r, (x) => {
    try {
      localStorage.setItem("tracetool." + key, x);
    } catch {
      // 無視する
    }
  });
  return r;
}

export function storedFlag(key, initial) {
  let v = initial;
  try {
    const s = localStorage.getItem("tracetool." + key);
    if (s !== null) v = s === "1";
  } catch {
    // 保存できない環境では既定値のまま
  }
  const r = ref(v);
  watch(r, (x) => {
    try {
      localStorage.setItem("tracetool." + key, x ? "1" : "0");
    } catch {
      // 無視する
    }
  });
  return r;
}
