'use strict';

const API = (() => {
  const BASE = '/api';

  function _sessionId() {
    let id = sessionStorage.getItem('ft_session');
    if (!id) {
      id = 'ses_' + Date.now() + '_' + Math.random().toString(36).slice(2, 9);
      sessionStorage.setItem('ft_session', id);
    }
    return id;
  }

  async function analyze(url) {
    const r = await fetch(`${BASE}/analyze`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
    });
    return r.json();
  }

  function analyzePlaylist(url, { onHeader, onItem, onDone, onError } = {}) {
    const es = new EventSource(`${BASE}/analyze-playlist?url=${encodeURIComponent(url)}`);
    es.onmessage = (e) => {
      const d = JSON.parse(e.data);
      if      (d.event === 'header') onHeader?.(d);
      else if (d.event === 'item')   onItem?.(d);
      else if (d.event === 'done')   { es.close(); onDone?.(); }
      else if (d.event === 'error')  { es.close(); onError?.(d.message); }
    };
    es.onerror = () => { es.close(); onError?.('Erro de conexão ao analisar playlist.'); };
    return es;
  }

  async function startDownload({ url, format_id, urls, video_metadata }) {
    const r = await fetch(`${BASE}/download`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Session-ID': _sessionId() },
      body: JSON.stringify({ url, format_id, urls, video_metadata }),
    });
    return r.json();
  }

  function watchProgress(jobId, { onProgress, onDone, onError } = {}) {
    const es = new EventSource(`${BASE}/progress/${jobId}`);
    es.onmessage = (e) => {
      const d = JSON.parse(e.data);
      onProgress?.(d);
      if      (d.status === 'done' || d.status === 'cancelled') { es.close(); onDone?.(d); }
      else if (d.status === 'error')                            { es.close(); onError?.(d.error); }
    };
    es.onerror = () => { es.close(); onError?.('Conexão SSE encerrada.'); };
    return es;
  }

  async function cancelDownload(jobId) {
    const r = await fetch(`${BASE}/cancel/${jobId}`, { method: 'POST' });
    return r.json();
  }

  async function getJobs() {
    const r = await fetch(`${BASE}/jobs`);
    return r.json();
  }

  async function cleanup() {
    const r = await fetch(`${BASE}/cleanup`, { method: 'POST' });
    return r.json();
  }

  function fileUrl(fileId)   { return `${BASE}/file/${fileId}`; }
  function streamUrl(fileId) { return `${BASE}/stream/${fileId}`; }

  return { analyze, analyzePlaylist, startDownload, watchProgress, cancelDownload, getJobs, cleanup, fileUrl, streamUrl };
})();
