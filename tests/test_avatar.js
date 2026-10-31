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
