# First Playback Latency Design

## Intent

Reduce the browser-side delay between receiving streamed MP3 data and
scheduling the first audible buffer, so a typical warm text turn can begin
playing within three seconds.

## Scope

- Keep the existing MiniMax MP3 stream and WebSocket binary messages.
- Start the first decode attempt once 4096 bytes are buffered instead of 8192.
- If a partial MP3 cannot be decoded, retain it and retry when more bytes arrive.
- Schedule the first decoded buffer 20ms ahead of the AudioContext clock.
- Log the elapsed time from the first MP3 chunk received to first playback
  scheduling in the browser console.

## Approaches

1. **Earlier MP3 decode retry (selected).** Small frontend-only change; an early
   decode failure is harmless because the accumulated bytes are retained.
2. **Keep the 8KB threshold.** Safest decoding behavior, but the observed turn
   reaches the threshold after the three-second target.
3. **Replace MP3 with PCM streaming.** Lowest decode latency, but changes the
   provider/backend/frontend protocol and is too broad for this fix.

## Constraints

- Do not change existing WebSocket message shapes.
- Do not add a frontend testing dependency.
- Preserve interruption, replay, and PCM behavior.
- Network and provider latency can still cause turns to exceed three seconds.
