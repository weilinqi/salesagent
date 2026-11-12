const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const ts = require('typescript')

// Exercise the page's actual event handling, including the text-to-audio transition.
const page = fs.readFileSync(path.join(__dirname, '../src/pages/Practice/PracticeChatPage.tsx'), 'utf8')
const start = page.indexOf("    if (wsMessage.type === 'ai_streaming_start')")
const end = page.indexOf('    // phase_complete', start)
const js = ts.transpileModule(page.slice(start, end), { compilerOptions: { target: ts.ScriptTarget.ES2020 } }).outputText
function setup() {
  let messages = []
  const ref = { current: null }
  const receive = new Function('wsMessage', 'setMessages_', 'currentAIMessageIdRef', 'updatePersona', 'audioStream', js)
  return {
    send: event => receive(event, update => { messages = update(messages) }, ref, () => {}, { playStoredAudio() {} }),
    messages: () => messages,
  }
}
test('stream text and final audio occupy one bubble, repeated start does not duplicate', () => {
  const h = setup()
  h.send({ type: 'ai_streaming_start', id: 'reply-1' })
  h.send({ type: 'ai_streaming_start', id: 'reply-1' })
  h.send({ type: 'ai_streaming_update', id: 'reply-1', content: '试听适合吗？' })
  h.send({ type: 'ai_streaming_end', id: 'reply-1', content: '试听适合吗？', audio_data: 'audio' })
  assert.equal(h.messages().length, 1)
  assert.equal(h.messages()[0].content, '试听适合吗？')
  assert.equal(h.messages()[0].audioData, 'audio')
})
test('updates target their own reply and identical replies on different turns remain separate', () => {
  const h = setup()
  h.send({ type: 'ai_streaming_start', id: 'a' })
  h.send({ type: 'ai_streaming_start', id: 'b' })
  h.send({ type: 'ai_streaming_update', id: 'a', content: '好的' })
  assert.equal(h.messages()[1].content, '')
  h.send({ type: 'ai_streaming_end', id: 'a', content: '好的', audio_data: 'a1' })
  h.send({ type: 'ai_streaming_end', id: 'b', content: '好的', audio_data: 'b1' })
  assert.equal(h.messages().length, 2)
})
