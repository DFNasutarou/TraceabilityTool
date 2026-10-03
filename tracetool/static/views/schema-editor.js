// カラム定義の編集部品。文書の設定画面と、取り込みの列対応付け画面で使う。
// 編集用のモデル（toEdit で作る）を直接書き換える。保存時は fromEdit で API の形に戻す。

import { TYPE_LABEL } from "../api.js";

const DEFAULT_TRUE = ["○", "◯", "〇", "Yes", "Y", "TRUE", "1", "有", "あり"];
const DEFAULT_FALSE = ["×", "✕", "✖", "No", "N", "FALSE", "0", "無", "なし"];

function newKey() {
  return "c" + Array.from(crypto.getRandomValues(new Uint8Array(4)), (b) => b.toString(16).padStart(2, "0")).join("");
}

// 区切り文字: 改行とタブはチェックボックスで指定する。
// それ以外は入力欄にスペース区切りで書く（空白そのものを区切りにする場合は \s と書く）。
// 入力欄に \n や \t と書いても改行・タブとして扱う（以前の形式との互換のため）
const ESCAPES = { "\\n": "\n", "\\t": "\t", "\\s": " " };

function delimsToEdit(delims) {
  const list = delims || [];
  return {
    delimNewline: list.includes("\n"),
    delimTab: list.includes("\t"),
    delimText: list.filter((d) => d !== "\n" && d !== "\t").map((d) => (d === " " ? "\\s" : d)).join(" "),
  };
}

function editToDelims(c) {
  const out = c.delimText.split(/\s+/).filter(Boolean).map((d) => ESCAPES[d] ?? d);
  if (c.delimNewline) out.push("\n");
  if (c.delimTab) out.push("\t");
  return [...new Set(out)];
}

function lines(text) {
  return text.split("\n").map((s) => s.trim()).filter(Boolean);
}

export function newColumn(name = "", sourceHeader = null, type = "string") {
  return {
    key: newKey(), name, source_header: sourceHeader, type,
    listEnabled: false, delimText: ";", delimNewline: false, delimTab: false, enumText: "",
    trueText: DEFAULT_TRUE.join("\n"), falseText: DEFAULT_FALSE.join("\n"),
    ref_document_id: "",
  };
}

export function toEdit(schema) {
  return {
    display_column: schema?.display_column || "",
    columns: (schema?.columns || []).map((c) => ({
      key: c.key,
      name: c.name,
      source_header: c.source_header,
      type: c.type,
      listEnabled: !!c.list,
      ...(c.list ? delimsToEdit(c.list.delimiters) : { delimText: ";", delimNewline: false, delimTab: false }),
      enumText: (c.enum_values || []).join("\n"),
      trueText: (c.bool_values?.true || DEFAULT_TRUE).join("\n"),
      falseText: (c.bool_values?.false || DEFAULT_FALSE).join("\n"),
      ref_document_id: c.ref_document_id || "",
    })),
  };
}

export function fromEdit(model) {
  return {
    display_column: model.display_column || null,
    columns: model.columns.map((c) => ({
      key: c.key,
      name: c.name.trim(),
      source_header: c.source_header || null,
      type: c.type,
      list: c.listEnabled && c.type !== "id" ? { delimiters: editToDelims(c) } : null,
      enum_values: c.type === "enum" ? lines(c.enumText) : null,
      bool_values: c.type === "bool" ? { true: lines(c.trueText), false: lines(c.falseText) } : null,
      ref_document_id: c.type === "string" && c.ref_document_id ? Number(c.ref_document_id) : null,
    })),
  };
}

