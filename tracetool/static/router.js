// ハッシュ形式の簡易ルータ（#/documents/3/items?version=5）

const { reactive } = Vue;

export const route = reactive({ path: "/", parts: [], query: {} });

function parse() {
  const hash = location.hash.replace(/^#/, "") || "/";
  const [path, qs] = hash.split("?");
  route.path = path;
  route.parts = path.split("/").filter(Boolean);
  route.query = Object.fromEntries(new URLSearchParams(qs || ""));
}

window.addEventListener("hashchange", parse);
parse();

export function href(path, params) {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params || {})) {
    if (v !== undefined && v !== null && v !== "") q.append(k, v);
  }
  const s = q.toString();
  return "#" + path + (s ? "?" + s : "");
}

export function navigate(path, params) {
  location.hash = href(path, params).slice(1);
}

// 履歴を増やさずに query だけ書き換える
export function replaceQuery(params) {
  const merged = { ...route.query, ...params };
  history.replaceState(null, "", href(route.path, merged));
  parse();
}
