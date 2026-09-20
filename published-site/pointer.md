StoryOS pointer — measured, not promised
updated: 2026-09-19T01:58:30

AUTHORITY (read this first, it is byte-verifiable and needs no key):
  https://paste.rs/dtsYd

LIVE TUNNEL (optional fresh read, currently: healthy):
  <live-tunnel-url: read $STORYOS_HOME/.tunnel_url — it is re-minted on every restart>

last measurement window: 6/6 requests served 200 = 100.0%  (0 x HTTP 530)
longest continuous outage in window: 0s
connector: 0 registrations / 0 lost-edge events

Read <live-tunnel-url: read $STORYOS_HOME/.tunnel_url — it is re-minted on every restart>/agents.md for the route table. There is no
/health, /api, /api/state or /state — a 404 there is a wrong route, not an outage.
A 530/1033 means the connector is detached; the origin may still be healthy.
