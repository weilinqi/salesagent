// Run in one process: compatible with Node 20+ and restricted desktop sandboxes.
require('./auth.test.cjs')
require('./websocket.test.cjs')

require('./knowledge.test.cjs')

require('./chatMessageIdentity.test.cjs')

require('./suggestionsVisibility.test.cjs')

require('./audioPause.test.cjs')
