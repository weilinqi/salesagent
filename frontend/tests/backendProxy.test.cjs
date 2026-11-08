const test = require('node:test')
const assert = require('node:assert/strict')
const { harness } = require('./runtime.cjs')

test('HTTP and WebSocket proxies follow the configured backend port', () => {
  const { backendProxy } = harness().load('../config/backendProxy')
  const proxy = backendProxy('8011')
  assert.equal(proxy['/api'].target, 'http://127.0.0.1:8011')
  assert.equal(proxy['/ws'].target, 'ws://127.0.0.1:8011')
  assert.equal(proxy['/ws'].ws, true)
})

test('missing backend port defaults to 8002 and invalid ports fail explicitly', () => {
  const { backendProxy } = harness().load('../config/backendProxy')
  assert.equal(backendProxy()['/api'].target, 'http://127.0.0.1:8002')
  for (const port of ['oops', '0', '65536', '8011/path']) assert.throws(() => backendProxy(port))
})
