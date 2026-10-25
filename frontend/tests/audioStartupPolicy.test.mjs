import assert from 'node:assert/strict'
import test from 'node:test'

const audioStream = await import('../src/hooks/useAudioStream.ts')

test('initial MP3 decode starts at 4096 bytes and retries earlier with queued audio', () => {
  const policy = audioStream.shouldAttemptMp3Decode

  assert.equal(typeof policy, 'function')
  assert.equal(policy(4095, false), false)
  assert.equal(policy(4096, false), true)
  assert.equal(policy(1, true), true)
})
