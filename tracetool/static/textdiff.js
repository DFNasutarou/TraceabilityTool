// 2 つの文字列の差分を文字単位で求め、変わった部分に印を付ける（差分画面のハイライト用）。

// これを超える組み合わせ（文字数の積）は計算量が大きいため、共通の先頭・末尾以外をまとめて「変更」とする
const MAX_CELLS = 2_000_000;

function merge(segs) {
  const out = [];
  for (const s of segs) {
    if (!s.text) continue;
    const last = out[out.length - 1];
    if (last && last.changed === s.changed) last.text += s.text;
    else out.push({ ...s });
  }
  return out;
}

/**
 * @returns {{old: {text: string, changed: boolean}[], new: {text: string, changed: boolean}[]}}
 */
export function diffSegments(a, b) {
  const x = Array.from(a ?? "");
  const y = Array.from(b ?? "");
  // 共通の先頭・末尾を除く
  let pre = 0;
  while (pre < x.length && pre < y.length && x[pre] === y[pre]) pre++;
  let suf = 0;
  while (suf < x.length - pre && suf < y.length - pre && x[x.length - 1 - suf] === y[y.length - 1 - suf]) suf++;
  const xa = x.slice(pre, x.length - suf);
  const ya = y.slice(pre, y.length - suf);
  const head = x.slice(0, pre).join("");
  const tail = x.slice(x.length - suf).join("");

  let oldMid;
  let newMid;
  if (xa.length * ya.length > MAX_CELLS) {
    oldMid = [{ text: xa.join(""), changed: true }];
    newMid = [{ text: ya.join(""), changed: true }];
  } else {
    // 最長共通部分列（LCS）で、共通の文字と変わった文字を分ける
    const n = xa.length;
    const m = ya.length;
    const w = m + 1;
    const dp = new Uint32Array((n + 1) * w);
    for (let i = n - 1; i >= 0; i--) {
      for (let j = m - 1; j >= 0; j--) {
        dp[i * w + j] = xa[i] === ya[j] ? dp[(i + 1) * w + j + 1] + 1 : Math.max(dp[(i + 1) * w + j], dp[i * w + j + 1]);
      }
    }
    oldMid = [];
    newMid = [];
    let i = 0;
    let j = 0;
    while (i < n && j < m) {
      if (xa[i] === ya[j]) {
        oldMid.push({ text: xa[i], changed: false });
        newMid.push({ text: ya[j], changed: false });
        i++;
        j++;
      } else if (dp[(i + 1) * w + j] >= dp[i * w + j + 1]) {
        oldMid.push({ text: xa[i++], changed: true });
      } else {
        newMid.push({ text: ya[j++], changed: true });
      }
    }
    while (i < n) oldMid.push({ text: xa[i++], changed: true });
    while (j < m) newMid.push({ text: ya[j++], changed: true });
  }
  return {
    old: merge([{ text: head, changed: false }, ...oldMid, { text: tail, changed: false }]),
    new: merge([{ text: head, changed: false }, ...newMid, { text: tail, changed: false }]),
  };
}
