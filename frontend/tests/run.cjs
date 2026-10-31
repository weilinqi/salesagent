// Run in one process: compatible with Node 20+ and restricted desktop sandboxes.
require('./auth.test.cjs')
require('./websocket.test.cjs')

require('./knowledge.test.cjs')

// The deployment and CI runtime is Node 22, which can load this TypeScript-backed test.
void import('./audioStartupPolicy.test.mjs')
