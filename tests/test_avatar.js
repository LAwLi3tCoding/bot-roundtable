'use strict';
const assert = require('node:assert/strict');
const {test} = require('node:test');
const avatar = require('../static/avatar.js');

const agent = {id: 'demo-planner', kind: 'demo'};
const run = {id: 'run-a', plan: '["demo-planner","demo-critic"]', turn: 0, status: 'running'};
const reply = {run: 'run-a', sender: agent.id, source: 'demo', body: 'A reply'};

test('visual identity is deterministic and identity-derived', () => {
  assert.deepEqual(avatar.identity(agent.id), avatar.identity(agent.id));
  const identities = new Set(Array.from({length: 30}, (_, i) => JSON.stringify(avatar.identity(`bot-${i}`))));
  assert.ok(identities.size > 3, 'not every bot should have the same appearance');
});
test('missing runtime evidence stays idle', () => {
  assert.equal(avatar.stateFor(agent, null, []), 'idle');
  assert.equal(avatar.stateFor(agent, {...run, plan: '[]'}, []), 'idle');
  assert.equal(avatar.stateFor(agent, {...run, plan: 'not JSON'}, []), 'idle');
});
test('only the current planned agent has a working turn', () => {
  assert.equal(avatar.stateFor(agent, run, []), 'working');
  assert.equal(avatar.stateFor({id: 'demo-critic'}, run, []), 'idle');
  assert.equal(avatar.stateFor(agent, {...run, turn: 1}, []), 'idle');
});
test('finished reflects this agent reply in this run, not another run or bot', () => {
  const completed = {...run, status: 'completed', turn: 2};
  assert.equal(avatar.stateFor(agent, completed, [reply]), 'finished');
  assert.equal(avatar.stateFor(agent, completed, [{...reply, run: 'old-run'}]), 'idle');
  assert.equal(avatar.stateFor(agent, completed, [{...reply, sender: 'other-bot'}]), 'idle');
});
test('failure and timeout do not implicate unrelated agents', () => {
  for (const status of ['failed', 'timeout']) {
    assert.equal(avatar.stateFor(agent, {...run, status}, []), 'blocked');
    assert.equal(avatar.stateFor({id: 'demo-critic'}, {...run, status}, []), 'idle');
  }
  assert.equal(avatar.stateFor(agent, {...run, status: 'failed'}, [{...reply, source: 'demo-error'}]), 'blocked');
});
test('stopped and interrupted are not presented as active work', () => {
  for (const status of ['stopped', 'interrupted']) {
    assert.equal(avatar.stateFor(agent, {...run, status}, []), 'idle');
    assert.equal(avatar.stateFor(agent, {...run, status}, [reply]), 'finished');
  }
});
test('motion observer pauses hidden and reduced-motion avatars and releases detached nodes', () => {
  const listeners = new Map(), mediaListeners = new Map();
  const media = {matches: false, addEventListener: (name, fn) => mediaListeners.set(name, fn), removeEventListener: name => mediaListeners.delete(name)};
  const classes = new Set();
  const node = {isConnected: true, classList: {toggle(name, enabled) {if (enabled) classes.add(name); else classes.delete(name);}}};
  const root = {hidden: false, querySelectorAll: () => node.isConnected ? [node] : [], addEventListener: (name, fn) => listeners.set(name, fn), removeEventListener: name => listeners.delete(name)};
  let observerCallback, observed = 0, unobserved = 0, disconnected = 0;
  global.window = {matchMedia: () => media};
  global.IntersectionObserver = class {
    constructor(callback) {observerCallback = callback;}
    observe() {observed++;}
    unobserve() {unobserved++;}
    disconnect() {disconnected++;}
  };
  const controller = avatar.motionController(root);
  try {
    controller.sync(); controller.sync();
    assert.equal(observed, 1, 'repeat sync must not observe twice');
    assert.ok(classes.has('avatar-motion-paused'));
    observerCallback([{target: node, isIntersecting: true}]);
    assert.ok(!classes.has('avatar-motion-paused'));
    root.hidden = true; listeners.get('visibilitychange')();
    assert.ok(classes.has('avatar-motion-paused'));
    root.hidden = false; listeners.get('visibilitychange')();
    assert.ok(!classes.has('avatar-motion-paused'));
    media.matches = true; mediaListeners.get('change')();
    assert.ok(classes.has('avatar-motion-paused'));
    media.matches = false; mediaListeners.get('change')();
    observerCallback([{target: node, isIntersecting: false}]);
    assert.ok(classes.has('avatar-motion-paused'));
    node.isConnected = false; controller.sync(); controller.sync();
    assert.equal(unobserved, 1);
  } finally {
    controller.dispose(); delete global.window; delete global.IntersectionObserver;
  }
  assert.equal(disconnected, 1);
  assert.equal(listeners.size, 0);
  assert.equal(mediaListeners.size, 0);
});

test('bot initiation preserves avatar identity without implying a finished reply', () => {
  assert.deepEqual(avatar.messageVisual({sender:'bot:researcher',source:'mcp'}), {id:'researcher',state:'idle'});
  assert.deepEqual(avatar.messageVisual({sender:'researcher',source:'mailbox'}), {id:'researcher',state:'finished'});
  assert.deepEqual(avatar.messageVisual({sender:'researcher',source:'mailbox-error'}), {id:'researcher',state:'blocked'});
});
test('untrusted identity is data, never SVG markup', () => {
  const created = [];
  function node(tag) {
   const result = {tag,attributes:{},children:[],dataset:{},style:{},setAttribute(key,value){this.attributes[key]=value;},append(...children){this.children.push(...children);}};
   created.push(result); return result;
  }
  global.document = {createElement:node,createElementNS:(_ns,tag)=>node(tag)};
  try {
   const malicious = '<svg onload="alert(1)"><script>steal()</script>';
   const result = avatar.create(malicious,'working" onmouseover="steal()',48);
   assert.equal(result.dataset.identity,malicious);
   assert.equal(result.dataset.state,'idle');
   assert.ok(created.every(n=>['span','svg','g','rect','ellipse','path'].includes(n.tag)));
   assert.ok(created.every(n=>Object.keys(n.attributes).every(k=>!/^on/i.test(k))));
   assert.ok(created.every(n=>!Object.values(n.attributes).some(v=>String(v).includes('steal'))));
  } finally { delete global.document; }
});

const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require.resolve('../static/app.js'), 'utf8');
const render = source.slice(source.indexOf('function renderState()'), source.indexOf('function renderCreate()'));

test('clearing disconnected UI also invalidates render caches and releases avatars', () => {
 const nodes = new Map(); let syncs = 0;
 const $ = id => {
  if (!nodes.has(id)) nodes.set(id,{dataset:{signature:'previous-snapshot'},classList:{toggle(){}},replaceChildren(){this.cleared=true;}});
  return nodes.get(id);
 };
 const context = {active:null,state:null,$,t:key=>key,avatarMotion:{sync(){syncs++;}}};
 vm.runInNewContext(render+'\nrenderState();', context);
 for (const id of ['messages','participants','member-list']) {
  assert.ok($(id).cleared);
  assert.equal($(id).dataset.signature,undefined,'same snapshot must rebuild after clearing');
 }
 assert.equal(syncs,1,'detached avatar observers must be released without waiting for polling');
});
