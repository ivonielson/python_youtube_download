'use strict';

/* ── Utils ──────────────────────────────────────────────────────────────── */
function escHtml(s) {
  return (s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

/* ── Toast ──────────────────────────────────────────────────────────────── */
const Toast = {
  show(msg, type = 'info', ms = 3500) {
    const c = document.getElementById('toast-container');
    const el = document.createElement('div');
    el.className = `toast toast-${type}`;
    el.textContent = msg;
    c.appendChild(el);
    requestAnimationFrame(() => el.classList.add('show'));
    setTimeout(() => {
      el.classList.remove('show');
      setTimeout(() => el.remove(), 300);
    }, ms);
  },
};

/* ── App ────────────────────────────────────────────────────────────────── */
const App = (() => {
  const state = {
    type: null, url: '', urls: [], metadata: [],
    formats: [], selectedFmt: null,
    jobId: null, evtSource: null, analyzeEs: null,
    completedItems: new Map(),
  };

  const $ = (id) => document.getElementById(id);

  /* ── Alert ─────────────────────────────────────────────────────────────── */
  function _alert(msg, kind = 'danger') {
    const el = $('alert');
    el.className = `alert alert-${kind}`;
    el.textContent = msg;
    el.style.display = 'block';
    setTimeout(() => { el.style.display = 'none'; }, 5000);
  }
  function _clearAlert() { $('alert').style.display = 'none'; }

  /* ── Loading states ────────────────────────────────────────────────────── */
  function _setAnalyzeLoading(on) {
    const btn = $('analyzeBtn');
    btn.disabled = on;
    btn.innerHTML = on ? '<span class="spinner"></span>Analisando…' : 'Analisar';
  }
  function _setDlLoading(on) {
    $('dlBtn').disabled = on;
    $('dlBtn').innerHTML = on ? '<span class="spinner"></span>Processando…' : '⬇ Processar Links';
    $('cancelBtn').style.display = on ? 'block' : 'none';
  }

  /* ── Checkbox helpers ──────────────────────────────────────────────────── */
  function _updateSelectedCount() {
    const all     = document.querySelectorAll('.playlist-item-check');
    const checked = document.querySelectorAll('.playlist-item-check:checked');
    const selAll  = $('selectAllCheck');
    selAll.indeterminate = checked.length > 0 && checked.length < all.length;
    selAll.checked       = all.length > 0 && checked.length === all.length;
    $('selectedCount').textContent = `${checked.length} de ${all.length} selecionado${checked.length !== 1 ? 's' : ''}`;
    if (state.type === 'playlist' && state.selectedFmt) {
      $('dlBtn').disabled = checked.length === 0;
    }
  }

  /* ── UI Reset ──────────────────────────────────────────────────────────── */
  function _reset() {
    $('videoStrip').style.display     = 'none';
    $('videoWatchBtn').style.display  = 'none';
    $('playlistHeader').style.display = 'none';
    $('playlistScroll').style.display = 'none';
    $('playlistScroll').innerHTML     = '';
    $('formatSection').style.display  = 'none';
    $('formatGrid').innerHTML         = '';
    $('completedGrid').innerHTML      = '';
    $('completedList').style.display  = 'none';
    $('progressWrap').style.display   = 'none';
    $('selectAllCheck').checked       = false;
    $('selectAllCheck').indeterminate = false;
    $('selectedCount').textContent    = '';
    if (state.evtSource)  { state.evtSource.close();  state.evtSource  = null; }
    if (state.analyzeEs)  { state.analyzeEs.close();  state.analyzeEs  = null; }
    Object.assign(state, {
      type: null, url: '', urls: [], metadata: [], formats: [],
      selectedFmt: null, jobId: null, evtSource: null, analyzeEs: null,
      completedItems: new Map(),
    });
  }

  function _isPlaylistUrl(url) {
    const radio = [/list=RD/i, /list=WL/i, /list=LL/i, /list=HL/i, /list=LM/i, /start_radio=1/i];
    if (radio.some(p => p.test(url))) return false;
    return [/list=PL/i, /list=OL/i, /list=UU/i, /list=FL/i, /\/playlist\?list=/i].some(p => p.test(url));
  }

  /* ── Analyze ───────────────────────────────────────────────────────────── */
  async function analyze() {
    const url = $('urlInput').value.trim();
    if (!url) { _alert('Cole uma URL antes de continuar.', 'warn'); return; }
    _clearAlert();
    _reset();
    state.url = url;

    if (_isPlaylistUrl(url)) { _analyzePlaylist(url); return; }

    _setAnalyzeLoading(true);
    try {
      const d = await API.analyze(url);
      if (!d.success) { _alert(d.detail || d.error || 'Erro desconhecido.'); return; }
      state.type = d.type;
      state.formats = d.formats;
      if (d.type === 'video') _renderVideo(d); else _renderPlaylist(d);
      _renderFormats(d.formats);
      $('formatSection').style.display = 'block';
      $('dlBtn').disabled = true;
    } catch (e) {
      _alert('Falha na conexão: ' + e.message);
    } finally {
      _setAnalyzeLoading(false);
    }
  }

  function _analyzePlaylist(url) {
    _setAnalyzeLoading(true);
    state.type = 'playlist';
    state.urls = []; state.metadata = [];
    const scroll = $('playlistScroll');
    scroll.innerHTML = '<div class="playlist-analyzing"><span class="spinner"></span>Buscando vídeos…</div>';
    scroll.style.display = 'block';
    $('playlistHeader').style.display = 'block';
    $('playlistTitle').textContent = '…';
    $('playlistCount').textContent = 'aguardando…';

    state.analyzeEs = API.analyzePlaylist(url, {
      onHeader(d) {
        state.formats = d.formats;
        $('playlistTitle').textContent = d.title;
        $('playlistCount').textContent = `0 / ${d.count} vídeos`;
        scroll.querySelector('.playlist-analyzing')?.remove();
      },
      onItem(d) {
        state.urls.push(d.url);
        state.metadata.push({ title: d.title, thumbnail: d.thumbnail, duration: d.duration, index: d.index });
        _appendItem(d, scroll);
        $('playlistCount').textContent = `${state.urls.length} / ${state.metadata.length} vídeos`;
      },
      onDone() {
        _setAnalyzeLoading(false);
        state.analyzeEs = null;
        $('playlistCount').textContent = `${state.urls.length} vídeos`;
        _renderFormats(state.formats);
        $('formatSection').style.display = 'block';
        $('dlBtn').disabled = true;
      },
      onError(msg) {
        _setAnalyzeLoading(false);
        state.analyzeEs = null;
        scroll.style.display = 'none';
        $('playlistHeader').style.display = 'none';
        _alert(msg || 'Erro ao analisar playlist.');
      },
    });
  }

  function _appendItem(item, scroll) {
    const ph = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='80' height='45'%3E%3Crect width='80' height='45' fill='%2326262e'/%3E%3Ctext x='40' y='28' text-anchor='middle' fill='%236b6b80' font-size='12'%3E%F0%9F%8E%B5%3C/text%3E%3C/svg%3E";
    const idx = state.urls.length - 1;
    const div = document.createElement('div');
    div.className = 'playlist-item playlist-item-new';
    div.innerHTML = `
      <input type="checkbox" class="playlist-item-check" data-index="${idx}" checked />
      <img class="playlist-item-thumb" src="${item.thumbnail || ph}" alt=""
           onerror="this.src='${ph}'" />
      <div class="playlist-item-info">
        <div class="playlist-item-title"><strong>${item.index}.</strong> ${escHtml(item.title)}</div>
        <div class="playlist-item-dur">⏱ ${item.duration || '–'}</div>
      </div>
      <button class="btn-sm btn-play-sm playlist-item-play" title="Assistir">▶</button>`;
    div.querySelector('.playlist-item-check').addEventListener('change', _updateSelectedCount);
    div.querySelector('.playlist-item-play').addEventListener('click', () =>
      Player.openYoutube(item.url, item.title));
    scroll.appendChild(div);
    _updateSelectedCount();
    if (scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight < 120)
      scroll.scrollTop = scroll.scrollHeight;
  }

  function _renderVideo(d) {
    $('typeBadge').textContent = '🎬 VÍDEO';
    $('typeBadge').className = 'badge badge-red';
    $('videoTitle').textContent = d.title;
    $('videoDuration').textContent = '⏱ ' + d.duration;
    const img = $('thumbImg');
    if (d.thumbnail) {
      img.src = d.thumbnail; img.style.display = '';
      img.onerror = () => { img.style.display = 'none'; };
    } else { img.style.display = 'none'; }
    $('videoStrip').style.display = 'flex';

    const btn = $('videoWatchBtn');
    btn.style.display = 'inline-flex';
    btn.onclick = () => Player.openYoutube(state.url, d.title);
  }

  function _renderPlaylist(d) {
    $('playlistTitle').textContent = d.title;
    $('playlistCount').textContent = `${d.count} vídeos`;
    $('playlistHeader').style.display = 'block';
    const scroll = $('playlistScroll');
    scroll.innerHTML = '';
    scroll.style.display = 'block';
    state.urls = []; state.metadata = [];
    (d.items || []).forEach((item, i) => {
      state.urls.push(item.url);
      state.metadata.push({ title: item.title, thumbnail: item.thumbnail, duration: item.duration, index: i + 1 });
      _appendItem(item, scroll);
    });
  }

  function _renderFormats(formats) {
    const grid = $('formatGrid');
    grid.innerHTML = '';
    formats.forEach((fmt, i) => {
      const btn = document.createElement('button');
      btn.className = 'format-btn' + (fmt.id === 'mp3' ? ' mp3-btn' : '');
      btn.textContent = fmt.label;
      btn.onclick = () => _selectFormat(fmt, btn);
      grid.appendChild(btn);
      if (i === 0) _selectFormat(fmt, btn);
    });
  }

  function _selectFormat(fmt, btn) {
    document.querySelectorAll('.format-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    state.selectedFmt = fmt;
    const dlBtn = $('dlBtn');
    dlBtn.disabled = false;
    if (fmt.id === 'mp3') {
      dlBtn.textContent = '🎵 Processar (MP3)';
      dlBtn.style.background = 'var(--blue)';
    } else {
      dlBtn.textContent = '⬇ Processar (Vídeo)';
      dlBtn.style.background = '';
    }
  }

  /* ── Download ──────────────────────────────────────────────────────────── */
  async function startDownload() {
    if (!state.selectedFmt) { _alert('Selecione um formato.', 'warn'); return; }

    let downloadUrls = state.urls;
    let downloadMeta = state.metadata;

    if (state.type === 'playlist') {
      const indices = [...document.querySelectorAll('.playlist-item-check:checked')]
        .map(cb => parseInt(cb.dataset.index));
      if (!indices.length) { _alert('Selecione ao menos um vídeo.', 'warn'); return; }
      downloadUrls = indices.map(i => state.urls[i]);
      downloadMeta = indices.map(i => state.metadata[i]);
    }

    _clearAlert();
    _setDlLoading(true);
    $('progressWrap').style.display = 'block';
    $('completedList').style.display = 'block';
    _updateProgress(0, 'Iniciando download…');
    state.completedItems.clear();
    $('completedGrid').innerHTML = '';

    const body = {
      url: state.url,
      format_id: state.selectedFmt.id,
      ...(state.type === 'playlist' && downloadUrls.length
        ? { urls: downloadUrls, video_metadata: downloadMeta }
        : {}),
    };

    try {
      const d = await API.startDownload(body);
      if (!d.success) {
        _alert(d.detail || d.error || 'Erro ao iniciar.'); _setDlLoading(false);
        $('progressWrap').style.display = 'none'; return;
      }
      state.jobId = d.job_id;
      state.evtSource = API.watchProgress(d.job_id, {
        onProgress(p) {
          _updateProgress(p.percent || 0, p.message || '…');
          (p.completed_files || []).forEach(_addCompleted);
        },
        onDone(p) {
          state.evtSource = null;
          _updateProgress(100, p.message || '✅ Concluído!');
          _setDlLoading(false);
          Toast.show('Download concluído!', 'success');
        },
        onError(msg) {
          state.evtSource = null;
          _alert('Erro: ' + (msg || 'Desconhecido'));
          _setDlLoading(false);
          $('progressWrap').style.display = 'none';
        },
      });
    } catch (e) {
      _alert('Erro: ' + e.message);
      _setDlLoading(false);
      $('progressWrap').style.display = 'none';
    }
  }

  function _updateProgress(pct, msg) {
    $('progressFill').style.width = pct + '%';
    $('progressMsg').textContent = msg;
  }

  function _addCompleted(file) {
    if (state.completedItems.has(file.id)) return;
    state.completedItems.set(file.id, file);

    const grid = $('completedGrid');
    const div = document.createElement('div');
    div.className = 'completed-item';
    const fileUrl = file.url || API.fileUrl(file.id);
    div.innerHTML = `
      <div class="completed-item-info">
        ${file.thumbnail
          ? `<img class="completed-thumb" src="${escHtml(file.thumbnail)}" alt="" onerror="this.style.display='none'" />`
          : ''}
        <span class="completed-item-title">${escHtml(file.title || file.name)}</span>
      </div>
      <div class="completed-item-actions">
        <button class="btn-sm btn-play-sm">▶</button>
        <a href="${escHtml(fileUrl)}" class="btn-sm btn-dl-sm" download>⬇</a>
      </div>`;
    div.querySelector('.btn-play-sm').addEventListener('click', () => Player.open(file));
    grid.appendChild(div);
    div.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

    // Auto-download: stagger by completed count to avoid browser blocking on playlists
    const delay = (state.completedItems.size - 1) * 800;
    setTimeout(() => {
      const a = document.createElement('a');
      a.href = fileUrl; a.download = '';
      document.body.appendChild(a); a.click();
      setTimeout(() => a.remove(), 100);
    }, delay);
  }

  async function cancelDownload() {
    if (!state.jobId) return;
    if (!confirm('Cancelar o download? Os vídeos já baixados continuarão disponíveis.')) return;
    if (state.evtSource) { state.evtSource.close(); state.evtSource = null; }
    _setDlLoading(false);
    try {
      const d = await API.cancelDownload(state.jobId);
      if (d.success) Toast.show('Download cancelado.', 'warn');
      state.jobId = null;
    } catch (e) {
      _alert('Erro ao cancelar: ' + e.message);
    }
  }

  /* ── Init ──────────────────────────────────────────────────────────────── */
  function init() {
    $('urlInput').addEventListener('keydown', e => { if (e.key === 'Enter') analyze(); });

    $('selectAllCheck').addEventListener('change', (e) => {
      document.querySelectorAll('.playlist-item-check')
        .forEach(cb => { cb.checked = e.target.checked; });
      _updateSelectedCount();
    });

    setInterval(() => API.cleanup().catch(() => {}), 5 * 60 * 1000);
  }

  return { analyze, startDownload, cancelDownload, init };
})();

document.addEventListener('DOMContentLoaded', App.init);
