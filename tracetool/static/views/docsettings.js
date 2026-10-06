import { api, toast } from "../api.js";
import { href, navigate } from "../router.js";
import SchemaEditor, { toEdit, fromEdit } from "./schema-editor.js";

const { ref, onMounted } = Vue;

export default {
  components: { SchemaEditor },
  props: { docId: { type: Number, default: null } },
  setup(props) {
    const name = ref("");
    const description = ref("");
    const model = ref(toEdit(null));
    const documents = ref([]);
    const hasVersions = ref(false);
    const referencedBy = ref([]);
    const sample = ref(null); // レイアウトのプレビュー用（最新版の 1 つ目の項目）
    const saving = ref(false);

    const relations = ref([]);
    async function loadRelations() {
      relations.value = (await api.get("/api/relations")).map((r) => r.relation);
    }

    onMounted(async () => {
      documents.value = await api.get("/api/documents");
      await loadRelations();
      if (props.docId) {
        const d = await api.get(`/api/documents/${props.docId}`);
        name.value = d.name;
        description.value = d.description;
        model.value = toEdit(d.schema);
        hasVersions.value = !!d.latest_version_id;
        if (hasVersions.value) {
          sample.value = (await api.get(`/api/documents/${props.docId}/latest-items`)).items[0]?.data || null;
        }
        referencedBy.value = d.referenced_by || [];
      }
    });

    async function save() {
      saving.value = true;
      try {
        const body = { name: name.value, description: description.value, schema: fromEdit(model.value) };
        if (props.docId) {
          await api.put(`/api/documents/${props.docId}`, body);
          toast("保存しました");
        } else {
          const r = await api.post("/api/documents", body);
          toast("文書を作成しました。続けて表を取り込んでください");
          navigate(`/documents/${r.id}/import`);
        }
      } finally {
        saving.value = false;
      }
    }

    // 最新版で使われている値（「使われている値から enum を作る」用）
    async function loadValues(col) {
      const r = await api.get(`/api/documents/${props.docId}/distinct`, { key: col.key });
      return r.values;
    }

    async function createRelation({ upper, lower }) {
      await api.post("/api/relations", { upper_doc_id: upper, lower_doc_id: lower });
      toast("トレース関係を登録しました");
      await loadRelations();
    }

    async function remove() {
      const refs = referencedBy.value.length
        ? `\n次の文書の参照 ID 列は、参照先が「なし」に変わります: ${referencedBy.value.join("、")}`
        : "";
      if (!confirm(`文書「${name.value}」を削除します。\nすべての版、トレース関係、リンクも削除され、元に戻せません。${refs}\nよろしいですか？`)) return;
      await api.del(`/api/documents/${props.docId}`);
      toast("文書を削除しました");
      navigate("/");
    }

    return { sample, name, description, model, documents, relations, hasVersions, saving, save, remove, loadValues, createRelation, href };
  },
  template: `
    <section class="page">
      <div class="page-head">
        <h1>{{ docId ? '文書の設定' : '文書を追加' }}</h1>
        <div class="actions">
          <a class="btn" :href="href('/')">戻る</a>
          <button class="btn primary" :disabled="saving" @click="save">{{ docId ? '保存' : '作成して取り込みへ' }}</button>
        </div>
      </div>

      <div class="form-grid">
        <label>文書名<input v-model="name" placeholder="例: 要件定義書"></label>
        <label>説明<input v-model="description" placeholder="任意"></label>
      </div>

      <h2>カラム定義</h2>
      <p class="hint">
        ここで定義した列構成は、<b>次回の取り込み</b>で使われます（取り込み済みの版は変わりません）。
        列が未定義の場合は、取り込み時にファイルのヘッダから列を作ることもできます。
        <template v-if="hasVersions"><br>参照 ID 列の変更は、次回の取り込みからリンクに反映されます。</template>
      </p>
      <SchemaEditor :model="model" :documents="documents" :self-id="docId" :relations="relations"
                    :load-values="hasVersions ? loadValues : null" :sample="sample" @create-relation="createRelation" />
      <p v-if="hasVersions" class="hint">「使われている値から enum を作る」は、最新版で実際に使われている値を選択肢にします。変更は「保存」を押すと、次回の取り込みから適用されます。</p>

      <div v-if="docId" class="danger-zone">
        <button class="btn danger" @click="remove">この文書を削除</button>
      </div>
    </section>
  `,
};
