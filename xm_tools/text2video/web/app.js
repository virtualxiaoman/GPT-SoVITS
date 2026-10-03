'use strict';
/* text2video 编辑器：时间轴拖拽 / 预览 / 属性面板 / 保存 / 渲染 */

const $ = id => document.getElementById(id);
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const round3 = v => Math.round(v * 1000) / 1000;
const fmt = t => (Math.max(0, t)).toFixed(2);
const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

const S = {
  id: null, project: null,
  sel: null,                 // 选中片段下标
  pps: 80,                   // 像素/秒
  dirty: false,
  ctx: null, buffers: {}, buffersReady: false,
  playing: false, sources: [], p0: 0, t0: 0,
  suppress: false,
  polling: false,
};

/* ---------------- 基础 ---------------- */
async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) {
    let msg = r.status + ' ' + r.statusText;
    try { msg = (await r.json()).detail || msg; } catch (e) { }
    throw new Error(msg);
  }
  return r.json();
}
const jpost = (p, body) => api(p, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });
const jput = (p, body) => api(p, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

const segs = () => (S.project ? S.project.segments : []);
const isVideo = () => S.project && S.project.mode === 'video' && S.project.source && S.project.source.video;
const logDur = () => {
  const s = S.project && S.project.source;
  return (s && s.width) ? { w: s.width, h: s.height } : { w: 1920, h: 1080 };
};
const dbToGain = db => Math.pow(10, (db || 0) / 20);
const duration = () => {
  if (!S.project) return 10;
  let m = S.project.timeline.end_time || 0;
  for (const s of segs()) {
    m = Math.max(m, s.start + s.duration, s.subtitle.start + s.subtitle.duration);
  }
  if (S.project.source && S.project.source.duration) m = Math.max(m, S.project.source.duration);
  return Math.max(m, 1);
};
const curPos = () => {
  if (isVideo()) return $('video').currentTime;
  return S.playing ? S.ctx.currentTime - S.t0 + S.p0 : S.p0;
};
function markDirty() { S.dirty = true; setSaveState('未保存'); }
function setSaveState(t, isErr) {
  const el = $('save-state');
  el.textContent = t;
  el.style.color = isErr ? '#ff8a80' : '';
}

/* ---------------- 样式计算 ---------------- */
function effStyle(seg) {
  const g = S.project.style_default || {}, o = seg.subtitle.style || {};
  return {
    size: o.size != null ? o.size : (g.size != null ? g.size : 54),
    color: o.color || g.color || '#FFFFFF',
    outline_color: o.outline_color || g.outline_color || '#000000',
    outline_width: o.outline_width != null ? o.outline_width : (g.outline_width != null ? g.outline_width : 2),
    shadow: o.shadow != null ? o.shadow : (g.shadow != null ? g.shadow : 0),
  };
}
function effXY(seg) {
  const g = S.project.style_default || {}, sub = seg.subtitle, { w, h } = logDur();
  const x = sub.x != null ? sub.x : (g.x != null ? g.x : w / 2);
  const y = sub.y != null ? sub.y : (g.y != null ? g.y : h - Math.round(h * 0.08));
  return { x, y };
}
const linkedSub = seg => Math.abs(seg.subtitle.start - seg.start) < 1e-6 &&
  Math.abs(seg.subtitle.duration - seg.duration) < 1e-6;
const syncAll = () => { const el = $('sync-all'); return !!(el && el.checked); };
function forAllSubs(fn) { for (const s of segs()) fn(s); }

/* ---------------- 时间轴 ---------------- */
function renderRuler() {
  const total = duration() + 1;
  $('tl-inner').style.width = (total * S.pps + 140) + 'px';
  const ruler = $('ruler');
  ruler.innerHTML = '';
  const steps = [0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300];
  const step = steps.find(s => s * S.pps >= 64) || 300;
  for (let t = 0; t <= total + step; t += step) {
    const d = document.createElement('div');
    d.className = 'tick';
    d.style.left = (t * S.pps) + 'px';
    const mm = Math.floor(t / 60), ss = t % 60;
    d.textContent = step >= 1 ? (mm + ':' + String(Math.round(ss)).padStart(2, '0')) : t.toFixed(1);
    ruler.appendChild(d);
  }
  const ve = $('video-end');
  if (isVideo() && S.project.source.duration < total) {
    ve.classList.remove('hidden');
    ve.style.left = (S.project.source.duration * S.pps) + 'px';
  } else {
    ve.classList.add('hidden');
  }
}

function blockPos(el, start, dur) {
  el.style.left = (start * S.pps) + 'px';
  el.style.width = Math.max(12, dur * S.pps) + 'px';
}
function blockTitle(s) {
  return '#' + s.id + '  音频 ' + fmt(s.start) + ' → ' + fmt(s.start + s.duration) +
    's ｜ 字幕 ' + fmt(s.subtitle.start) + ' → ' + fmt(s.subtitle.start + s.subtitle.duration) + 's';
}

function renderTracks() {
  const ta = $('track-audio'), ts = $('track-sub');
  ta.querySelectorAll('.blk').forEach(e => e.remove());
  ts.querySelectorAll('.blk').forEach(e => e.remove());
  segs().forEach((s, i) => {
    const a = document.createElement('div');
    a.className = 'blk audio' + (S.sel === i ? ' sel' : '');
    a.dataset.idx = i; a.dataset.kind = 'audio';
    a.textContent = s.subtitle_text;
    a.title = blockTitle(s);
    blockPos(a, s.start, s.duration);
    a.addEventListener('pointerdown', e => startDrag(e, i, 'audio'));
    a.addEventListener('dblclick', () => seekTo(s.start));
    ta.appendChild(a);

    const b = document.createElement('div');
    b.className = 'blk sub' + (S.sel === i ? ' sel' : '');
    b.dataset.idx = i; b.dataset.kind = 'sub';
    b.textContent = s.subtitle_text;
    b.title = blockTitle(s);
    blockPos(b, s.subtitle.start, s.subtitle.duration);
    b.addEventListener('pointerdown', e => startDrag(e, i, 'sub'));
    ts.appendChild(b);
  });
}

const blockEl = (kind, idx) => document.querySelector('#track-' + (kind === 'audio' ? 'audio' : 'sub') + ' .blk[data-idx="' + idx + '"]');

function audioBounds(seg) {
  const list = segs();
  const order = list.map((s, k) => k).sort((x, y) => list[x].start - list[y].start);
  const pi = order.indexOf(list.indexOf(seg));
  const minGap = S.project.timeline.min_gap != null ? S.project.timeline.min_gap : 0.08;
  const tl0 = S.project.timeline.start_time != null ? S.project.timeline.start_time : 0;
  const prev = pi > 0 ? list[order[pi - 1]] : null;
  const next = pi < order.length - 1 ? list[order[pi + 1]] : null;
  const lo = prev ? prev.start + prev.duration + minGap : tl0;
  const hi = next ? next.start - seg.duration - minGap : Infinity;
  return [lo, hi];
}
function subBounds(seg) {
  const sub = seg.subtitle;
  let lo = 0, hi = Infinity;
  for (const s of segs()) {
    if (s === seg) continue;
    const o = s.subtitle;
    if (o.start + o.duration <= sub.start + 1e-9) lo = Math.max(lo, o.start + o.duration);
    else if (o.start >= sub.start + sub.duration - 1e-9) hi = Math.min(hi, o.start - sub.duration);
  }
  return [lo, Math.max(lo, hi)];
}

function startDrag(e, idx, kind) {
  if (!S.project) return;
  e.preventDefault();
  select(idx);
  const seg = segs()[idx];
  const minGap = S.project.timeline.min_gap != null ? S.project.timeline.min_gap : 0.08;
  const snap = v => Math.round(v / 0.05) * 0.05;
  const x0 = e.clientX;
  const onlyAudio = kind === 'audio' && e.altKey;
  const wasLinked = kind === 'audio' && linkedSub(seg);
  const base = kind === 'audio'
    ? { start: seg.start, subStart: seg.subtitle.start, subDur: seg.subtitle.duration }
    : { start: seg.subtitle.start };
  const elA = blockEl('audio', idx), elB = blockEl('sub', idx);

  function onMove(ev) {
    const dt = (ev.clientX - x0) / S.pps;
    if (kind === 'audio') {
      const [lo, hi] = audioBounds(seg);
      const ns = round3(clamp(snap(base.start + dt), lo, hi));
      const applied = ns - seg.start;
      seg.start = ns;
      if (!onlyAudio) {
        const [slo, shi] = subBounds(seg);
        if (wasLinked) {
          seg.subtitle.start = round3(clamp(seg.start, slo, shi));   // 联动：严格对齐，避免吸附误差
        } else {
          seg.subtitle.start = round3(clamp(snap(seg.subtitle.start + applied), slo, shi));
        }
      }
      elA.style.left = (seg.start * S.pps) + 'px';
      elB.style.left = (seg.subtitle.start * S.pps) + 'px';
    } else {
      const [lo, hi] = subBounds(seg);
      const ns = round3(clamp(snap(base.start + dt), lo, hi));
      seg.subtitle.start = ns;
      elB.style.left = (ns * S.pps) + 'px';
    }
    elA.title = blockTitle(seg); elB.title = blockTitle(seg);
    markDirty();
    syncSegInputs();
    updateOverlay();
  }
  function onUp() {
    document.removeEventListener('pointermove', onMove);
    document.removeEventListener('pointerup', onUp);
    renderTracks();
  }
  document.addEventListener('pointermove', onMove);
  document.addEventListener('pointerup', onUp);
}

function select(idx) {
  S.sel = idx == null ? null : idx;
  renderTracks();
  updateSegPanel();
  updateOverlay();
}

/* ---------------- 预览 ---------------- */
function ensureCtx() {
  if (!S.ctx) S.ctx = new (window.AudioContext || window.webkitAudioContext)();
  return S.ctx;
}
function updateVideoVolume() {
  if (!isVideo()) return;
  const mix = S.project.mix || {};
  $('video').volume = clamp(dbToGain(mix.original_volume_db), 0, 1);
}
async function loadBuffers() {
  S.buffers = {}; S.buffersReady = false;
  try {
    ensureCtx();
    await Promise.all(segs().map(async s => {
      const r = await fetch('/media/' + S.id + '/' + s.wav);
      const ab = await r.arrayBuffer();
      S.buffers[s.wav] = await S.ctx.decodeAudioData(ab);
    }));
    S.buffersReady = true;
  } catch (e) {
    console.warn('音频加载失败', e);
  }
}
function scheduleAudio(from) {
  stopAudio();
  if (!S.buffersReady) return;
  const ctx = ensureCtx();
  const t0 = ctx.currentTime + 0.06;
  const mix = S.project.mix || {};
  for (const s of segs()) {
    const buf = S.buffers[s.wav];
    if (!buf) continue;
    if (s.start + s.duration <= from + 0.01) continue;
    const src = ctx.createBufferSource();
    src.buffer = buf;
    const g = ctx.createGain();
    g.gain.value = clamp(dbToGain((mix.tts_volume_db || 0) + (s.volume_db || 0)), 0, 4);
    src.connect(g); g.connect(ctx.destination);
    src.start(t0 + Math.max(0, s.start - from), Math.max(0, from - s.start));
    S.sources.push(src);
  }
}
function stopAudio() {
  for (const s of S.sources) { try { s.stop(); } catch (e) { } }
  S.sources = [];
}
function play() {
  if (!S.project || S.playing) return;
  ensureCtx().resume();
  if (isVideo()) $('video').play().catch(() => { });
  else { S.t0 = S.ctx.currentTime; S.p0 = curPos(); }
  scheduleAudio(curPos());
  S.playing = true;
  $('btn-play').textContent = '⏸';
  requestAnimationFrame(loop);
}
function pause() {
  if (!S.playing) return;
  if (isVideo()) $('video').pause();
  else S.p0 = curPos();
  stopAudio();
  S.playing = false;
  $('btn-play').textContent = '▶';
}
function seekTo(t) {
  t = clamp(t, 0, duration());
  if (isVideo()) $('video').currentTime = t;
  else { if (S.playing) S.t0 = S.ctx.currentTime; S.p0 = t; }
  updatePlayhead(); updateOverlay();
  if (S.playing) scheduleAudio(t);
}
function loop() {
  if (!S.playing) return;
  updatePlayhead();
  updateOverlay();
  if (curPos() >= duration() - 0.02) { pause(); return; }
  requestAnimationFrame(loop);
}
function updatePlayhead() {
  const t = curPos();
  $('playhead').style.left = (t * S.pps) + 'px';
  $('seek').max = duration();
  $('seek').value = Math.min(t, duration());
  $('time-label').textContent = fmt(t) + ' / ' + fmt(duration());
}
function updateOverlay() {
  if (!S.project) return;
  const ov = $('overlay');
  const t = curPos();
  const act = segs().find(s => {
    const st = s.subtitle.start + (s.subtitle.offset || 0);
    return t >= st && t < st + s.subtitle.duration;
  });
  if (!act) { ov.classList.add('hidden'); return; }
  ov.classList.remove('hidden');
  const es = effStyle(act), { x, y } = effXY(act), { w, h } = logDur();
  const box = $('preview').getBoundingClientRect();
  const scale = box.width / w;
  const vs = scale * (h / 1080);   // 与渲染一致：字号/描边按 1080p 基准随视频高度缩放
  ov.textContent = act.subtitle_text;
  ov.style.fontSize = (es.size * vs) + 'px';
  ov.style.color = es.color;
  const ow = es.outline_width * vs;
  ov.style.webkitTextStroke = ow > 0 ? ow + 'px ' + es.outline_color : '';
  ov.style.textShadow = es.shadow > 0 ? (es.shadow * vs) + 'px ' + (es.shadow * vs) + 'px 2px rgba(0,0,0,.85)' : '';
  ov.style.left = (x * scale) + 'px';
  ov.style.top = (y * scale) + 'px';
}

function setupPreviewSize() {
  const { w, h } = logDur();
  const box = $('preview-box'), pr = $('preview');
  function fit() {
    const bw = box.clientWidth || 640;
    const bh = Math.max(150, window.innerHeight * 0.36);
    let pw = bw, ph = pw * h / w;
    if (ph > bh) { ph = bh; pw = ph * w / h; }
    pr.style.width = pw + 'px';
    pr.style.height = ph + 'px';
    updateOverlay();
  }
  fit();
  window.addEventListener('resize', fit);
}

/* ---------------- 选中片段面板 ---------------- */
function syncSegInputs() {
  const i = S.sel;
  if (i == null || !segs()[i]) return;
  const s = segs()[i];
  S.suppress = true;
  $('sg-start').value = s.start;
  $('sg-dur').value = s.duration.toFixed(3);
  $('sb-start').value = s.subtitle.start;
  $('sb-dur').value = s.subtitle.duration;
  $('sb-x').value = s.subtitle.x == null ? '' : s.subtitle.x;
  $('sb-y').value = s.subtitle.y == null ? '' : s.subtitle.y;
  S.suppress = false;
}
function updateSegPanel() {
  const i = S.sel;
  const has = i != null && segs()[i];
  $('seg-empty').classList.toggle('hidden', !!has);
  $('seg-body').classList.toggle('hidden', !has);
  if (!has) return;
  const s = segs()[i], ov = s.subtitle.style || {};
  S.suppress = true;
  $('sg-text').value = s.subtitle_text;
  $('sg-start').value = s.start;
  $('sg-dur').value = s.duration.toFixed(3);
  $('sg-vol').value = s.volume_db || 0;
  $('sg-vol-label').textContent = (s.volume_db || 0) + ' dB';
  $('sb-start').value = s.subtitle.start;
  $('sb-dur').value = s.subtitle.duration;
  $('sb-x').value = s.subtitle.x == null ? '' : s.subtitle.x;
  $('sb-y').value = s.subtitle.y == null ? '' : s.subtitle.y;
  $('sb-size').value = ov.size == null ? '' : ov.size;
  $('sb-color-on').checked = ov.color != null;
  $('sb-color').value = ov.color || (S.project.style_default.color || '#FFFFFF');
  $('sb-oc-on').checked = ov.outline_color != null;
  $('sb-oc').value = ov.outline_color || (S.project.style_default.outline_color || '#000000');
  $('sb-ow').value = ov.outline_width == null ? '' : ov.outline_width;
  $('sb-sh').value = ov.shadow == null ? '' : ov.shadow;
  S.suppress = false;
}

/* ---------------- 全局面板 ---------------- */
function fitText() {
  const tl = S.project.timeline;
  if (tl.fit === 'auto') return '总时长（自动估计）：' + fmt(tl.end_time) + 's';
  if (tl.fit === 'padded') return '总时长 ' + fmt(tl.end_time) + 's：富余已摊入停顿（间隔 ' + fmt(tl.gap) + 's）';
  if (tl.fit === 'tight') return '总时长 ' + fmt(tl.end_time) + 's：停顿已压缩到 ' + fmt(tl.gap) + 's';
  if (tl.fit === 'overflow') return '⚠ 超出 END_TIME ' + fmt(tl.overflow_seconds) + 's';
  return '';
}
function refreshGlobalPanel() {
  const p = S.project, tl = p.timeline, mix = p.mix || {};
  let info = '项目 ' + esc(p.id) + ' · ' + (p.mode === 'video' ? '视频模式' : '无视频模式') +
    ' · ' + esc(p.role) + ' / ' + p.lang + ' / x' + p.speed + '<br>共 ' + segs().length + ' 句';
  if (p.source && p.source.video) {
    info += '<br>视频：' + esc(p.source.video) + '（' + p.source.duration + 's ｜ ' +
      p.source.width + '×' + p.source.height + (p.source.has_audio ? ' 带原声' : ' 无原声') + '）';
  }
  $('proj-info').innerHTML = info;
  $('v-orig').value = mix.original_volume_db || 0;
  $('v-tts').value = mix.tts_volume_db || 0;
  $('v-orig-label').textContent = (mix.original_volume_db || 0) + ' dB';
  $('v-tts-label').textContent = (mix.tts_volume_db || 0) + ' dB';
  $('tl-start').value = tl.start_time;
  $('tl-end').value = tl.end_time_auto ? '' : tl.end_time;
  $('tl-end').placeholder = '自动（' + fmt(tl.end_time) + '）';
  $('render-quality').value = (p.render && p.render.quality) || 'lossless';
  const fi = $('fit-info');
  fi.textContent = fitText();
  fi.classList.toggle('warn', tl.fit === 'overflow');
  const btn = $('btn-resynth');
  if (tl.fit === 'overflow' && segs().length > 1) {
    const asum = segs().reduce((a, s) => a + s.duration, 0);
    const avail = tl.end_time - tl.start_time;
    const sugg = p.speed * (asum + (segs().length - 1) * tl.min_gap) / Math.max(avail, 0.001);
    btn.textContent = '自动压缩语速 → ' + Math.min(sugg, 1.25).toFixed(2) + (sugg > 1.25 ? '（超上限，建议删减文本）' : '');
    btn.dataset.speed = Math.min(sugg, 1.25);
    btn.classList.remove('hidden');
  } else {
    btn.classList.add('hidden');
  }
}

/* ---------------- 载入 / 保存 / 渲染 ---------------- */
function renderAll() {
  renderRuler();
  renderTracks();
  updateSegPanel();
  updateOverlay();
  updatePlayhead();
}
async function loadProjects() {
  const list = await api('/api/projects');
  const sel = $('sel-project');
  sel.innerHTML = '';
  if (!list.length) {
    const o = document.createElement('option');
    o.value = ''; o.textContent = '（还没有项目，点「新建项目」）';
    sel.appendChild(o);
  }
  for (const it of list) {
    const o = document.createElement('option');
    o.value = it.id;
    o.textContent = it.id + '  [' + (it.mode === 'video' ? '视频' : '无视频') + '｜' + it.n + '句]  ' + it.text;
    sel.appendChild(o);
  }
}
async function loadProject(id) {
  const r = await api('/api/projects/' + id);
  S.id = id; S.project = r.project;
  S.sel = null; S.dirty = false; setSaveState('已保存');
  const v = $('video');
  if (isVideo()) {
    v.src = '/api/projects/' + id + '/video';
    v.classList.remove('hidden');
    $('no-video').classList.add('hidden');
  } else {
    v.removeAttribute('src'); v.load();
    v.classList.add('hidden');
    $('no-video').classList.remove('hidden');
  }
  updateVideoVolume();
  setupPreviewSize();
  refreshGlobalPanel();
  renderAll();
  $('sel-project').value = id;
  loadBuffers();
  updateRenderStateFromApi();
}
async function save() {
  if (!S.id) return;
  try {
    await jput('/api/projects/' + S.id, S.project);
    S.dirty = false;
    setSaveState('已保存 ' + new Date().toLocaleTimeString());
  } catch (e) {
    setSaveState('保存失败：' + e.message, true);
  }
}
async function updateRenderStateFromApi() {
  if (!S.id) return;
  const { job } = await api('/api/projects/' + S.id + '/render');
  updateRenderState(job);
}
function updateRenderState(job) {
  const el = $('render-state');
  const ok = job && job.stage === 'done' && job.output_url;
  if (ok) {
    el.innerHTML = '成片：<a href="' + job.output_url + '" download="' + esc(job.output_name || '') + '" class="dl">' +
      esc(job.output_name || '下载') + '</a>';
  } else if (job && job.stage === 'rendering') {
    el.textContent = '渲染中…（ffmpeg 处理中，稍候）';
  } else if (job && job.stage === 'error') {
    el.textContent = '渲染失败：' + (job.error || '');
    el.style.color = '#ff8a80';
  } else {
    el.textContent = '把改动保存后，点右上「渲染出片」';
    el.style.color = '';
  }
}
function startRenderPolling() {
  if (S.polling) return;
  S.polling = true;
  const timer = setInterval(async () => {
    try {
      const { job } = await api('/api/projects/' + S.id + '/render');
      updateRenderState(job);
      if (job.stage !== 'rendering') {
        clearInterval(timer); S.polling = false;
        if (job.stage === 'done' && !S.dirty) await loadProject(S.id);
      }
    } catch (e) { clearInterval(timer); S.polling = false; }
  }, 1000);
}
function startJobPolling(onDone) {
  const timer = setInterval(async () => {
    try {
      const r = await api('/api/projects/' + S.id);
      const job = r.job || {};
      $('nw-progress').textContent = job.message || '';
      if (job.stage === 'done') { clearInterval(timer); onDone(); }
      else if (job.stage === 'error') { clearInterval(timer); $('nw-progress').textContent = job.message || '失败'; }
    } catch (e) { clearInterval(timer); }
  }, 1000);
}

/* ---------------- 事件绑定 ---------------- */
function bind() {
  $('sel-project').addEventListener('change', e => { if (e.target.value) loadProject(e.target.value); });
  $('btn-save').addEventListener('click', save);
  $('btn-render').addEventListener('click', async () => {
    if (!S.id) return;
    if (S.dirty) await save();
    try {
      $('render-state').textContent = '渲染中…';
      const { job } = await jpost('/api/projects/' + S.id + '/render', {});
      updateRenderState(job);
      startRenderPolling();
    } catch (e) { updateRenderState({ stage: 'error', error: e.message }); }
  });

  // 播放控制
  $('btn-play').addEventListener('click', () => S.playing ? pause() : play());
  $('btn-back').addEventListener('click', () => seekTo(curPos() - 5));
  $('btn-fwd').addEventListener('click', () => seekTo(curPos() + 5));
  $('seek').addEventListener('input', () => seekTo(parseFloat($('seek').value)));
  $('video').addEventListener('ended', pause);
  $('ruler').addEventListener('pointerdown', e => {
    const rect = $('tl-inner').getBoundingClientRect();
    seekTo((e.clientX - rect.left) / S.pps);
  });

  // 缩放
  $('btn-zoom-in').addEventListener('click', () => { S.pps = Math.min(400, S.pps * 1.4); renderAll(); });
  $('btn-zoom-out').addEventListener('click', () => { S.pps = Math.max(12, S.pps / 1.4); renderAll(); });

  // 预览区拖字幕
  $('overlay').addEventListener('pointerdown', e => {
    const t = curPos();
    const idx = segs().findIndex(s => {
      const st = s.subtitle.start + (s.subtitle.offset || 0);
      return t >= st && t < st + s.subtitle.duration;
    });
    if (idx < 0) return;
    e.preventDefault();
    select(idx);
    const seg = segs()[idx], { w, h } = logDur();
    const box = $('preview').getBoundingClientRect();
    const scale = box.width / w;
    if (!(scale > 0)) return;   // 预览区不可见/尺寸为 0 时忽略拖拽
    const { x, y } = effXY(seg);
    const x0 = e.clientX, y0 = e.clientY;
    function onMove(ev) {
      const nx = Math.round(clamp(x + (ev.clientX - x0) / scale, 0, w));
      const ny = Math.round(clamp(y + (ev.clientY - y0) / scale, 0, h));
      const apply = sg => { sg.subtitle.x = nx; sg.subtitle.y = ny; };
      if (syncAll()) forAllSubs(apply); else apply(seg);
      updateOverlay(); syncSegInputs(); markDirty();
    }
    function onUp() {
      document.removeEventListener('pointermove', onMove);
      document.removeEventListener('pointerup', onUp);
      updateSegPanel();
    }
    document.addEventListener('pointermove', onMove);
    document.addEventListener('pointerup', onUp);
  });

  // 全局：音量
  $('v-orig').addEventListener('input', () => {
    S.project.mix.original_volume_db = parseFloat($('v-orig').value);
    $('v-orig-label').textContent = S.project.mix.original_volume_db + ' dB';
    updateVideoVolume(); markDirty();
  });
  $('v-tts').addEventListener('input', () => {
    S.project.mix.tts_volume_db = parseFloat($('v-tts').value);
    $('v-tts-label').textContent = S.project.mix.tts_volume_db + ' dB';
    markDirty();
  });
  // 导出质量
  $('render-quality').addEventListener('change', () => {
    if (!S.project) return;
    S.project.render = S.project.render || {};
    S.project.render.quality = $('render-quality').value;
    markDirty();
  });
  // 重新排版
  $('btn-relayout').addEventListener('click', async () => {
    try {
      const end = $('tl-end').value === '' ? null : parseFloat($('tl-end').value);
      const r = await jpost('/api/projects/' + S.id + '/relayout',
        { start_time: parseFloat($('tl-start').value) || 0, end_time: end });
      S.project = r.project;
      refreshGlobalPanel(); renderAll(); setSaveState('已保存');
    } catch (e) { setSaveState('重新排版失败：' + e.message, true); }
  });
  // 自动压缩语速
  $('btn-resynth').addEventListener('click', async () => {
    try {
      const speed = parseFloat($('btn-resynth').dataset.speed);
      await jpost('/api/projects/' + S.id + '/resynth', { speed });
      startJobPolling(async () => { await loadProject(S.id); await loadProjects(); });
    } catch (e) { setSaveState('重合成失败：' + e.message, true); }
  });

  // 选中片段：文本
  $('sg-text').addEventListener('input', () => {
    if (S.suppress || S.sel == null) return;
    segs()[S.sel].subtitle_text = $('sg-text').value;
    markDirty();
  });
  // 音频开始
  $('sg-start').addEventListener('change', () => {
    if (S.suppress || S.sel == null) return;
    const seg = segs()[S.sel];
    const v = parseFloat($('sg-start').value);
    if (isNaN(v)) { updateSegPanel(); return; }
    const linked = linkedSub(seg);
    const [lo, hi] = audioBounds(seg);
    seg.start = round3(clamp(v, lo, hi));
    if (linked) seg.subtitle.start = seg.start;
    markDirty(); renderTracks(); syncSegInputs(); updateOverlay();
  });
  // 片段音量
  $('sg-vol').addEventListener('input', () => {
    if (S.suppress || S.sel == null) return;
    segs()[S.sel].volume_db = parseFloat($('sg-vol').value);
    $('sg-vol-label').textContent = segs()[S.sel].volume_db + ' dB';
    markDirty();
  });
  // 字幕开始
  $('sb-start').addEventListener('change', () => {
    if (S.suppress || S.sel == null) return;
    const seg = segs()[S.sel];
    const v = parseFloat($('sb-start').value);
    if (isNaN(v)) { updateSegPanel(); return; }
    const [lo, hi] = subBounds(seg);
    seg.subtitle.start = round3(clamp(v, lo, hi));
    markDirty(); renderTracks(); syncSegInputs(); updateOverlay();
  });
  // 字幕时长
  $('sb-dur').addEventListener('change', () => {
    if (S.suppress || S.sel == null) return;
    const seg = segs()[S.sel];
    let v = parseFloat($('sb-dur').value);
    if (isNaN(v) || v < 0.2) { updateSegPanel(); return; }
    const [lo, hi] = subBounds(seg);
    v = Math.max(0.2, Math.min(v, hi - seg.subtitle.start));
    seg.subtitle.duration = round3(v);
    markDirty(); renderTracks(); syncSegInputs(); updateOverlay();
  });
  // X / Y（勾选「同步到全部字幕」时，所有字幕统一到同一位置）
  const xyHandler = (id, key) => $(id).addEventListener('change', () => {
    if (S.suppress || S.sel == null) return;
    const { w, h } = logDur();
    const raw = $(id).value.trim();
    const val = raw === '' ? null : Math.round(clamp(parseFloat(raw) || 0, 0, key === 'x' ? w : h));
    const apply = sg => { sg.subtitle[key] = val; };
    if (syncAll()) forAllSubs(apply); else apply(segs()[S.sel]);
    markDirty(); updateOverlay(); renderTracks();
  });
  xyHandler('sb-x', 'x'); xyHandler('sb-y', 'y');
  $('btn-clear-xy').addEventListener('click', () => {
    if (S.sel == null) return;
    const apply = sg => { sg.subtitle.x = null; sg.subtitle.y = null; };
    if (syncAll()) forAllSubs(apply); else apply(segs()[S.sel]);
    markDirty(); updateSegPanel(); updateOverlay();
  });
  // 样式覆盖（勾选「同步到全部字幕」时，所有字幕一起改）
  const ensureOv = seg => seg.subtitle.style = seg.subtitle.style || {};
  const editStyle = mut => {
    const apply = sg => { ensureOv(sg); mut(sg.subtitle.style); };
    if (syncAll()) forAllSubs(apply); else apply(segs()[S.sel]);
    markDirty(); updateOverlay();
  };
  $('sb-size').addEventListener('change', () => {
    if (S.suppress || S.sel == null) return;
    const raw = $('sb-size').value.trim();
    editStyle(st => { if (raw === '') delete st.size; else st.size = parseFloat(raw) || 54; });
  });
  $('sb-color-on').addEventListener('change', () => {
    if (S.suppress || S.sel == null) return;
    const on = $('sb-color-on').checked, color = $('sb-color').value;
    editStyle(st => { if (on) st.color = color; else delete st.color; });
  });
  $('sb-color').addEventListener('input', () => {
    if (S.suppress || S.sel == null) return;
    $('sb-color-on').checked = true;   // 直接点色块选色 = 自动开启覆盖
    const color = $('sb-color').value;
    editStyle(st => { st.color = color; });
  });
  $('sb-oc-on').addEventListener('change', () => {
    if (S.suppress || S.sel == null) return;
    const on = $('sb-oc-on').checked, color = $('sb-oc').value;
    editStyle(st => { if (on) st.outline_color = color; else delete st.outline_color; });
  });
  $('sb-oc').addEventListener('input', () => {
    if (S.suppress || S.sel == null) return;
    $('sb-oc-on').checked = true;   // 直接点色块选色 = 自动开启覆盖
    const color = $('sb-oc').value;
    editStyle(st => { st.outline_color = color; });
  });
  $('sb-ow').addEventListener('change', () => {
    if (S.suppress || S.sel == null) return;
    const raw = $('sb-ow').value.trim();
    editStyle(st => { if (raw === '') delete st.outline_width; else st.outline_width = parseFloat(raw) || 0; });
  });
  $('sb-sh').addEventListener('change', () => {
    if (S.suppress || S.sel == null) return;
    const raw = $('sb-sh').value.trim();
    editStyle(st => { if (raw === '') delete st.shadow; else st.shadow = parseFloat(raw) || 0; });
  });
  $('btn-clear-style').addEventListener('click', () => {
    if (S.sel == null) return;
    const apply = sg => { sg.subtitle.style = {}; };
    if (syncAll()) forAllSubs(apply); else apply(segs()[S.sel]);
    markDirty(); updateSegPanel(); updateOverlay();
  });

  // 新建项目
  $('btn-new').addEventListener('click', async () => {
    $('dlg').classList.remove('hidden');
    $('nw-progress').textContent = '';
    if (!$('nw-role').options.length) {
      try {
        const roles = await api('/api/roles');
        for (const r of roles) {
          const o = document.createElement('option'); o.textContent = r; $('nw-role').appendChild(o);
        }
        $('nw-role').value = roles.includes('洛天依') ? '洛天依' : (roles[0] || '');
      } catch (e) { }
    }
  });
  $('nw-cancel').addEventListener('click', () => $('dlg').classList.add('hidden'));
  $('nw-create').addEventListener('click', async () => {
    const body = {
      text: $('nw-text').value,
      video: $('nw-video').value.trim(),
      role: $('nw-role').value,
      lang: $('nw-lang').value,
      speed: parseFloat($('nw-speed').value) || 1.0,
      start_time: parseFloat($('nw-start').value) || 0,
      end_time: $('nw-end').value.trim() === '' ? null : parseFloat($('nw-end').value),
    };
    try {
      $('nw-progress').textContent = '提交…';
      const r = await jpost('/api/projects', body);
      const pid = r.id;
      const timer = setInterval(async () => {
        try {
          const rr = await api('/api/projects/' + pid);
          const job = rr.job || {};
          $('nw-progress').textContent = job.message || '';
          if (job.stage === 'done') {
            clearInterval(timer);
            $('dlg').classList.add('hidden');
            await loadProjects();
            await loadProject(pid);
          } else if (job.stage === 'error') {
            clearInterval(timer);
            $('nw-progress').textContent = job.message || '失败';
          }
        } catch (e) { clearInterval(timer); $('nw-progress').textContent = '失败：' + e.message; }
      }, 1000);
    } catch (e) {
      $('nw-progress').textContent = '失败：' + e.message;
    }
  });

  // 快捷键
  document.addEventListener('keydown', e => {
    const tag = (e.target.tagName || '').toLowerCase();
    const typing = tag === 'input' || tag === 'textarea' || tag === 'select';
    if (e.ctrlKey && e.key.toLowerCase() === 's') { e.preventDefault(); save(); return; }
    if (typing) return;
    if (e.code === 'Space') { e.preventDefault(); S.playing ? pause() : play(); }
  });
  window.addEventListener('beforeunload', e => {
    if (S.dirty) { e.preventDefault(); e.returnValue = ''; }
  });
}

/* ---------------- 启动 ---------------- */
(async function main() {
  bind();
  try {
    await loadProjects();
    const first = $('sel-project').value;
    if (first) await loadProject(first);
  } catch (e) {
    setSaveState('初始化失败：' + e.message, true);
  }
})();