export default {
  name: "SchemaEditor",
  props: {
    model: { type: Object, required: true },
    documents: { type: Array, default: () => [] },
    selfId: { type: Number, default: null },
    headers: { type: Array, default: null }, // 取り込み時のみ: ファイルのヘッダ一覧
  },
  emits: ["change"],
  setup(props, { emit }) {
    const types = Object.entries(TYPE_LABEL);

    function changed() {
      emit("change");
    }
    function add() {
      props.model.columns.push(newColumn("新しい列"));
      changed();
    }
    function remove(i) {
      props.model.columns.splice(i, 1);
      changed();
    }
    function move(i, d) {
      const cols = props.model.columns;
      const j = i + d;
      if (j < 0 || j >= cols.length) return;
      [cols[i], cols[j]] = [cols[j], cols[i]];
      changed();
    }
    function onTypeChange(col) {
      if (col.type === "id") {
        // ID 列は 1 つだけ。他の ID 列は文字列に戻す
        for (const c of props.model.columns) if (c !== col && c.type === "id") c.type = "string";
        col.listEnabled = false;
      }
      changed();
    }
    const otherDocs = () => props.documents.filter((d) => d.id !== props.selfId);
    const headerUsed = (h, col) => props.model.columns.some((c) => c !== col && c.source_header === h);
    const missing = (col) => props.headers && (!col.source_header || !props.headers.includes(col.source_header));

    return { types, add, remove, move, onTypeChange, otherDocs, headerUsed, missing, changed };
  },
  template: `
    <div class="schema-editor">
      <table class="grid compact">
        <thead>
          <tr>
            <th style="width:56px">順序</th>
            <th class="col-name">列名</th>
            <th v-if="headers" class="col-src">ファイルの列</th>
            <th style="width:110px">型</th>
            <th>詳細設定</th>
            <th style="width:60px"></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(col, i) in model.columns" :key="col.key" :class="{'row-missing': missing(col)}">
            <td class="nowrap">
              <button class="icon-btn" title="上へ" @click="move(i, -1)" :disabled="i === 0">↑</button>
              <button class="icon-btn" title="下へ" @click="move(i, 1)" :disabled="i === model.columns.length - 1">↓</button>
            </td>
            <td><input v-model="col.name" @input="changed" placeholder="列名"></td>
            <td v-if="headers">
              <select v-model="col.source_header" @change="changed">
                <option :value="null">（ファイルに無い）</option>
                <option v-for="h in headers" :key="h" :value="h">{{ h }}{{ headerUsed(h, col) ? '（他の列で使用中）' : '' }}</option>
              </select>
            </td>
            <td>
              <select v-model="col.type" @change="onTypeChange(col)">
                <option v-for="[v, label] in types" :key="v" :value="v">{{ label }}</option>
              </select>
            </td>
            <td class="detail-cell">
              <label v-if="col.type !== 'id'" class="check">
                <input type="checkbox" v-model="col.listEnabled" @change="changed"> リスト形式
              </label>
              <span v-if="col.listEnabled && col.type !== 'id'" class="delims">
                <label class="inline">
                  区切り文字 <input class="short" v-model="col.delimText" @input="changed" placeholder="例: ; ," title="スペース区切りで複数指定できます。空白そのものを区切りにする場合は \\s と書きます">
                </label>
                <label class="check"><input type="checkbox" v-model="col.delimNewline" @change="changed"> 改行</label>
                <label class="check"><input type="checkbox" v-model="col.delimTab" @change="changed"> タブ</label>
              </span>
              <label v-if="col.type === 'string'" class="inline">
                参照先
                <select v-model="col.ref_document_id" @change="changed">
                  <option value="">（参照 ID 列ではない）</option>
                  <option v-for="d in otherDocs()" :key="d.id" :value="d.id">{{ d.name }}</option>
                </select>
              </label>
              <div v-if="col.type === 'enum'" class="stack">
                <span class="sub">選択肢（1 行に 1 つ）</span>
                <textarea rows="3" v-model="col.enumText" @input="changed"></textarea>
              </div>
              <div v-if="col.type === 'bool'" class="bool-grid">
                <div><span class="sub">真とみなす文字列</span><textarea rows="3" v-model="col.trueText" @input="changed"></textarea></div>
                <div><span class="sub">偽とみなす文字列</span><textarea rows="3" v-model="col.falseText" @input="changed"></textarea></div>
              </div>
            </td>
            <td><button class="btn danger-ghost small" @click="remove(i)">削除</button></td>
          </tr>
        </tbody>
      </table>
      <div class="schema-footer">
        <button class="btn" @click="add">＋ 列を追加</button>
        <label class="inline">
          表示列
          <select v-model="model.display_column" @change="changed" title="ID と一緒に表示する列（リンク一覧や出力で使う）">
            <option value="">（自動: ID の次の列）</option>
            <option v-for="c in model.columns.filter(c => c.type !== 'id')" :key="c.key" :value="c.key">{{ c.name }}</option>
          </select>
        </label>
        <span class="sub">英字の大文字・小文字、全角・半角は区別せずに bool を判定します。</span>
      </div>
    </div>
  `,
};
