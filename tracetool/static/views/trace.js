import { api, download, fmtPct, toast, STATUS_LABEL, ORIGIN_LABEL } from "../api.js";
import { href, navigate } from "../router.js";

const { ref, computed, onMounted } = Vue;

export default {
  props: { relId: { type: Number, default: null } },
  setup(props) {
    const relations = ref([]);
    const ev = ref(null);
    const tab = ref("upper");
    const checked = ref([]);

    async function load() {
      relations.value = await api.get("/api/relations");
      const id = props.relId || relations.value[0]?.relation.id;
      if (!id) return;
      if (!props.relId) {
        navigate(`/trace/${id}`);
        return;
      }
      ev.value = await api.get(`/api/trace/${id}`);
      checked.value = [];
    }
    onMounted(load);

    function selectRelation(e) {
      navigate(`/trace/${e.target.value}`);
    }

    async function ack(ids) {
      if (!ids.length) return;
      await api.post("/api/links/ack", { ids });
      toast(`${ids.length} 件を確認済みにしました`);
      load();
    }

    const allChecked = computed({
      get: () => ev.value && ev.value.suspect.length > 0 && checked.value.length === ev.value.suspect.length,
      set: (v) => (checked.value = v ? ev.value.suspect.map((l) => l.id) : []),
    });

    const itemHref = (docId, id) => href(`/documents/${docId}/items`, { item: id });

    return { relations, ev, tab, checked, allChecked, selectRelation, ack, itemHref, fmtPct, download, STATUS_LABEL, ORIGIN_LABEL };
  },
  template: `
    <section class="page">
      <div class="page-head">
        <h1>トレース状況</h1>
        <div class="actions" v-if="ev">
          <label class="inline">関係
            <select :value="relId" @change="selectRelation">
              <option v-for="r in relations" :key="r.relation.id" :value="r.relation.id">{{ r.upper_name }} → {{ r.lower_name }}</option>
            </select>
          </label>
        </div>
      </div>

      <p v-if="!relations.length" class="empty">トレース関係がありません。文書一覧で「上位文書 → 下位文書」を登録してください。</p>

      <template v-if="ev">
        <div class="stats">
          <div class="stat">
            <div class="stat-label">{{ ev.upper.name }}（上位）の網羅率</div>
            <div class="stat-value">{{ fmtPct(ev.upper.coverage) }}</div>
            <div class="sub">{{ ev.upper.total }} 項目中 下位なし {{ ev.upper.untraced.length }}</div>
          </div>
          <div class="stat">
            <div class="stat-label">{{ ev.lower.name }}（下位）の網羅率</div>
            <div class="stat-value">{{ fmtPct(ev.lower.coverage) }}</div>
            <div class="sub">{{ ev.lower.total }} 項目中 上位なし {{ ev.lower.untraced.length }}</div>
          </div>
          <div class="stat"><div class="stat-label">リンク</div><div class="stat-value">{{ ev.links.length }}</div></div>
          <div class="stat"><div class="stat-label">要確認</div><div class="stat-value" :class="{'warn-text': ev.suspect.length}">{{ ev.suspect.length }}</div></div>
          <div class="stat"><div class="stat-label">リンク切れ</div><div class="stat-value" :class="{'err-text': ev.broken.length}">{{ ev.broken.length }}</div></div>
        </div>

        <div class="inline-form">
          <span>出力:</span>
          <button class="btn" @click="download('/api/export/matrix', {relation: relId, format: 'xlsx'})">トレースマトリクス Excel</button>
          <button class="btn" @click="download('/api/export/matrix', {relation: relId, format: 'csv'})">CSV</button>
          <button class="btn" @click="download('/api/export/untraced', {relation: relId, format: 'xlsx'})">未トレース一覧 Excel</button>
          <button class="btn" @click="download('/api/export/untraced', {relation: relId, format: 'csv'})">CSV</button>
        </div>

        <div class="tabs">
          <button :class="{active: tab === 'upper'}" @click="tab = 'upper'">下位なし（{{ ev.upper.untraced.length }}）</button>
          <button :class="{active: tab === 'lower'}" @click="tab = 'lower'">上位なし（{{ ev.lower.untraced.length }}）</button>
          <button :class="{active: tab === 'broken'}" @click="tab = 'broken'">リンク切れ（{{ ev.broken.length }}）</button>
          <button :class="{active: tab === 'suspect'}" @click="tab = 'suspect'">要確認（{{ ev.suspect.length }}）</button>
          <button :class="{active: tab === 'links'}" @click="tab = 'links'">全リンク（{{ ev.links.length }}）</button>
        </div>

        <div v-if="tab === 'upper' || tab === 'lower'">
          <p class="hint" v-if="tab === 'upper'">{{ ev.upper.name }} の項目のうち、{{ ev.lower.name }} へのリンクが無いもの。</p>
          <p class="hint" v-else>{{ ev.lower.name }} の項目のうち、{{ ev.upper.name }} へのリンクが無いもの。</p>
          <table class="grid compact">
            <thead><tr><th>ID</th><th>表示列</th></tr></thead>
            <tbody>
              <tr v-for="id in ev[tab].untraced" :key="id">
                <td class="idcell"><a :href="itemHref(ev.relation[tab + '_doc_id'], id)">{{ id }}</a></td>
                <td>{{ ev[tab].labels[id] }}</td>
              </tr>
            </tbody>
          </table>
          <p v-if="!ev[tab].untraced.length" class="ok-text">該当する項目はありません。</p>
        </div>

        <div v-if="tab === 'broken' || tab === 'suspect' || tab === 'links'">
          <p class="hint" v-if="tab === 'broken'">リンク先の ID が最新版に存在しないリンク。参照 ID 列の誤記や、項目の削除が考えられます。</p>
          <p class="hint" v-if="tab === 'suspect'">リンクを確認した後に、どちらかの項目の内容（全列）が変わったリンク。内容を確認して「確認済み」にしてください。</p>
          <div class="inline-form" v-if="tab === 'suspect' && ev.suspect.length">
            <button class="btn primary" :disabled="!checked.length" @click="ack(checked)">選択した {{ checked.length }} 件を確認済みにする</button>
          </div>
          <table class="grid compact">
            <thead>
              <tr>
                <th v-if="tab === 'suspect'" style="width:32px"><input type="checkbox" v-model="allChecked"></th>
                <th>{{ ev.upper.name }}</th><th>表示列</th><th>{{ ev.lower.name }}</th><th>表示列</th><th>生成元</th><th>状態</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="l in (tab === 'links' ? ev.links : ev[tab])" :key="l.id">
                <td v-if="tab === 'suspect'"><input type="checkbox" :value="l.id" v-model="checked"></td>
                <td class="idcell">
                  <a v-if="l.upper_item_id in ev.upper.labels" :href="itemHref(ev.relation.upper_doc_id, l.upper_item_id)">{{ l.upper_item_id }}</a>
                  <span v-else class="err-text">{{ l.upper_item_id }}（存在しない）</span>
                </td>
                <td>{{ ev.upper.labels[l.upper_item_id] }}</td>
                <td class="idcell">
                  <a v-if="l.lower_item_id in ev.lower.labels" :href="itemHref(ev.relation.lower_doc_id, l.lower_item_id)">{{ l.lower_item_id }}</a>
                  <span v-else class="err-text">{{ l.lower_item_id }}（存在しない）</span>
                </td>
                <td>{{ ev.lower.labels[l.lower_item_id] }}</td>
                <td>{{ ORIGIN_LABEL[l.origin] }}</td>
                <td><span class="badge" :class="l.status">{{ STATUS_LABEL[l.status] }}</span></td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>
    </section>
  `,
};
