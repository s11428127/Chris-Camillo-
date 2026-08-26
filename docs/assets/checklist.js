/* 訊號窗口 · 五層檢查清單工具
   狀態只存在這台裝置的瀏覽器裡，不會上傳到任何地方。 */

(function () {
  'use strict';

  var KEY = 'signal-window-card-v1';
  var form = document.getElementById('cardform');
  if (!form) return;

  var fields = function () {
    return Array.prototype.slice.call(form.querySelectorAll('[data-f]'));
  };

  /* ---------- 讀寫 ---------- */

  function read() {
    var o = {};
    fields().forEach(function (el) {
      o[el.dataset.f] = el.type === 'checkbox' ? el.checked : el.value;
    });
    return o;
  }

  function write(o) {
    fields().forEach(function (el) {
      if (!(el.dataset.f in o)) return;
      if (el.type === 'checkbox') el.checked = !!o[el.dataset.f];
      else el.value = o[el.dataset.f];
    });
  }

  function save() {
    try {
      localStorage.setItem(KEY, JSON.stringify(read()));
      stamp('已存到這台裝置 · ' + new Date().toLocaleTimeString('zh-TW'));
    } catch (e) {
      stamp('這個瀏覽器不讓存草稿，記得自己複製走');
    }
  }

  function load() {
    try {
      var raw = localStorage.getItem(KEY);
      if (raw) write(JSON.parse(raw));
    } catch (e) { /* 讀不到就用空白表 */ }
  }

  function stamp(msg) {
    var el = document.getElementById('savedmark');
    if (el) el.textContent = msg;
  }

  /* ---------- 已知度計分 ---------- */

  function score() {
    var total = 0;
    form.querySelectorAll('[data-score]').forEach(function (sel) {
      var n = parseInt(sel.value, 10);
      if (!isNaN(n)) total += n;
    });
    return Math.min(total, 100);
  }

  function verdict(n) {
    if (n < 30) return { text: '窗口敞開 — 值得做', color: 'var(--good)' };
    if (n < 60) return { text: '部分反應 — 縮小部位或觀望', color: 'var(--warn)' };
    return { text: '已 price in — 丟掉這張卡', color: 'var(--bad)' };
  }

  function paintScore() {
    var n = score();
    var v = verdict(n);
    var valEl = document.getElementById('scoreval');
    var barEl = document.getElementById('scorebar');
    var verEl = document.getElementById('scoreverdict');
    if (valEl) { valEl.textContent = n; valEl.style.color = v.color; }
    if (barEl) { barEl.style.width = n + '%'; barEl.style.background = v.color; }
    if (verEl) { verEl.textContent = v.text; verEl.style.color = v.color; }
  }

  /* ---------- 退件狀態 ---------- */

  function paintLayers() {
    form.querySelectorAll('.layer').forEach(function (layer) {
      var sel = layer.querySelector('[data-kill]');
      var state = layer.querySelector('.state');
      var dead = sel && sel.value;
      layer.classList.toggle('dead', !!dead);
      if (state) {
        state.textContent = dead ? '❌ ' + sel.value : '';
      }
    });
  }

  /* ---------- 產生 Markdown ---------- */

  function killedAt() {
    var found = null;
    form.querySelectorAll('.layer').forEach(function (layer) {
      if (found) return;
      var sel = layer.querySelector('[data-kill]');
      if (sel && sel.value) {
        found = { layer: layer.dataset.layer, reason: sel.value };
      }
    });
    return found;
  }

  function line(label, val) {
    return '- ' + label + '：' + (val && String(val).trim() ? val : '（未填）');
  }

  function toMarkdown() {
    var d = read();
    var n = score();
    var dead = killedAt();
    var title = (d.ticker || '未填代號') + ' — ' + (d.headline || '未填標題');
    var out = [];

    out.push('# ' + title, '');
    out.push('狀態：' + (dead ? '❌ 已退件' : '紙上交易'));
    out.push('開卡日：' + (d.opened || new Date().toISOString().slice(0, 10)));
    out.push('到期日：' + (d.due || '（未填）'));
    out.push('');

    out.push('## 01 我看到什麼', '');
    out.push(d.seen || '（未填）', '');
    out.push(line('來源', d.source));
    out.push(line('人工觀察', d.human));
    out.push('');

    out.push('## 02 這是什麼性質的訊號', '');
    out.push(line('類型', d.sigtype));
    out.push(line('獨立來源數', d.sources_n));
    out.push(line('三個月前存在嗎', d.was_before));
    out.push('');

    out.push('## 03 映射', '');
    out.push(line('標的', d.ticker));
    out.push(line('營收曝險', d.exposure ? d.exposure + '%' : ''));
    out.push(line('財報出處', d.exposure_src));
    out.push(line('有沒有更純的標的', d.purer));
    out.push('');

    out.push('## 04 已知度分數：' + n + ' / 100', '');
    out.push(line('媒體報導', textOf('s_news')));
    out.push(line('分析師報告', textOf('s_analyst')));
    out.push(line('法說會', textOf('s_call')));
    out.push(line('股價近一個月', textOf('s_price')));
    out.push(line('判斷', verdict(n).text));
    out.push('');

    out.push('## 05 紀律', '');
    out.push('**為什麼法人看不到**：');
    out.push(d.blindspot || '（未填）', '');
    out.push('**什麼會證明我錯**：');
    out.push(d.falsify || '（未填）', '');
    out.push(line('假想部位', d.size ? d.size + '% NAV' : ''));
    out.push(line('進場價（紙上）', d.entry));
    out.push('');

    if (dead) {
      out.push('---', '');
      out.push('❌ **死因：' + dead.reason + '**（死在第 ' + dead.layer + ' 層）', '');
    } else {
      out.push('---', '');
      out.push('## 到期回顧（到期日再填）', '');
      out.push('- 結果：對 / 錯 / 不明');
      out.push('- 實際發生什麼：');
      out.push('- 如果錯，錯在哪一層：訊號 / 映射 / 濾網 / 時機');
      out.push('- 學到什麼：', '');
    }

    return out.join('\n');
  }

  function textOf(name) {
    var sel = form.querySelector('[data-f="' + name + '"]');
    if (!sel || !sel.selectedOptions || !sel.selectedOptions.length) return '';
    return sel.selectedOptions[0].textContent.trim();
  }

  function filename() {
    var d = read();
    var date = d.opened || new Date().toISOString().slice(0, 10);
    var slug = (d.ticker || 'card') + '-' + (d.headline || '').slice(0, 20);
    return date + '-' + slug.replace(/\s+/g, '-') + '.md';
  }

  /* ---------- 事件 ---------- */

  var t;
  form.addEventListener('input', function () {
    paintScore();
    paintLayers();
    clearTimeout(t);
    t = setTimeout(save, 600);
  });
  form.addEventListener('change', function () {
    paintScore();
    paintLayers();
    clearTimeout(t);
    t = setTimeout(save, 300);
  });

  document.getElementById('gen').addEventListener('click', function () {
    var box = document.getElementById('output');
    box.value = toMarkdown();
    document.getElementById('outwrap').hidden = false;
    document.getElementById('fname').textContent = filename();
    box.scrollIntoView({ block: 'nearest' });
  });

  document.getElementById('copy').addEventListener('click', function () {
    var box = document.getElementById('output');
    if (!box.value) box.value = toMarkdown();
    box.select();
    var ok = false;
    try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(box.value).then(function () {
        this.textContent = '已複製 ✓';
      }.bind(this), function () {});
    }
    this.textContent = ok ? '已複製 ✓' : '請手動選取複製';
    var btn = this;
    setTimeout(function () { btn.textContent = '複製 Markdown'; }, 2200);
  });

  document.getElementById('reset').addEventListener('click', function () {
    if (!confirm('清空整張卡，重新開始？這台裝置上的草稿會一起刪掉。')) return;
    try { localStorage.removeItem(KEY); } catch (e) {}
    form.reset();
    var d = form.querySelector('[data-f="opened"]');
    if (d) d.value = new Date().toISOString().slice(0, 10);
    document.getElementById('outwrap').hidden = true;
    document.getElementById('output').value = '';
    paintScore();
    paintLayers();
    stamp('已清空');
  });

  /* ---------- 起手 ---------- */

  load();
  var opened = form.querySelector('[data-f="opened"]');
  if (opened && !opened.value) opened.value = new Date().toISOString().slice(0, 10);
  paintScore();
  paintLayers();
})();
