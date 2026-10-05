// 項目一覧の編集モード。最新版の全項目を画面で編集し、新しい版として、または最新版を書き換えて保存する。
// セルを押すとその場で編集できる。enum・bool は選択肢から選ぶ（enum は選択肢を足せる）。
// 取り込み済みの項目の ID を変えると、保存時にリンクと他の文書の参照 ID 列の値も新しい ID に付け直す。

import { api, toast, TYPE_LABEL } from "../api.js";
import { CellValue, widthStyle, choiceOptions } from "./cells.js";

const { ref, reactive, computed, watch, nextTick, onMounted, onBeforeUnmount } = Vue;

const PAGE_SIZE = 500;

function newKey() {
  return "c" + Array.from(crypto.getRandomValues(new Uint8Array(4)), (b) => b.toString(16).padStart(2, "0")).join("");
}

const clone = (v) => (v === undefined ? undefined : JSON.parse(JSON.stringify(v)));
const same = (a, b) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null);

// 1 つのセルの編集欄
const EditCell = {
  props: {
    col: { type: Object, required: true },
    row: { type: Object, required: true },
  },
  emits: ["add-choice", "done"],
  setup(props, { emit }) {
    const isList = computed(() => !!props.col.list && props.col.type !== "id");
    const value = computed(() => props.row.data[props.col.key] ?? null);
    function set(v) {
      props.row.data[props.col.key] = v === "" || (Array.isArray(v) && !v.length) ? null : v;
    }

    // 文字列・番号・ID（リスト形式なら 1 行に 1 つ）
    const text = computed(() => {
      const v = value.value;
      if (v === null) return "";
      return Array.isArray(v) ? v.map(String).join("\n") : String(v);
    });
    function onText(e) {
      const t = e.target.value;
      if (isList.value) {
        set(t.split("\n").map((s) => s.trim()).filter(Boolean).map(toTyped));
      } else {
        set(props.col.type === "string" ? t : toTyped(t.trim()));
      }
    }
    function toTyped(t) {
      return props.col.type === "int" && /^[+-]?\d+$/.test(t) ? Number(t) : t;
    }
    const rows = computed(() => Math.min(8, Math.max(isList.value ? 3 : 1, text.value.split("\n").length)));

    // enum・bool
    const options = computed(() => choiceOptions(props.col));
    const scalarKey = computed(() => {
      const v = value.value;
      if (v === null) return "";
      if (v === true) return "true";
      if (v === false) return "false";
      return String(v);
    });
    // 選択肢に無い値（取り込み時の警告の値）も選べるよう、一覧に残す
    const unknown = computed(() => {
      const known = new Set(options.value.map((o) => o.value));
      const vals = Array.isArray(value.value) ? value.value.map(String) : value.value === null ? [] : [scalarKey.value];
      return vals.filter((v) => !known.has(v));
    });
    function onSelect(e) {
      const v = e.target.value;
      if (props.col.type === "bool") set(v === "true" ? true : v === "false" ? false : v === "" ? null : v);
      else set(v);
    }
    const checked = (v) => Array.isArray(value.value) && value.value.map(String).includes(v);
    function toggle(v) {
      const cur = Array.isArray(value.value) ? [...value.value] : value.value === null ? [] : [value.value];
      const i = cur.map(String).indexOf(v);
      if (i >= 0) cur.splice(i, 1);
      else cur.push(v);
      // 選択肢の並び順にそろえる（選択肢に無い値は後ろ）
      const order = options.value.map((o) => o.value);
      cur.sort((a, b) => (order.indexOf(String(a)) + 1 || 1e9) - (order.indexOf(String(b)) + 1 || 1e9));
      set(cur);
    }

    // enum の選択肢を足す
    const adding = ref(false);
    const newChoice = ref("");
    function addChoice() {
      const v = newChoice.value.trim();
      if (!v) return;
      emit("add-choice", v);
      if (isList.value) {
        if (!checked(v)) toggle(v);
      } else set(v);
      newChoice.value = "";
      adding.value = false;
    }

    return { isList, value, text, onText, rows, options, scalarKey, unknown, onSelect, checked, toggle, adding, newChoice, addChoice };
  },
  template: `
    <div class="edit-cell" @click.stop @keydown.esc.stop="$emit('done')">
      <template v-if="col.type === 'enum' || col.type === 'bool'">
        <div v-if="isList" class="edit-checks">
          <label v-for="o in options" :key="o.value" class="check"><input type="checkbox" :checked="checked(o.value)" @change="toggle(o.value)"> {{ o.label }}</label>
          <label v-for="u in unknown" :key="'u' + u" class="check unknown" title="選択肢に無い値です"><input type="checkbox" checked @change="toggle(u)"> {{ u }}</label>
        </div>
        <select v-else :value="scalarKey" @change="onSelect" class="edit-select">
          <option value="">（空欄）</option>
          <option v-for="o in options" :key="o.value" :value="o.value">{{ o.label }}</option>
          <option v-for="u in unknown" :key="'u' + u" :value="u">{{ u }}（選択肢に無い値）</option>
        </select>
        <template v-if="col.type === 'enum'">
          <div v-if="adding" class="edit-add-choice">
            <input v-model="newChoice" placeholder="新しい選択肢" @keydown.enter="addChoice">
            <button class="btn small primary" @click="addChoice">追加</button>
            <button class="btn small" @click="adding = false">やめる</button>
          </div>
          <button v-else class="btn small" @click="adding = true" title="この列の選択肢を足して、この値にします">＋ 選択肢を追加</button>
        </template>
      </template>
      <template v-else>
        <textarea :rows="rows" :value="text" @input="onText" :placeholder="isList ? '1 行に 1 つ' : ''" v-focus></textarea>
        <span v-if="isList" class="sub">1 行に 1 つ</span>
        <span v-if="col.type === 'id' && row.orig" class="id-note">
          元の ID: {{ row.orig.item_id }}。ID を変えると、保存時にこの項目のリンクと、他の文書がこの項目を参照している ID もすべて新しい ID に付け直します。
        </span>
      </template>
    </div>
  `,
  directives: {
    focus: { mounted: (el) => el.focus() },
  },
};

