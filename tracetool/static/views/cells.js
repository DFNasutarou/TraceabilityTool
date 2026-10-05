// 項目一覧・横並び表示・編集で共通に使う、セルの値の表示部品と、選択式の絞り込み部品。

import { fmtValue } from "../api.js";

const { ref, computed, watch, onMounted, onBeforeUnmount } = Vue;

// セルの値。リスト形式で値が 2 つ以上ある場合は 1 つ目だけを表示し、‹ › で 2 つ目以降に切り替える
export const CellValue = {
  props: {
    value: { default: null },
    col: { type: Object, default: null },
  },
  setup(props) {
    const idx = ref(0);
    const isMulti = computed(() => Array.isArray(props.value) && props.value.length > 1);
    watch(() => props.value, () => (idx.value = 0));
    const text = computed(() =>
      isMulti.value ? fmtValue(props.value[Math.min(idx.value, props.value.length - 1)]) : fmtValue(props.value, props.col)
    );
    function step(d) {
      const n = props.value.length;
      idx.value = (idx.value + d + n) % n;
    }
    const all = computed(() => (isMulti.value ? fmtValue(props.value, props.col) : ""));
    return { idx, isMulti, text, step, all };
  },
  template: `
    <span v-if="isMulti" class="list-value">
      <span class="list-nav" @click.stop :title="'全 ' + value.length + ' 件: ' + all">
        <button class="list-btn" @click.stop="step(-1)" aria-label="前の値">‹</button><span class="list-pos">{{ idx + 1 }}/{{ value.length }}</span><button class="list-btn" @click.stop="step(1)" aria-label="次の値">›</button>
      </span><span class="list-text">{{ text }}</span>
    </span>
    <template v-else>{{ text }}</template>
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

// 横並び表示のカードで、欄が占める幅（4 分割のうちいくつか）。自動・全幅は 1 行全体
export const WIDTH_SPAN = { s: 1, m: 2, l: 3, full: 4, auto: 4 };

// 画面ごとの表示の設定（折り返しなど）を、ブラウザに保存しておく
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
