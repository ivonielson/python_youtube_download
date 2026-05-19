'use strict';

const Player = (() => {
  let _media = null;
  let _dragging = false;

  /* ── Open (arquivo do servidor) ───────────────────────────────────────── */
  function open(file) {
    const modal    = document.getElementById('playerModal');
    const wrap     = document.getElementById('playerMediaWrap');
    const controls = document.getElementById('playerControls');
    const titleBar = document.getElementById('playerTitleBar');

    _destroy();
    wrap.innerHTML = '';
    controls.style.display = '';

    titleBar.textContent = file.title || file.name || 'FastTube Player';
    _reset();

    const isAudio = /\.(mp3|m4a|ogg|flac)$/i.test(file.name || '');
    wrap.innerHTML = isAudio ? _audioTemplate(file) : _videoTemplate();

    _media = document.getElementById('_mediaEl');
    _media.volume = document.getElementById('playerVolume').value / 100;
    _media.playbackRate = parseFloat(document.getElementById('playerSpeed').value);

    _media.addEventListener('timeupdate',     _onTimeUpdate);
    _media.addEventListener('loadedmetadata', _onMeta);
    _media.addEventListener('ended',          _onEnded);
    _media.addEventListener('error',          _onError);

    _media.src = file.stream_url || API.streamUrl(file.id);

    modal.style.display = 'flex';
    document.body.style.overflow = 'hidden';

    _media.play().catch(() => {});
    document.getElementById('playerPlayBtn').textContent = '⏸';
  }

  /* ── Open YouTube (iframe embed, sem precisar baixar) ─────────────────── */
  function openYoutube(url, title) {
    const videoId = _extractVideoId(url);
    if (!videoId) {
      if (typeof Toast !== 'undefined') Toast.show('URL inválida.', 'danger');
      return;
    }

    _destroy();

    const modal    = document.getElementById('playerModal');
    const wrap     = document.getElementById('playerMediaWrap');
    const controls = document.getElementById('playerControls');
    const titleBar = document.getElementById('playerTitleBar');

    titleBar.textContent = title || 'FastTube Player';
    controls.style.display = 'none'; // YouTube tem seus próprios controles
    wrap.innerHTML = `<iframe class="player-yt-embed"
      src="https://www.youtube-nocookie.com/embed/${videoId}?autoplay=1&rel=0&modestbranding=1"
      allow="autoplay; encrypted-media; picture-in-picture"
      allowfullscreen></iframe>`;

    modal.style.display = 'flex';
    document.body.style.overflow = 'hidden';
  }

  /* ── Close ────────────────────────────────────────────────────────────── */
  function close() {
    _destroy();
    document.getElementById('playerMediaWrap').innerHTML = '';
    document.getElementById('playerControls').style.display = '';
    document.getElementById('playerModal').style.display = 'none';
    document.body.style.overflow = '';
  }

  /* ── Controls ─────────────────────────────────────────────────────────── */
  function togglePlay() {
    if (!_media) return;
    if (_media.paused) {
      _media.play();
      document.getElementById('playerPlayBtn').textContent = '⏸';
    } else {
      _media.pause();
      document.getElementById('playerPlayBtn').textContent = '▶';
    }
  }

  function skip(sec) {
    if (!_media) return;
    _media.currentTime = Math.max(0, Math.min(_media.currentTime + sec, _media.duration || 0));
  }

  function setSpeed(v) { if (_media) _media.playbackRate = parseFloat(v); }

  function toggleFullscreen() {
    const el = document.querySelector('.player-container');
    if (!document.fullscreenElement) el.requestFullscreen?.();
    else document.exitFullscreen?.();
  }

  /* ── Internal ─────────────────────────────────────────────────────────── */
  function _destroy() {
    if (_media) { _media.pause(); _media.src = ''; _media = null; }
  }

  function _reset() {
    document.getElementById('playerCurrentTime').textContent = '0:00';
    document.getElementById('playerTotalTime').textContent = '0:00';
    const seek = document.getElementById('playerSeek');
    seek.value = 0;
    seek.style.setProperty('--p', '0%');
  }

  function _onTimeUpdate() {
    if (_dragging || !_media) return;
    const pct = _media.duration ? (_media.currentTime / _media.duration) * 100 : 0;
    const seek = document.getElementById('playerSeek');
    seek.value = pct;
    seek.style.setProperty('--p', pct + '%');
    document.getElementById('playerCurrentTime').textContent = _fmt(_media.currentTime);
  }

  function _onMeta() {
    document.getElementById('playerTotalTime').textContent = _fmt(_media?.duration || 0);
  }

  function _onEnded() {
    document.getElementById('playerPlayBtn').textContent = '▶';
  }

  function _onError() {
    if (typeof Toast !== 'undefined') Toast.show('Erro ao carregar mídia.', 'danger');
  }

  function _fmt(s) {
    if (!s || isNaN(s)) return '0:00';
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = Math.floor(s % 60);
    return h
      ? `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`
      : `${m}:${String(sec).padStart(2, '0')}`;
  }

  function _videoTemplate() {
    return `<video id="_mediaEl" class="player-video" preload="metadata"></video>`;
  }

  function _audioTemplate(file) {
    const thumb = file.thumbnail
      ? `<img class="player-audio-thumb" src="${_esc(file.thumbnail)}" alt="" />`
      : `<div class="player-audio-placeholder">🎵</div>`;
    return `
      <div class="player-audio-art">${thumb}</div>
      <audio id="_mediaEl" preload="metadata" style="display:none"></audio>
    `;
  }

  function _esc(s) {
    return (s || '').replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function _extractVideoId(url) {
    const m = (url || '').match(/(?:[?&]v=|youtu\.be\/|\/embed\/)([A-Za-z0-9_-]{11})/);
    return m ? m[1] : null;
  }

  /* ── DOM Events (seek + volume + keyboard) ───────────────────────────── */
  function _initDOM() {
    const seekEl = document.getElementById('playerSeek');
    const volEl  = document.getElementById('playerVolume');

    seekEl.addEventListener('pointerdown', () => { _dragging = true; });
    seekEl.addEventListener('input', () => {
      seekEl.style.setProperty('--p', seekEl.value + '%');
      if (_media?.duration) {
        document.getElementById('playerCurrentTime').textContent =
          _fmt((_media.duration * seekEl.value) / 100);
      }
    });
    seekEl.addEventListener('change', () => {
      if (_media?.duration) _media.currentTime = (_media.duration * seekEl.value) / 100;
      _dragging = false;
    });
    seekEl.addEventListener('pointerup', () => { _dragging = false; });

    volEl.addEventListener('input', () => {
      if (_media) _media.volume = volEl.value / 100;
      const icon = document.getElementById('playerVolIcon');
      icon.textContent = volEl.value == 0 ? '🔇' : volEl.value < 50 ? '🔉' : '🔊';
    });

    document.addEventListener('keydown', (e) => {
      const modal = document.getElementById('playerModal');
      if (modal.style.display === 'none') return;
      const tag = e.target.tagName;
      if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return;

      switch (e.key) {
        case ' ':
        case 'k':
          e.preventDefault(); togglePlay(); break;
        case 'ArrowLeft':
          e.preventDefault(); skip(-10); break;
        case 'ArrowRight':
          e.preventDefault(); skip(10); break;
        case 'ArrowUp':
          e.preventDefault();
          volEl.value = Math.min(100, +volEl.value + 10);
          volEl.dispatchEvent(new Event('input'));
          break;
        case 'ArrowDown':
          e.preventDefault();
          volEl.value = Math.max(0, +volEl.value - 10);
          volEl.dispatchEvent(new Event('input'));
          break;
        case 'f':
          toggleFullscreen(); break;
        case 'Escape':
          close(); break;
      }
    });
  }

  document.addEventListener('DOMContentLoaded', _initDOM);

  return { open, openYoutube, close, togglePlay, skip, setSpeed, toggleFullscreen };
})();
