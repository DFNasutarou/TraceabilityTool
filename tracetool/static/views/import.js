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
    const fileInput = ref(null);
    const start = ref(null);
    // ステップ 2
    const encoding = ref("");
    const headerRow = ref(1);
    const sheets = ref([]);
    const preview = ref([]);
    // ステップ 3
    const settings = ref(null);
    const model = ref(toEdit(null));
    const validation = ref(null);
    const dirty = ref(true);
    const label = ref("");
    const tab = ref("errors");

    onMounted(async () => {
      [doc.value, documents.value] = await Promise.all([
        api.get(`/api/documents/${props.docId}`),
        api.get("/api/documents"),
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
      const f = fileInput.value?.files?.[0];
      if (!f) return;
      busy.value = true;
      try {
        await cancelSession();
        const fd = new FormData();
        fd.append("document_id", props.docId);
        fd.append("file", f);
        start.value = await api.post("/api/imports", fd);
        model.value = toEdit(null); // 別のファイルを選び直したら、定義の案を作り直す
        encoding.value = "";
        headerRow.value = 1;
        sheets.value = start.value.sheets.slice(0, 1);
        preview.value = start.value.preview;
        step.value = 2;
      } finally {
        busy.value = false;
      }
    }

    async function applySettings() {
      busy.value = true;
      try {
        settings.value = await api.put(`/api/imports/${start.value.session_id}/settings`, {
          encoding: encoding.value || null,
          header_row: Number(headerRow.value),
          sheets: sheets.value,
        });
        preview.value = settings.value.preview;
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
      const used = new Set(model.value.columns.map((c) => c.source_header));
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
    const maxCols = computed(() => Math.max(0, ...preview.value.map((r) => r.length)));

    return {
      doc, documents, step, busy, fileInput, start, encoding, headerRow, sheets, preview, settings, model,
      validation, dirty, label, tab, unmapped, previewCols, canCommit, maxCols,
      upload, applySettings, toStep3, addColumnFor, addAllUnmapped, onSchemaChange, validate, commit, cancel,
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
        <p>CSV / TSV / Excel（.xlsx）ファイルを選択してください。ファイルはこの PC 内のツールにだけ送られ、元ファイルは保存されません。</p>
        <div class="inline-form">
          <input type="file" ref="fileInput" accept=".csv,.tsv,.txt,.xlsx,.xlsm">
          <button class="btn primary" :disabled="busy" @click="upload">読み込む</button>
        </div>
      </div>

      <!-- ステップ 2 -->
      <div v-if="step === 2" class="card">
        <div class="inline-form">
          <span><b>{{ start.filename }}</b>（{{ start.format.toUpperCase() }}）</span>
          <label v-if="start.format !== 'xlsx'">文字コード
            <select v-model="encoding" @change="applySettings">
              <option value="">自動判定（{{ settings?.encoding || start.encoding }}）</option>
              <option value="utf-8-sig">UTF-8</option>
              <option value="cp932">Shift_JIS（CP932）</option>
            </select>
          </label>
          <label>ヘッダ行 <input type="number" min="1" class="short" v-model="headerRow"> 行目</label>
        </div>
        <div v-if="start.sheets.length" class="sheet-select">
          <span>取り込むシート（複数選択すると行を連結します。ヘッダは同じである必要があります）:</span>
          <label v-for="s in start.sheets" :key="s" class="check"><input type="checkbox" :value="s" v-model="sheets" @change="sheets.length && applySettings()"> {{ s }}</label>
        </div>
        <p class="hint">プレビュー（先頭 {{ preview.length }} 行）。色の付いた行がヘッダ行です。</p>
        <div class="scroll-x">
          <table class="grid compact raw">
            <tbody>
              <tr v-for="(row, i) in preview" :key="i" :class="{'header-row': i + 1 === Number(headerRow)}" @click="headerRow = i + 1" title="クリックでヘッダ行に指定">
                <th class="rownum">{{ i + 1 }}</th>
                <td v-for="c in maxCols" :key="c">{{ row[c - 1] }}</td>
              </tr>
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
          <SchemaEditor :model="model" :documents="documents" :self-id="docId" :headers="settings.headers" @change="onSchemaChange" />
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
                    <td v-for="c in previewCols" :key="c.key" :class="{invalid: it.invalid.includes(c.key)}">{{ fmtValue(it.data[c.key]) }}</td>
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
