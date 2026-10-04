// カラム定義の編集部品。文書の設定画面と、取り込みの列対応付け画面で使う。
// 編集用のモデル（toEdit で作る）を直接書き換える。保存時は fromEdit で API の形に戻す。

import { TYPE_LABEL, toast } from "../api.js";

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
    relations: { type: Array, default: () => [] }, // トレース関係の一覧（参照 ID 列の確認に使う）
    // 列に使われている値を返す関数（col → Promise<string[]>）。指定すると「値から enum を作る」ボタンを出す
    loadValues: { type: Function, default: null },
  },
  emits: ["change", "create-relation"],
  setup(props, { emit }) {
    const types = Object.entries(TYPE_LABEL);

    function changed() {
      emit("change");
    }
    // --- 列をまとめて追加（列名のテキストを貼り付け、区切り文字で分割する） ---
    const bulkOpen = Vue.ref(false);
    const bulkText = Vue.ref("");
    const bulkDelim = Vue.ref("auto"); // auto / tab / comma / newline / custom
    const bulkCustom = Vue.ref("");

    function splitNames(text) {
      let d = bulkDelim.value;
      if (d === "auto") d = text.includes("\t") ? "tab" : /\r?\n/.test(text.trim()) ? "newline" : "comma";
      const sep = { tab: /\t|\r?\n/, comma: /,|\r?\n/, newline: /\r?\n/ }[d] || bulkCustom.value;
      if (!sep) return [];
      return text.split(sep).map((t) => t.trim()).filter(Boolean);
    }
    const bulkPreview = Vue.computed(() => splitNames(bulkText.value));

    function addBulk() {
      const existing = new Set(props.model.columns.map((c) => c.name));
      const added = [];
      const skipped = [];
      for (const name of bulkPreview.value) {
        if (existing.has(name)) {
          skipped.push(name);
          continue;
        }
        existing.add(name);
        // 取り込み画面では、同じ名前のファイルの列があれば対応付ける
        const src = props.headers && props.headers.includes(name) ? name : null;
        props.model.columns.push(newColumn(name, src));
        added.push(name);
      }
      if (added.length) changed();
      toast(`${added.length} 列を追加しました` + (skipped.length ? `（同じ名前の列があるため ${skipped.length} 列は追加しませんでした: ${skipped.join("、")}）` : ""));
      if (added.length) {
        bulkText.value = "";
        bulkOpen.value = false;
      }
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
    const docName = (id) => props.documents.find((d) => d.id === Number(id))?.name || "";
    // 参照先との間にトレース関係があるか（参照 ID 列は関係が無いと取り込めない）
    const hasRelation = (refId) =>
      props.relations.some(
        (r) =>
          (r.upper_doc_id === props.selfId && r.lower_doc_id === Number(refId)) ||
          (r.lower_doc_id === props.selfId && r.upper_doc_id === Number(refId))
      );
    function createRelation(col, refIsUpper) {
      const ref = Number(col.ref_document_id);
      emit("create-relation", refIsUpper ? { upper: ref, lower: props.selfId } : { upper: props.selfId, lower: ref });
    }

    const loadingValues = Vue.ref(null);
    async function toEnum(col) {
      loadingValues.value = col.key;
      try {
        const values = await props.loadValues(col);
        if (!values.length) {
          toast(`「${col.name}」列には値がありません`, "error");
          return;
        }
        // 確認ダイアログは出さず、結果を通知する（選択肢は欄で確認・修正でき、型も戻せる）
        toast(`「${col.name}」列を enum にしました（${values.length} 種類の値を選択肢にしました）`);
        col.type = "enum";
        col.ref_document_id = "";
        col.enumText = values.join("\n");
        changed();
      } catch {
        // エラーは api.js がトースト表示する
      } finally {
        loadingValues.value = null;
      }
    }
    const headerUsed = (h, col) => props.model.columns.some((c) => c !== col && c.source_header === h);
    const missing = (col) => props.headers && (!col.source_header || !props.headers.includes(col.source_header));

    return {
      types, add, remove, move, onTypeChange, otherDocs, headerUsed, missing, changed,
      bulkOpen, bulkText, bulkDelim, bulkCustom, bulkPreview, addBulk,
      docName, hasRelation, createRelation, loadingValues, toEnum,
    };
  },
  template: `
    <div class="schema-editor">
      <table class="grid compact">
        <thead>
          <tr>
            <th style="width:56px">順序</th>
            <th class="col-name">列名</th>
            <th v-if="headers" class="col-src">ファイルの列</th>
            <th class="col-type">型</th>
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
              <div v-if="col.type === 'string' && col.ref_document_id && !hasRelation(col.ref_document_id)" class="relation-warn">
                <template v-if="selfId">
                  「{{ docName(col.ref_document_id) }}」との間にトレース関係がありません（関係が無いと取り込めません）。
                  <button class="btn small primary" @click="createRelation(col, true)">関係を登録（{{ docName(col.ref_document_id) }} を上位にする）</button>
                  <button class="btn small" @click="createRelation(col, false)">下位にする</button>
                </template>
                <template v-else>文書を作成した後、「{{ docName(col.ref_document_id) }}」との間にトレース関係を登録してください。</template>
              </div>
              <div v-if="col.type === 'enum'" class="stack">
                <span class="sub">選択肢（1 行に 1 つ）</span>
                <textarea rows="3" v-model="col.enumText" @input="changed"></textarea>
              </div>
              <button v-if="loadValues && (col.type === 'string' || col.type === 'enum') && !col.ref_document_id"
                      class="btn small" :disabled="loadingValues === col.key" @click="toEnum(col)"
                      title="この列で実際に使われている値だけを選択肢にして、enum に変換します">
                {{ col.type === 'enum' ? '使われている値で選択肢を作り直す' : '使われている値から enum を作る' }}
              </button>
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
        <button class="btn" @click="bulkOpen = !bulkOpen">＋ 列をまとめて追加</button>
        <label class="inline">
          表示列
          <select v-model="model.display_column" @change="changed" title="ID と一緒に表示する列（リンク一覧や出力で使う）">
            <option value="">（自動: ID の次の列）</option>
            <option v-for="c in model.columns.filter(c => c.type !== 'id')" :key="c.key" :value="c.key">{{ c.name }}</option>
          </select>
        </label>
        <span class="sub">英字の大文字・小文字、全角・半角は区別せずに bool を判定します。</span>
      </div>
      <div v-if="bulkOpen" class="bulk-add">
        <p class="hint">列名を区切り文字で区切って貼り付けてください。Excel の見出しの行をコピーして貼り付けることもできます（タブ区切り）。追加した列は文字列型になります。</p>
        <textarea rows="3" v-model="bulkText" placeholder="要件ID&#9;要件名&#9;優先度"></textarea>
        <div class="inline-form">
          <label>区切り文字
            <select v-model="bulkDelim">
              <option value="auto">自動判定</option>
              <option value="tab">タブ</option>
              <option value="comma">カンマ（,）</option>
              <option value="newline">改行</option>
              <option value="custom">その他</option>
            </select>
          </label>
          <input v-if="bulkDelim === 'custom'" class="short" v-model="bulkCustom" placeholder="例: ;">
          <span class="sub">{{ bulkPreview.length }} 列: {{ bulkPreview.slice(0, 10).join(' / ') }}{{ bulkPreview.length > 10 ? ' …' : '' }}</span>
          <button class="btn primary" :disabled="!bulkPreview.length" @click="addBulk">追加する</button>
        </div>
      </div>
    </div>
  `,
};
