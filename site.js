// GPT-6.2 Preview — waterfall front-end (bilingual zh / en).
// Data source: data/cases.json (single source of truth, auto-maintained).
// English content uses title_en / summary_en when present, else falls back
// to the original fields. Layout: JS-managed flex columns — expanding a
// card's prompt only grows that card's own column (no global reflow).
(function () {
  var STR = {
    zh: {
      sub: 'GPT-6.2 灰度目击与社区实测案例索引 — 目击 · 演示 · 提示词',
      notice: '⚠️ GPT-6.2 尚未被 OpenAI 官方发布，以下均为灰度目击与社区报告，涵盖 Astra 与 Sol 两条线，模型归属以原帖作者标注为准。预览为原视频前 5 秒动图，完整内容见原帖；版权归各原作者所有。',
      repo: 'GitHub 仓库',
      submit: '📥 提交案例',
      pills: {
        all: '全部',
        demo_3d: '🧊 3D 与游戏演示',
        sighting: '🔍 灰度目击',
        signal: '📡 信号与讨论'
      },
      searchPh: '搜索标题 / 作者 / 技术栈…',
      count: function (total, shown) {
        return '共 ' + total + ' 条案例' + (shown !== total ? '（显示 ' + shown + ' 条）' : '');
      },
      time: '耗时 ',
      cost: '成本 ',
      viewPrompt: '查看 Prompt',
      origPost: '🔗 原推文',
      demo: '🕹️ 在线试玩',
      loading: '加载案例中…',
      empty: '没有符合条件的案例。',
      loadFail: function (m) { return '案例数据加载失败（' + m + '），请到 GitHub 仓库查看。'; },
      footer: '索引与整理以 MIT 发布；原帖内容与视频版权归各原作者所有。数据自动更新自 <a href="https://github.com/zqingdut/gpt6.2-preview/blob/main/data/cases.json" target="_blank" rel="noopener">data/cases.json</a>。',
      promptFallback: '未公开'
    },
    en: {
      sub: 'An index of GPT-6.2 gray-rollout sightings & community tests — sightings · demos · prompts',
      notice: '⚠️ GPT-6.2 has not been officially released by OpenAI. Everything here is gray-rollout sightings and community reports covering both the Astra and Sol lines; model attribution follows the labels given by the original authors. Previews are animated clips of the first 5 seconds; see the original post for the full piece. All content belongs to its authors.',
      repo: 'GitHub Repo',
      submit: '📥 Submit a Case',
      pills: {
        all: 'All',
        demo_3d: '🧊 3D & Game Demos',
        sighting: '🔍 Sightings',
        signal: '📡 Signals & Discussion'
      },
      searchPh: 'Search titles / authors / stack…',
      count: function (total, shown) {
        return total + ' cases' + (shown !== total ? ' (' + shown + ' shown)' : '');
      },
      time: 'Time ',
      cost: 'Cost ',
      viewPrompt: 'View Prompt',
      origPost: '🔗 Original Post',
      demo: '🕹️ Live Demo',
      loading: 'Loading cases…',
      empty: 'No cases match.',
      loadFail: function (m) { return 'Failed to load case data (' + m + '). Please check the GitHub repo.'; },
      footer: 'The index is MIT-licensed; posts and videos belong to their original authors. Data auto-updates from <a href="https://github.com/zqingdut/gpt6.2-preview/blob/main/data/cases.json" target="_blank" rel="noopener">data/cases.json</a>.',
      promptFallback: 'Not published'
    }
  };

  var grid = document.getElementById('grid');
  var countEl = document.getElementById('count');
  var searchEl = document.getElementById('search');
  var activeCat = 'all';
  var allCases = [];
  var lastColCount = 0;

  var lang = 'zh';
  try {
    var param = new URLSearchParams(window.location.search).get('lang');
    var saved = window.localStorage.getItem('g62s-lang');
    if (param === 'en' || param === 'zh') lang = param;
    else if (saved === 'en' || saved === 'zh') lang = saved;
  } catch (e) { /* keep default */ }

  function S() { return STR[lang]; }

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function fmtCost(v) {
    if (v === '' || v == null) return '';
    if (typeof v === 'number') return '$' + v;
    var s = String(v);
    if (s.charAt(0) === '~') return '~$' + s.slice(1);
    return s.indexOf('$') >= 0 ? s : '$' + s;
  }

  function colCount() {
    var w = grid.clientWidth || window.innerWidth;
    if (w >= 1000) return 3;
    if (w >= 640) return 2;
    return 1;
  }

  function pick(item, enField, field) {
    if (lang === 'en' && item[enField]) return item[enField];
    return item[field];
  }

  function cardHTML(item) {
    var s = S();
    var title = pick(item, 'title_en', 'title');
    var summary = pick(item, 'summary_en', 'summary');
    var metaBits = [esc(item.author), esc(item.created_at)];
    if (item.duration_sec) metaBits.push(esc(item.duration_sec) + 's');
    if (item.work_time) metaBits.push(s.time + esc(item.work_time));
    var cost = fmtCost(item.cost_usd);
    if (cost) metaBits.push(s.cost + esc(cost));

    var chips = (item.tech_stack || [])
      .map(function (t) { return '<span class="chip">' + esc(t) + '</span>'; })
      .join('');

    var demo = item.demo_url
      ? '<a href="' + esc(item.demo_url) + '" target="_blank" rel="noopener">' + s.demo + '</a>'
      : '';

    return (
      '<article class="card">' +
      (item.preview_webp
        ? '<img class="preview" loading="lazy" src="' + esc(item.preview_webp) + '" alt="' + esc(title) + '" />'
        : '') +
      '<div class="body">' +
      '<h3>' + esc(title) +
      (item.verification ? '<span class="badge">' + esc(item.verification) + '</span>' : '') +
      '</h3>' +
      '<div class="meta">' + metaBits.join(' · ') + '</div>' +
      '<p class="summary">' + esc(summary) + '</p>' +
      (chips ? '<div class="chips">' + chips + '</div>' : '') +
      '<button class="prompt-toggle" type="button" aria-expanded="false">' +
      '<span class="arrow">▸</span>' + s.viewPrompt + '</button>' +
      '<div class="prompt-wrap"><div class="prompt-inner"><pre>' +
      esc(item.prompt || s.promptFallback) +
      '</pre></div></div>' +
      '<div class="links">' +
      '<a href="' + esc(item.tweet_url) + '" target="_blank" rel="noopener">' + s.origPost + '</a>' +
      demo +
      '</div>' +
      '</div></article>'
    );
  }

  function render() {
    var s = S();
    var q = (searchEl.value || '').trim().toLowerCase();
    var rows = allCases.filter(function (c) {
      if (activeCat !== 'all' && c.category !== activeCat) return false;
      if (!q) return true;
      var hay = [c.title, c.title_en, c.author, c.summary, c.summary_en, (c.tech_stack || []).join(' ')]
        .join(' ')
        .toLowerCase();
      return hay.indexOf(q) >= 0;
    });

    countEl.textContent = s.count(allCases.length, rows.length);

    if (!rows.length) {
      grid.innerHTML = '<p class="empty">' + s.empty + '</p>';
      lastColCount = 0;
      return;
    }

    var n = colCount();
    lastColCount = n;
    grid.innerHTML = '';
    var cols = [];
    for (var i = 0; i < n; i++) {
      var col = document.createElement('div');
      col.className = 'col';
      grid.appendChild(col);
      cols.push(col);
    }
    rows.forEach(function (item) {
      var target = cols[0];
      for (var j = 1; j < cols.length; j++) {
        if (cols[j].offsetHeight < target.offsetHeight) target = cols[j];
      }
      var t = document.createElement('template');
      t.innerHTML = cardHTML(item).trim();
      target.appendChild(t.content.firstElementChild);
    });
  }

  function applyStatic() {
    var s = S();
    document.documentElement.lang = lang === 'en' ? 'en' : 'zh-CN';
    document.getElementById('heroSub').textContent = s.sub;
    document.getElementById('heroNotice').textContent = s.notice;
    document.getElementById('btnRepo').textContent = s.repo;
    document.getElementById('btnSubmit').textContent = s.submit;
    document.getElementById('footerText').innerHTML = s.footer;
    searchEl.placeholder = s.searchPh;
    document.querySelectorAll('.pill').forEach(function (p) {
      var cat = p.getAttribute('data-cat');
      if (s.pills[cat]) p.textContent = s.pills[cat];
    });
    document.getElementById('langZh').classList.toggle('active', lang === 'zh');
    document.getElementById('langEn').classList.toggle('active', lang === 'en');
    var lt = document.getElementById('loadingText');
    if (lt) lt.textContent = s.loading;
  }

  function setLang(next) {
    if (next !== 'zh' && next !== 'en') return;
    lang = next;
    try { window.localStorage.setItem('g62s-lang', lang); } catch (e) { /* ignore */ }
    applyStatic();
    render();
  }

  document.getElementById('langZh').addEventListener('click', function () { setLang('zh'); });
  document.getElementById('langEn').addEventListener('click', function () { setLang('en'); });

  grid.addEventListener('click', function (e) {
    var btn = e.target.closest('.prompt-toggle');
    if (!btn) return;
    var wrap = btn.parentElement.querySelector('.prompt-wrap');
    var open = wrap.classList.toggle('open');
    btn.setAttribute('aria-expanded', open ? 'true' : 'false');
  });

  document.getElementById('filters').addEventListener('click', function (e) {
    var btn = e.target.closest('.pill');
    if (!btn) return;
    document.querySelectorAll('.pill').forEach(function (p) { p.classList.remove('active'); });
    btn.classList.add('active');
    activeCat = btn.getAttribute('data-cat');
    render();
  });
  searchEl.addEventListener('input', render);

  var resizeTimer = null;
  window.addEventListener('resize', function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () {
      if (allCases.length && colCount() !== lastColCount) render();
    }, 150);
  });

  applyStatic();

  fetch('data/cases.json')
    .then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    })
    .then(function (data) {
      allCases = Array.isArray(data) ? data : [];
      render();
    })
    .catch(function (err) {
      grid.innerHTML = '<p class="empty">' + esc(S().loadFail(err.message)) + '</p>';
    });
})();
