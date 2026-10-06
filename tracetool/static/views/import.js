import { api, fmtValue, toast } from "../api.js";
import { href, navigate } from "../router.js";
import SchemaEditor, { toEdit, fromEdit, newColumn } from "./schema-editor.js";

const { ref, computed, onMounted, onBeforeUnmount } = Vue;

export default {
  components: { SchemaEditor },
  props: { docId: { type: Number, required: true } },
  setup(props) {
    const doc = ref(null);
    const documents = ref([]);
    const step = ref(1);
    const busy = ref(false);

    // ステップ 1
    const source = ref("file"); // file: ファイルを選ぶ / text: テキストを貼り付ける
    const fileInput = ref(null);
    const pasteText = ref("");
    const pasteFormat = ref("auto");
    const start = ref(null);
    const relations = ref([]);
    // ステップ 2
    const encoding = ref("");
    const headerRow = ref(1);
    const dataStart = ref(""); // 空ならヘッダ行の次
    const endMode = ref("all"); // all: 最後まで / row: 指定した行まで / blank: 最初の空行まで
    const dataEnd = ref("");
    const clickMode = ref("header"); // プレビューの行を押したときに指定するもの
    const sheets = ref([]);
    const preview = ref(null); // { sheet, rows: [{no, cells}], total, suggested_header_row }
    // ステップ 3
    const settings = ref(null);
    const model = ref(toEdit(null));
    const validation = ref(null);
    const dirty = ref(true);
    const label = ref("");
    const tab = ref("errors");

    async function loadRelations() {
      relations.value = (await api.get("/api/relations")).map((r) => r.relation);
    }

    onMounted(async () => {
      [doc.value, documents.value] = await Promise.all([
        api.get(`/api/documents/${props.docId}`),
        api.get("/api/documents"),
        loadRelations(),
      ]);
    });

    async function cancelSession() {
      if (start.value) {
        const sid = start.value.session_id;
        start.value = null;
        await api.del(`/api/imports/${sid}`).catch(() => {});
      }
    }
    onBeforeUnmount(() => {
      // 確定せずに画面を離れたら、メモリ上のファイルを破棄させる
      if (start.value) fetch(`/api/imports/${start.value.session_id}`, { method: "DELETE" });
    });

    async function upload() {
      busy.value = true;
      try {
        if (source.value === "file") {
          const f = fileInput.value?.files?.[0];
          if (!f) return;
          await cancelSession();
          const fd = new FormData();
          fd.append("document_id", props.docId);
          fd.append("file", f);
          start.value = await api.post("/api/imports", fd);
        } else {
          if (!pasteText.value.trim()) return;
          await cancelSession();
          start.value = await api.post("/api/imports/text", {
            document_id: props.docId, text: pasteText.value, format: pasteFormat.value,
          });
        }
        model.value = toEdit(null); // 別のファイルを選び直したら、定義の案を作り直す
        encoding.value = "";
        headerRow.value = start.value.suggested_header_row || 1;
        dataStart.value = "";
        endMode.value = "all";
        dataEnd.value = "";
        clickMode.value = "header";
        sheets.value = start.value.sheets.slice(0, 1);
        preview.value = start.value.sheet_preview;
        step.value = 2;
      } finally {
        busy.value = false;
      }
    }

    // プレビューは取り込みの設定とは別に読み込む（シートを切り替えたとき、設定に誤りがあっても表示できるように）
    async function loadPreview(sheet) {
      preview.value = await api.get(`/api/imports/${start.value.session_id}/preview`, {
        sheet: sheet ?? preview.value?.sheet, encoding: encoding.value,
      });
    }

    // 取り込むシートの選択を変えたら、選んだシートのプレビューに切り替える。
    // 1 枚だけを選んでいる場合は、そのシートで見出しの行を推定し直す
    async function onSheetToggle(e) {
      const s = e.target.value;
      if (e.target.checked) {
        await loadPreview(s);
        if (sheets.value.length === 1 && preview.value.suggested_header_row !== Number(headerRow.value)) {
          headerRow.value = preview.value.suggested_header_row;
          toast(`シート「${s}」の見出しの行を ${headerRow.value} 行目と推定しました`);
        }
      } else if (sheets.value.length && preview.value?.sheet === s) {
        await loadPreview(sheets.value[0]);
      }
    }

    function onPreviewRowClick(no) {
      if (clickMode.value === "header") headerRow.value = no;
      else if (clickMode.value === "start") dataStart.value = no;
      else {
        endMode.value = "row";
        dataEnd.value = no;
      }
    }
    const firstDataRow = computed(() => Number(dataStart.value) || Number(headerRow.value) + 1);
    const lastDataRow = computed(() => (endMode.value === "row" && Number(dataEnd.value) ? Number(dataEnd.value) : Infinity));
    function rowClass(no) {
      return {
        "header-row": no === Number(headerRow.value),
        "outside-row": no !== Number(headerRow.value) && (no < firstDataRow.value || no > lastDataRow.value),
        "range-start": no === firstDataRow.value,
        "range-end": no === lastDataRow.value,
      };
    }
    // プレビューの先頭と末尾の間で省略した行があれば、その位置に「…」の行を入れる
    const previewRows = computed(() => {
      const out = [];
      let prev = 0;
      for (const r of preview.value?.rows || []) {
        if (r.no > prev + 1 && prev > 0) out.push({ gap: r.no - prev - 1, no: `gap${r.no}` });
        out.push(r);
        prev = r.no;
      }
      return out;
    });

    async function applySettings() {
      busy.value = true;
      try {
        settings.value = await api.put(`/api/imports/${start.value.session_id}/settings`, {
          encoding: encoding.value || null,
          header_row: Number(headerRow.value),
          sheets: sheets.value,
          data_start: Number(dataStart.value) || null,
          data_end: endMode.value === "row" ? Number(dataEnd.value) || null : null,
          stop_at_blank: endMode.value === "blank",
        });
        return true;
      } catch {
        return false;
      } finally {
        busy.value = false;
      }
    }

    async function toStep3() {
      if (!(await applySettings())) return;
      if (model.value.columns.length) {
        // ステップ 3 で編集した定義は保ったまま、ファイルの列との対応付けだけを更新する
        const headers = settings.value.headers;
        const used = new Set();
        for (const c of model.value.columns) {
          if (c.source_header && headers.includes(c.source_header) && !used.has(c.source_header)) used.add(c.source_header);
          else c.source_header = null;
        }
        for (const c of model.value.columns) {
          if (!c.source_header && headers.includes(c.name) && !used.has(c.name)) {
            c.source_header = c.name;
            used.add(c.name);
          }
        }
      } else {
        model.value = toEdit(settings.value.schema);
      }
      validation.value = null;
      dirty.value = true;
      step.value = 3;
      validate();
    }

    const unmapped = computed(() => {
      if (!settings.value) return [];
      const used = new Set(model.value.columns.filter((c) => !(c.type === "id" && c.autoId)).map((c) => c.source_header));
      return settings.value.headers.filter((h) => !used.has(h));
    });

    function addColumnFor(h) {
      model.value.columns.push(newColumn(h, h));
      onSchemaChange();
    }
    function addAllUnmapped() {
      for (const h of unmapped.value) model.value.columns.push(newColumn(h, h));
      onSchemaChange();
    }
    function onSchemaChange() {
      dirty.value = true;
    }

    async function validate() {
      busy.value = true;
      try {
        validation.value = await api.put(`/api/imports/${start.value.session_id}/validate`, { schema: fromEdit(model.value) });
        dirty.value = false;
        tab.value = validation.value.error_count ? "errors" : validation.value.warning_count ? "warnings" : "preview";
      } catch {
        validation.value = null;
      } finally {
        busy.value = false;
      }
    }

    // 取り込み中のファイルで、列に使われている値（「使われている値から enum を作る」用）
    async function loadValues(col) {
      const column = fromEdit({ columns: [col] }).columns[0];
      const r = await api.put(`/api/imports/${start.value.session_id}/distinct`, { column });
      return r.values;
    }

    async function createRelation({ upper, lower }) {
      await api.post("/api/relations", { upper_doc_id: upper, lower_doc_id: lower });
      toast("トレース関係を登録しました");
      await loadRelations();
      if (validation.value) await validate();
    }

    async function commit() {
      busy.value = true;
      try {
        await api.post(`/api/imports/${start.value.session_id}/commit`, { schema: fromEdit(model.value), label: label.value });
        start.value = null;
        toast("取り込みました");
        navigate(`/documents/${props.docId}/items`);
      } finally {
        busy.value = false;
      }
    }

    async function cancel() {
      await cancelSession();
      navigate("/");
    }

    const previewCols = computed(() => (validation.value ? validation.value.schema.columns : []));
    const canCommit = computed(() => validation.value && !dirty.value && validation.value.error_count === 0 && !busy.value);
    const maxCols = computed(() => Math.max(0, ...(preview.value?.rows || []).map((r) => r.cells.length)));

    return {
      doc, documents, relations, step, busy, source, fileInput, pasteText, pasteFormat, start, encoding, headerRow, sheets, preview, settings, model,
      dataStart, endMode, dataEnd, clickMode, previewRows, rowClass, loadPreview, onSheetToggle, onPreviewRowClick,
      validation, dirty, label, tab, unmapped, previewCols, canCommit, maxCols,
      upload, applySettings, loadValues, createRelation, toStep3, addColumnFor, addAllUnmapped, onSchemaChange, validate, commit, cancel,
      href, fmtValue,
    };
  },
  template: `
    <section class="page" v-if="doc">
      <div class="page-head">
        <h1>取り込み: {{ doc.name }}</h1>
        <div class="actions"><button class="btn" @click="cancel">中止</button></div>
      </div>

      <ol class="steps">
        <li :class="{active: step === 1, done: step > 1}">1. ファイル選択</li>
        <li :class="{active: step === 2, done: step > 2}">2. 読み込み設定</li>
        <li :class="{active: step === 3}">3. 列の対応付けと検証</li>
      </ol>

      <!-- ステップ 1 -->
      <div v-if="step === 1" class="card">
        <div class="source-tabs">
          <button :class="{active: source === 'file'}" @click="source = 'file'">ファイルを選ぶ</button>
          <button :class="{active: source === 'text'}" @click="source = 'text'">テキストを貼り付ける</button>
        </div>
        <template v-if="source === 'file'">
          <p>CSV / TSV / Excel（.xlsx）ファイルを選択してください。ファイルはこの PC 内のツールにだけ送られ、元ファイルは保存されません。</p>
          <div class="inline-form">
            <input type="file" ref="fileInput" accept=".csv,.tsv,.txt,.xlsx,.xlsm">
            <button class="btn primary" :disabled="busy" @click="upload">読み込む</button>
          </div>
        </template>
        <template v-else>
          <p>CSV / TSV のテキストを貼り付けてください。Excel で表の範囲（見出しの行を含む）をコピーして貼り付けることもできます（タブ区切りとして読み込みます）。</p>
          <textarea class="paste-area" v-model="pasteText" placeholder="要件ID&#9;要件名&#10;REQ-001&#9;ログインできる"></textarea>
          <div class="inline-form">
            <label>形式
              <select v-model="pasteFormat">
                <option value="auto">自動判定（1 行目にタブがあれば TSV）</option>
                <option value="tsv">TSV（タブ区切り）</option>
                <option value="csv">CSV（カンマ区切り）</option>
              </select>
            </label>
            <button class="btn primary" :disabled="busy || !pasteText.trim()" @click="upload">読み込む</button>
          </div>
        </template>
      </div>

      <!-- ステップ 2 -->
      <div v-if="step === 2" class="card">
        <div class="inline-form">
          <span><b>{{ start.filename }}</b>（{{ start.format.toUpperCase() }}）</span>
          <label v-if="start.format !== 'xlsx' && !start.filename.startsWith('貼り付けた')">文字コード
            <select v-model="encoding" @change="loadPreview()">
              <option value="">自動判定（{{ preview?.encoding || start.encoding }}）</option>
              <option value="utf-8-sig">UTF-8</option>
              <option value="cp932">Shift_JIS（CP932）</option>
            </select>
          </label>
        </div>
        <div class="inline-form">
          <label>ヘッダ行 <input type="number" min="1" class="short" v-model="headerRow"> 行目</label>
          <label title="見出しとデータの間に説明の行などがある場合に指定します">データの開始行
            <input type="number" min="1" class="short" v-model="dataStart" :placeholder="String(Number(headerRow) + 1)"> 行目
          </label>
          <label>データの終わり
            <select v-model="endMode">
              <option value="all">最後の行まで</option>
              <option value="row">指定した行まで</option>
              <option value="blank">最初の空行の手前まで</option>
            </select>
          </label>
          <label v-if="endMode === 'row'"><input type="number" min="1" class="short" v-model="dataEnd"> 行目まで</label>
          <span class="sub" v-if="endMode === 'blank'">表の下の注記などが、空行で表と区切られている場合に使います（複数シートではシートごとに判定します）</span>
        </div>
        <div v-if="start.sheets.length" class="sheet-select">
          <span>取り込むシート（複数選択すると行を連結します。ヘッダは同じである必要があります）:</span>
          <label v-for="s in start.sheets" :key="s" class="check"><input type="checkbox" :value="s" v-model="sheets" @change="onSheetToggle"> {{ s }}</label>
        </div>
        <div v-if="start.sheets.length > 1" class="tabs">
          <span class="sub tab-label">プレビューするシート:</span>
          <button v-for="s in start.sheets" :key="s" :class="{active: preview?.sheet === s}" @click="loadPreview(s)">
            {{ s }}<span v-if="!sheets.includes(s)" class="sub">（取り込まない）</span>
          </button>
        </div>
        <div class="inline-form">
          <span class="sub">プレビューの行を押して指定:</span>
          <label class="check"><input type="radio" value="header" v-model="clickMode"> ヘッダ行</label>
          <label class="check"><input type="radio" value="start" v-model="clickMode"> データの開始行</label>
          <label class="check"><input type="radio" value="end" v-model="clickMode"> データの終了行</label>
        </div>
        <p class="hint" v-if="preview">
          プレビュー（全 {{ preview.total }} 行<template v-if="preview.total > preview.rows.length">。先頭と末尾の行だけを表示しています</template>）。
          色の付いた行がヘッダ行、灰色の行は取り込まない行です。
          <template v-if="start.suggested_header_row > 1">見出しの行を自動で推定し、{{ start.suggested_header_row }} 行目にしました。</template>
        </p>
        <div class="scroll-x" v-if="preview">
          <table class="grid compact raw">
            <tbody>
              <template v-for="row in previewRows" :key="row.no">
                <tr v-if="row.gap" class="gap-row"><td :colspan="maxCols + 1">… {{ row.gap }} 行を省略 …</td></tr>
                <tr v-else :class="rowClass(row.no)" @click="onPreviewRowClick(row.no)" title="クリックで指定">
                  <th class="rownum">{{ row.no }}</th>
                  <td v-for="c in maxCols" :key="c">{{ row.cells[c - 1] }}</td>
                </tr>
              </template>
            </tbody>
          </table>
        </div>
        <div class="actions end">
          <button class="btn" @click="step = 1">戻る</button>
          <button class="btn primary" :disabled="busy || (start.sheets.length && !sheets.length)" @click="toStep3">次へ</button>
        </div>
      </div>

      <!-- ステップ 3 -->
      <div v-if="step === 3">
        <div class="card">
          <p class="hint">
            ファイルの {{ settings.row_count }} 行を読み込みました。各列が「ファイルのどの列」から値を取るかを確認してください。
            この列構成は、この文書の次回以降の取り込みにも引き継がれます。
          </p>
          <SchemaEditor :model="model" :documents="documents" :self-id="docId" :headers="settings.headers"
                        :relations="relations" :load-values="loadValues" :sample="validation?.preview?.[0]?.data || null"
                        @change="onSchemaChange" @create-relation="createRelation" />
          <div v-if="unmapped.length" class="unmapped">
            <span>どの列にも対応付けられていないファイルの列:</span>
            <button v-for="h in unmapped" :key="h" class="chip" @click="addColumnFor(h)" title="列として追加">＋ {{ h }}</button>
            <button class="btn small" @click="addAllUnmapped">すべて列として追加</button>
            <span class="sub">（追加しない列は取り込まれません）</span>
          </div>
        </div>

        <div class="card">
          <div class="inline-form">
            <button class="btn" :disabled="busy" @click="validate">検証する</button>
            <span v-if="dirty && validation" class="warn-text">定義を変更しました。もう一度検証してください。</span>
            <template v-if="validation && !dirty">
              <span :class="validation.error_count ? 'err-text' : 'ok-text'">エラー {{ validation.error_count }} 件</span>
              <span :class="{'warn-text': validation.warning_count}">警告 {{ validation.warning_count }} 件</span>
              <span>取り込み対象 {{ validation.item_count }} 行</span>
            </template>
          </div>

          <template v-if="validation">
            <div class="tabs">
              <button :class="{active: tab === 'errors'}" @click="tab = 'errors'">エラー（{{ validation.error_count }}）</button>
              <button :class="{active: tab === 'warnings'}" @click="tab = 'warnings'">警告（{{ validation.warning_count }}）</button>
              <button :class="{active: tab === 'preview'}" @click="tab = 'preview'">プレビュー</button>
            </div>
            <div class="scroll-y">
              <table v-if="tab !== 'preview'" class="grid compact">
                <thead><tr><th>行</th><th>列</th><th>内容</th></tr></thead>
                <tbody>
                  <tr v-for="(m, i) in (tab === 'errors' ? validation.errors : validation.warnings)" :key="i">
                    <td class="nowrap">{{ m.row }}</td><td class="nowrap">{{ m.column }}</td><td>{{ m.message }}</td>
                  </tr>
                </tbody>
              </table>
              <p v-if="tab !== 'preview' && (tab === 'errors' ? validation.error_count : validation.warning_count) > 1000" class="sub">先頭 1,000 件を表示しています。</p>
              <table v-if="tab === 'preview'" class="grid compact">
                <thead><tr><th v-for="c in previewCols" :key="c.key">{{ c.name }}</th></tr></thead>
                <tbody>
                  <tr v-for="it in validation.preview" :key="it.item_id">
                    <td v-for="c in previewCols" :key="c.key" :class="{invalid: it.invalid.includes(c.key)}">{{ fmtValue(it.data[c.key], c) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </template>
        </div>

        <div class="card inline-form">
          <label>版のラベル <input v-model="label" placeholder="例: 第3版 / 2026-10-03 受領"></label>
          <button class="btn" @click="step = 2">戻る</button>
          <button class="btn primary" :disabled="!canCommit" @click="commit">取り込む</button>
          <span v-if="validation && validation.error_count" class="err-text">エラーを解消するまで取り込めません。</span>
        </div>
      </div>
    </section>
  `,
};
