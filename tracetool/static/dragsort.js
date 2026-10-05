// ドラッグ＆ドロップによる並べ替え（HTML5 の drag イベント）。
// 行の中の入力欄で文字を選べるよう、つまみ（handle）を押している間だけ行をドラッグできるようにする。
//
//   const sorter = dragSort(() => list, (from, to) => moveItem(list, from, to));
//   <tr :draggable="sorter.state.armed === i" @dragstart="sorter.start(i, $event)" @dragover="sorter.over(i, $event)"
//       @drop="sorter.drop(i, $event)" @dragend="sorter.end()" :class="sorter.rowClass(i)">
//     <td><span class="drag-handle" @mousedown="sorter.arm(i)" @mouseup="sorter.end()">⋮⋮</span></td>

const { reactive } = Vue;

export function moveItem(arr, from, to) {
  const [x] = arr.splice(from, 1);
  arr.splice(to, 0, x);
}

export function dragSort(onMove) {
  const state = reactive({ armed: null, from: null, over: null });
  return {
    state,
    arm(i) {
      state.armed = i;
      // つまみを押したまま行の外で離した場合も、行をドラッグできる状態のまま残さない
      document.addEventListener("mouseup", () => {
        if (state.from === null) state.armed = null;
      }, { once: true });
    },
    start(i, e) {
      if (state.armed !== i) {
        // 内側の並べ替え（列の中の enum の選択肢など）から伝わってきたドラッグは取り消さない
        if (e.target === e.currentTarget) e.preventDefault();
        return;
      }
      state.from = i;
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", String(i)); // Firefox はデータが無いとドラッグを始めない
    },
    over(i, e) {
      if (state.from === null) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      state.over = i;
    },
    drop(i, e) {
      if (state.from === null) return;
      e.preventDefault();
      const from = state.from;
      this.end();
      if (from !== i) onMove(from, i);
    },
    end() {
      state.armed = state.from = state.over = null;
    },
    rowClass(i) {
      return {
        dragging: state.from === i,
        "drop-before": state.over === i && state.from !== null && state.from > i,
        "drop-after": state.over === i && state.from !== null && state.from < i,
      };
    },
  };
}
