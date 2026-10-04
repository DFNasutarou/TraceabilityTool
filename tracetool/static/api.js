// API 呼び出しと、画面共通の小さな部品

const { reactive } = Vue;

export const toasts = reactive([]);
let toastSeq = 0;

export function toast(message, kind = "info") {
  const id = ++toastSeq;
  toasts.push({ id, message, kind });
  setTimeout(() => {
    const i = toasts.findIndex((t) => t.id === id);
    if (i >= 0) toasts.splice(i, 1);
  }, kind === "error" ? 8000 : 3000);
}

async function request(method, url, body) {
  const opts = { method, headers: {} };
  if (body instanceof FormData) {
    opts.body = body;
  } else if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(url, opts);
  } catch (e) {
    toast("サーバに接続できません。ツールが起動しているか確認してください", "error");
    throw e;
  }
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const message = data?.error?.message || `エラーが発生しました（${res.status}）`;
    toast(message, "error");
    throw new Error(message);
  }
  return data;
}

export const api = {
  get: (url, params) => request("GET", url + query(params)),
  post: (url, body) => request("POST", url, body ?? {}),
  put: (url, body) => request("PUT", url, body ?? {}),
  del: (url) => request("DELETE", url),
};

export function query(params) {
  if (!params) return "";
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") q.append(k, v);
  }
  const s = q.toString();
  return s ? "?" + s : "";
}

// 出力ファイルをダウンロードする。押したことが分かるよう、開始・完了・エラーを通知する
export async function download(url, params) {
  toast("出力ファイルを作成しています…");
  let res;
  try {
    res = await fetch(url + query(params));
  } catch (e) {
    toast("サーバに接続できません。ツールが起動しているか確認してください", "error");
    return;
  }
  if (!res.ok) {
    const data = await res.json().catch(() => null);
    toast(data?.error?.message || `出力に失敗しました（${res.status}）`, "error");
    return;
  }
  const blob = await res.blob();
  const filename = filenameFrom(res.headers.get("Content-Disposition")) || "export";
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 10000);
  toast(`ダウンロードしました: ${filename}（ブラウザのダウンロード先に保存されます）`);
}

function filenameFrom(disposition) {
  if (!disposition) return null;
  const star = disposition.match(/filename\*=UTF-8''([^;]+)/i);
  if (star) return decodeURIComponent(star[1]);
  const plain = disposition.match(/filename="([^"]+)"/i);
  return plain ? plain[1] : null;
}

// --- 値の表示 ---------------------------------------------------------------

export function fmtValue(value) {
  if (value === null || value === undefined) return "";
  if (value === true) return "○";
  if (value === false) return "×";
  if (Array.isArray(value)) return value.map(fmtValue).join(", ");
  return String(value);
}

export function fmtPct(v) {
  return v === null || v === undefined ? "-" : (v * 100).toFixed(1) + "%";
}

export function fmtDate(iso) {
  return iso ? iso.replace("T", " ") : "";
}

export const STATUS_LABEL = { ok: "正常", suspect: "要確認", broken: "リンク切れ" };
export const ORIGIN_LABEL = { manual: "手動", auto: "自動" };
export const TYPE_LABEL = { id: "ID", int: "番号", string: "文字列", enum: "enum", bool: "bool" };