export default {
  components: { CellValue, EditCell },
  props: { docId: { type: Number, required: true } },
  emits: ["close"],
  setup(props, { emit }) {
    const base = ref(null); // { version_id, version_no, schema, items }
    const schema = ref(null);
    const rows = ref([]); // { uid, orig, data, deleted }
    const active = ref(null); // { uid, key }
    const page = ref(1);
    const q = ref("");
    const saving = ref(false);
    let seq = 0;

    async function load() {
      const r = await api.get(`/api/documents/${props.docId}/latest-items`);
      base.value = r;
      schema.value = clone(r.schema);
      rows.value = r.items.map((it) => reactive({ uid: ++seq, orig: it, data: clone(it.data), deleted: false }));
    }
    onMounted(load);

    const columns = computed(() => schema.value?.columns || []);
    const idCol = computed(() => columns.value.find((c) => c.type === "id"));
    const idOf = (r) => (r.data[idCol.value.key] ?? "").toString().trim();

    const isChanged = (r, c) => !r.orig || !same(r.data[c.key], r.orig.data[c.key]);
    const baseIds = computed(() => new Set(base.value?.items.map((i) => i.item_id)));
    // ID を変えた行: { 古い ID: 新しい ID }
    const renames = computed(() => {
      const out = {};
      for (const r of rows.value) {
        if (!r.orig || r.deleted) continue;
        const id = idOf(r);
        if (id && id !== r.orig.item_id) out[r.orig.item_id] = id;
      }
      return out;
    });
    // 編集前に別の項目で使われていた ID への変更（入れ替え・削除した項目の ID の再利用）は付け直しを取り違えるため受け付けない
    const badRenames = computed(() => Object.entries(renames.value).filter(([, n]) => baseIds.value.has(n)).map(([, n]) => n));
    const addedCols = computed(() => {
      const before = new Set(base.value?.schema.columns.map((c) => c.key));
      return columns.value.filter((c) => !before.has(c.key));
    });
    const stats = computed(() => {
      let changed = 0, added = 0, deleted = 0;
      for (const r of rows.value) {
        if (!r.orig) added += r.deleted ? 0 : 1;
        else if (r.deleted) deleted++;
        else if (columns.value.some((c) => isChanged(r, c))) changed++;
      }
      return { changed, added, deleted, columns: addedCols.value.length, renamed: Object.keys(renames.value).length };
    });
    const choicesChanged = computed(() =>
      columns.value.some((c) => {
        const b = base.value?.schema.columns.find((x) => x.key === c.key);
        return b && !same(b.enum_values, c.enum_values);
      })
    );
    const dirty = computed(() => {
      const s = stats.value;
      return !!(s.changed || s.added || s.deleted || s.columns || choicesChanged.value);
    });

    // ID の重複（追加した行の入力ミスを示す）
    const dupIds = computed(() => {
      const seen = new Set(), dup = new Set();
      for (const r of rows.value) {
        if (r.deleted) continue;
        const id = idOf(r);
        if (!id) continue;
        if (seen.has(id)) dup.add(id);
        seen.add(id);
      }
      return dup;
    });

    const filtered = computed(() => {
      const t = q.value.trim().toLowerCase();
      if (!t) return rows.value;
      return rows.value.filter((r) => !r.orig || JSON.stringify(r.data).toLowerCase().includes(t));
    });
    const pages = computed(() => Math.max(1, Math.ceil(filtered.value.length / PAGE_SIZE)));
    const visible = computed(() => filtered.value.slice((page.value - 1) * PAGE_SIZE, page.value * PAGE_SIZE));
    watch(q, () => (page.value = 1));

    function activate(r, c) {
      if (r.deleted) return;
      active.value = { uid: r.uid, key: c.key };
    }
    const isActive = (r, c) => active.value && active.value.uid === r.uid && active.value.key === c.key;
    function onKey(e) {
      if (e.key === "Escape") active.value = null;
    }
    onMounted(() => window.addEventListener("keydown", onKey));

    // --- 行の追加・削除 ---
    function nextAutoId() {
      const a = idCol.value.auto_id;
      if (!a) return "";
      let max = a.start - 1;
      for (const r of rows.value) {
        const id = idOf(r);
        if (id.startsWith(a.prefix) && /^\d+$/.test(id.slice(a.prefix.length))) max = Math.max(max, Number(id.slice(a.prefix.length)));
      }
      return a.prefix + String(max + 1).padStart(a.digits, "0");
    }
    async function addRow() {
      const r = reactive({ uid: ++seq, orig: null, data: {}, deleted: false });
      const id = nextAutoId();
      if (id) r.data[idCol.value.key] = id;
      rows.value.push(r);
      q.value = "";
      await nextTick(); // 検索語を消したことで 1 ページ目に戻る処理の後に、最後のページへ移る
      page.value = pages.value;
      active.value = { uid: r.uid, key: idCol.value.key };
      await nextTick();
      document.querySelector(".edit-table tr.added:last-of-type")?.scrollIntoView({ block: "center" });
    }
    function toggleDelete(r) {
      if (!r.orig) {
        rows.value.splice(rows.value.indexOf(r), 1);
        return;
      }
      r.deleted = !r.deleted;
      if (active.value?.uid === r.uid) active.value = null;
    }

    // --- 列の追加 ---
    const colForm = reactive({ open: false, name: "", type: "string", list: false, delim: ";", choices: "" });
    function addColumn() {
      const name = colForm.name.trim();
      if (!name) return toast("列名を入力してください", "error");
      if (columns.value.some((c) => c.name === name)) return toast(`列名「${name}」は既にあります`, "error");
      const choices = colForm.choices.split("\n").map((s) => s.trim()).filter(Boolean);
      if (colForm.type === "enum" && !choices.length) return toast("enum の列には選択肢を 1 つ以上入力してください", "error");
      schema.value.columns.push({
        key: newKey(), name, source_header: null, type: colForm.type,
        list: colForm.list && colForm.delim ? { delimiters: [colForm.delim === "\\n" ? "\n" : colForm.delim] } : null,
        enum_values: colForm.type === "enum" ? choices : null,
        bool_values: null, ref_document_id: null, importance: "low", width: "auto", auto_id: null,
      });
      toast(`列「${name}」を追加しました。保存すると、この文書のカラム定義にも加わります`);
      Object.assign(colForm, { open: false, name: "", type: "string", list: false, delim: ";", choices: "" });
    }
    function removeAddedColumn(c) {
      schema.value.columns.splice(schema.value.columns.indexOf(c), 1);
      for (const r of rows.value) delete r.data[c.key];
    }
    function addChoice(col, v) {
      if (!col.enum_values.includes(v)) col.enum_values.push(v);
    }

    // --- 保存 ---
    const saveForm = reactive({ open: false, mode: "new", label: "" });
    const impact = ref(null); // ID を付け直すと変わるもの
    const impactFailed = ref(false);
    async function loadImpact() {
      impact.value = null;
      impactFailed.value = false;
      try {
        impact.value = await api.post(`/api/documents/${props.docId}/rename-impact`, { renames: renames.value });
      } catch {
        impactFailed.value = true; // 付け直す範囲を確かめられないまま保存させない
      }
    }
    async function openSave() {
      impact.value = null;
      impactFailed.value = false;
      saveForm.open = true;
      if (stats.value.renamed) await loadImpact();
    }
    const canSave = computed(() => !saving.value && (!stats.value.renamed || !!impact.value));
    async function save() {
      saving.value = true;
      try {
        const r = await api.post(`/api/documents/${props.docId}/edit`, {
          base_version_id: base.value.version_id,
          base_stamp: base.value.stamp,
          mode: saveForm.mode,
          schema: schema.value,
          items: rows.value.filter((x) => !x.deleted).map((x) => ({ orig_id: x.orig?.item_id ?? null, data: x.data })),
          label: saveForm.label,
        });
        toast((r.mode === "new" ? `v${r.version_no} として保存しました` : `v${r.version_no} を書き換えて保存しました`) +
          (r.renamed ? `（ID を ${r.renamed} 件変更し、リンクと参照を付け直しました）` : ""));
        saveForm.open = false;
        window.removeEventListener("beforeunload", onBeforeUnload);
        emit("close", { saved: true, versionId: r.version_id });
      } finally {
        saving.value = false;
      }
    }
    function cancel() {
      if (dirty.value && !confirm("編集した内容を破棄して、編集を終えます。よろしいですか？")) return;
      emit("close", { saved: false });
    }

    // 保存せずにタブを閉じる・再読み込みする場合は、ブラウザに確認させる
    function onBeforeUnload(e) {
      if (dirty.value) {
        e.preventDefault();
        e.returnValue = "";
      }
    }
    onMounted(() => window.addEventListener("beforeunload", onBeforeUnload));
    onBeforeUnmount(() => {
      window.removeEventListener("beforeunload", onBeforeUnload);
      window.removeEventListener("keydown", onKey);
    });

    return {
      base, schema, rows, columns, idCol, active, renames, badRenames, impact, impactFailed, loadImpact, canSave, openSave, page, pages, q, visible, filtered, saving, stats, dirty, dupIds, addedCols,
      isChanged, activate, isActive, addRow, toggleDelete, colForm, addColumn, removeAddedColumn, addChoice,
      saveForm, save, cancel, idOf, widthStyle, TYPE_LABEL,
    };
  },
  template: `
    <div v-if="base" class="editor">
      <div class="edit-bar">
        <b>編集中</b>
        <span class="sub">v{{ base.version_no }}（最新版）を元に編集しています。セルを押すと編集できます（Esc で閉じる）。</span>
        <span class="spacer"></span>
        <span class="edit-stats">
          変更 {{ stats.changed }} 行 / 追加 {{ stats.added }} 行 / 削除 {{ stats.deleted }} 行<template v-if="stats.renamed"> / ID の変更 {{ stats.renamed }}</template><template v-if="stats.columns"> / 列の追加 {{ stats.columns }}</template>
        </span>
        <button class="btn" @click="cancel">編集をやめる</button>
        <button class="btn primary" :disabled="!dirty || dupIds.size > 0 || badRenames.length > 0" @click="openSave" :title="dupIds.size || badRenames.length ? 'ID に誤りがあります' : ''">保存…</button>
      </div>

      <div class="toolbar">
        <input class="search" v-model="q" placeholder="編集する項目を探す（全列）">
        <button class="btn" @click="addRow">＋ 行を追加</button>
        <button class="btn" @click="colForm.open = !colForm.open">＋ 列を追加</button>
        <span v-if="dupIds.size" class="err-text">ID が重複しています: {{ [...dupIds].join('、') }}</span>
        <span v-if="badRenames.length" class="err-text">編集前に別の項目で使われていた ID には変えられません: {{ badRenames.join('、') }}</span>
        <span class="spacer"></span>
        <span class="sub">{{ filtered.length }} 件</span>
        <button class="icon-btn" :disabled="page <= 1" @click="page--">‹</button>
        <span>{{ page }} / {{ pages }}</span>
        <button class="icon-btn" :disabled="page >= pages" @click="page++">›</button>
      </div>

      <div v-if="colForm.open" class="card inline-form add-col">
        <label>列名 <input v-model="colForm.name" placeholder="例: 担当者"></label>
        <label>型
          <select v-model="colForm.type">
            <option value="string">文字列</option>
            <option value="int">番号</option>
            <option value="enum">enum</option>
            <option value="bool">bool</option>
          </select>
        </label>
        <label class="check"><input type="checkbox" v-model="colForm.list"> リスト形式</label>
        <label v-if="colForm.list">区切り文字 <input class="tiny" v-model="colForm.delim" title="改行で区切る場合は \\n と書きます"></label>
        <label v-if="colForm.type === 'enum'" class="choices">選択肢（1 行に 1 つ）<textarea rows="3" v-model="colForm.choices"></textarea></label>
        <button class="btn primary" @click="addColumn">追加</button>
        <span class="sub">追加した列は、次回の取り込みでは「ファイルに無い列」になります（文書の設定で、ファイルの列に対応付けられます）。</span>
      </div>

      <div v-if="saveForm.open" class="modal-back" @click.self="saveForm.open = false">
        <div class="modal">
          <h2>編集した内容を保存</h2>
          <p class="sub">変更 {{ stats.changed }} 行 / 追加 {{ stats.added }} 行 / 削除 {{ stats.deleted }} 行<template v-if="stats.columns"> / 列の追加 {{ stats.columns }}</template></p>
          <div v-if="stats.renamed" class="rename-box">
            <b>ID の変更（{{ stats.renamed }} 件）</b>
            <ul class="rename-list">
              <li v-for="(n, o) in renames" :key="o"><span class="idcell">{{ o }}</span> → <span class="idcell">{{ n }}</span></li>
            </ul>
            <p v-if="impactFailed" class="err-text small">
              付け直す対象を調べられませんでした。<button class="btn small" @click="loadImpact">もう一度調べる</button>
            </p>
            <p v-else-if="!impact" class="sub">付け直す対象を調べています…</p>
            <template v-else>
              <p>保存すると、次も新しい ID に付け直します。</p>
              <ul>
                <li v-for="l in impact.links" :key="'l' + l.document">「{{ l.document }}」とのリンク {{ l.count }} 本</li>
                <li v-for="d in impact.documents" :key="'d' + d.document">
                  「{{ d.document }}」（v{{ d.version_no }}）の参照 ID 列: {{ d.count }} 項目（{{ d.items.join('、') }}{{ d.count > d.items.length ? ' …' : '' }}）。版は増やさずに書き換えます
                </li>
                <li v-if="!impact.links.length && !impact.documents.length">付け直すリンク・参照はありません。</li>
              </ul>
              <p class="warn-text small">元のファイル（この文書と、参照している文書）の ID も直してください。直さずに取り込み直すと、古い ID に戻り、リンクが切れます。</p>
            </template>
          </div>
          <label class="radio-block">
            <input type="radio" value="new" v-model="saveForm.mode">
            <span><b>新しい版として保存（v{{ base.version_no }} → 新しい版）</b><br>
            <span class="sub">編集前の v{{ base.version_no }} は残り、「版・差分」で変更点を比べられます。</span></span>
          </label>
          <label class="radio-block">
            <input type="radio" value="overwrite" v-model="saveForm.mode">
            <span><b>v{{ base.version_no }} を書き換えて保存（版はそのまま）</b><br>
            <span class="sub">編集前の内容は残りません。前の版との差分には、編集した内容も含まれます。</span></span>
          </label>
          <label class="inline">版のラベル <input v-model="saveForm.label" :placeholder="saveForm.mode === 'new' ? '例: 画面で修正' : '空欄なら変えない'"></label>
          <p class="sub">内容を変えた項目へのリンクは、相手側で「要確認」になります。</p>
          <div class="actions end">
            <button class="btn" @click="saveForm.open = false">戻る</button>
            <button class="btn primary" :disabled="!canSave" @click="save">保存する</button>
          </div>
        </div>
      </div>

      <div class="scroll-both">
        <table class="grid compact items-table edit-table wrap">
          <thead>
            <tr>
              <th v-for="c in columns" :key="c.key" :style="widthStyle(c)" :class="{'added-col': addedCols.includes(c)}">
                {{ c.name }} <span class="sub">{{ TYPE_LABEL[c.type] }}{{ c.list ? '・リスト' : '' }}</span>
                <button v-if="addedCols.includes(c)" class="icon-btn" title="追加した列を取り消す" @click="removeAddedColumn(c)">×</button>
              </th>
              <th style="width:64px"></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in visible" :key="r.uid" :class="{added: !r.orig, deleted: r.deleted}">
              <td v-for="c in columns" :key="c.key" :style="widthStyle(c)" @click="activate(r, c)"
                  :class="{edited: r.orig && isChanged(r, c), editing: isActive(r, c), idcell: c.type === 'id',
                           invalid: r.orig && !isChanged(r, c) && r.orig.invalid.includes(c.key),
                           dup: c.type === 'id' && (dupIds.has(idOf(r)) || badRenames.includes(idOf(r)))}">
                <EditCell v-if="isActive(r, c)" :col="c" :row="r" @add-choice="v => addChoice(c, v)" @done="active = null" />
                <template v-else-if="c.type === 'id' && r.orig && renames[r.orig.item_id]">
                  <span class="old-id">{{ r.orig.item_id }}</span> → {{ idOf(r) }}
                </template>
                <CellValue v-else :value="r.data[c.key]" :col="c" />
              </td>
              <td class="nowrap"><button class="btn small" :class="r.deleted ? '' : 'danger-ghost'" @click.stop="toggleDelete(r)">{{ r.deleted ? '戻す' : '削除' }}</button></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  `,
};
