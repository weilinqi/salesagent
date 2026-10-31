# First Audio Latency Design

## Intent

Reduce the measured time from accepting a user message to sending the first AI audio chunk. The observed request took about 3.86 seconds; the practical target is below 3 seconds on a healthy MiniMax connection.

## Constraints

- Preserve knowledge references and existing WebSocket message shapes.
- Keep MiniMax, ChromaDB, embeddings, TTS, and other external calls mocked in automated tests.
- Report latency from the beginning of request processing, including context assembly.
- Treat 3 seconds as a measured target, not a guarantee against provider or network variance.

## Approach

The selected approach moves the one-time ChromaDB and knowledge-search initialization into application startup, before the server reports ready. It also records the first audio send against the original request start and prints a clear PASS/MISS line. Query-dependent RAG remains in each request so references stay relevant.

Alternatives considered were skipping slow RAG after a deadline, which would reduce answer quality, and pooling provider WebSockets, which adds concurrency and reconnect risk. Those are deferred because the observed 1.36-second cold context initialization is enough to explain the gap to the 3-second target.

## Success criteria

- Startup warms the same knowledge retrieval path used by conversations.
- A successful streamed reply returns and logs total first-audio latency.
- The log states whether the request met the 3000ms target.
- Retrieval warmup failure does not prevent the application from starting.
