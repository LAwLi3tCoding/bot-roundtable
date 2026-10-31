'use strict';
// Original geometric characters. Identity and expression never depend on display order.
const RoundtableAvatar = (() => {
 const palettes = ['#579b8b', '#8672bd', '#cc9251', '#618dc0', '#bd786e', '#79935e'];
 function identity(id) {
  let hash = 2166136261;
  for (const char of String(id)) hash = Math.imul(hash ^ char.codePointAt(0), 16777619) >>> 0;
  return {variant: hash % 3, palette: palettes[(hash >>> 8) % palettes.length]};
 }
 function stateFor(agent, run, messages = []) {
  if (!run) return 'idle';
  let plan;
  try { plan = JSON.parse(run.plan); } catch { plan = []; }
  if (!Array.isArray(plan)) plan = [];
  const pending = plan[run.turn] === agent.id;
  if (pending && run.status === 'running') return 'working';
  if (pending && ['failed','timeout'].includes(run.status)) return 'blocked';
  const latest = messages.filter(m => m.run === run.id && m.sender === agent.id).at(-1);
  if (latest) return String(latest.source).endsWith('-error') ? 'blocked' : 'finished';
  return 'idle';
 }
 const ns = 'http://www.w3.org/2000/svg';
 function shape(tag, attributes) {
  const node = document.createElementNS(ns, tag);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
  return node;
 }
 function create(id, state = 'idle', size = 32) {
  const visual = identity(id), wrapper = document.createElement('span');
  wrapper.className = 'bot-avatar'; wrapper.dataset.identity = String(id);
  wrapper.dataset.state = ['idle','working','finished','blocked'].includes(state) ? state : 'idle';
  wrapper.dataset.compact = String(size < 48);
  wrapper.style.width = `${size}px`; wrapper.style.height = `${size}px`;
  wrapper.setAttribute('aria-hidden', 'true');
  const svg = shape('svg', {viewBox:'0 0 64 64', width:size, height:size, focusable:'false'});
  const body = shape('g', {class:'avatar-body', fill:visual.palette});
  if (visual.variant === 0) body.append(shape('rect',{x:9,y:10,width:46,height:46,rx:19}));
  if (visual.variant === 1) body.append(shape('ellipse',{cx:32,cy:34,rx:25,ry:22}));
  if (visual.variant === 2) body.append(shape('path',{d:'M18 12 Q32 5 46 15 L55 41 Q54 56 34 56 L18 53 Q7 50 10 36 Z'}));
  body.append(shape('ellipse',{cx:24,cy:18,rx:8,ry:3,fill:'#fff',opacity:'.14'}));
  const eyes = shape('g',{class:'avatar-eyes',fill:'#fff'});
  eyes.append(shape('rect',{x:23,y:27,width:5,height:11,rx:2.5}),shape('rect',{x:36,y:27,width:5,height:11,rx:2.5}));
  body.append(eyes);
  body.append(shape('path',{class:'avatar-smile',d:'M27 43 Q32 47 37 43',fill:'none',stroke:'#fff','stroke-width':2,'stroke-linecap':'round'}));
  body.append(shape('path',{class:'avatar-brow',d:'M22 23 L28 25 M36 25 L42 23',fill:'none',stroke:'#fff','stroke-width':2,'stroke-linecap':'round'}));
  svg.append(body); wrapper.append(svg); return wrapper;
 }
 // One observer per page, no per-avatar timers. Detached avatars are released on sync.
 function motionController(root = document) {
  const tracked = new Set(), visible = new WeakSet();
  const media = window.matchMedia('(prefers-reduced-motion: reduce)');
  const update = node => node.classList.toggle('avatar-motion-paused', root.hidden || media.matches || !visible.has(node));
  const observer = typeof IntersectionObserver === 'function' ? new IntersectionObserver(entries => {
   for (const entry of entries) { if (entry.isIntersecting) visible.add(entry.target); else visible.delete(entry.target); update(entry.target); }
  }) : null;
  const refresh = () => tracked.forEach(update);
  root.addEventListener('visibilitychange', refresh); media.addEventListener('change', refresh);
  return {
   sync() {
    for (const node of tracked) if (!node.isConnected) { observer?.unobserve(node); tracked.delete(node); }
    for (const node of root.querySelectorAll('.bot-avatar')) if (!tracked.has(node)) {
     tracked.add(node); update(node); observer?.observe(node);
    }
   },
   dispose() { observer?.disconnect(); tracked.clear(); root.removeEventListener('visibilitychange', refresh); media.removeEventListener('change', refresh); }
  };
 }
 return {identity, stateFor, create, motionController};
})();
if (typeof module !== 'undefined') module.exports = RoundtableAvatar;
