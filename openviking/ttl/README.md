# Redis directory TTL

TTL is optional and disabled by default. The first implementation requires Redis;
there is no Redis-free backend. The implementation and tests ship with OpenViking.
It uses the existing expiry Redis client and storage/configuration lifecycle.

Install OpenViking with the `expiry` extra, then merge into your server config:

```json
{
  "server": {
    "ttl_adapter": {
      "enabled": true,
      "config": {
        "resource_id": "stable-library-id",
        "redis": {"mode": "standalone", "endpoints": ["redis://127.0.0.1:6379"]}
      }
    }
  },
  "expiry": {
    "service_name": "stable-library-id",
    "publisher_separate_process": false,
    "redis": {"mode": "standalone", "endpoints": ["redis://127.0.0.1:6379"]}
  },
  "ttl": {"sessions": 30, "user_events": 60, "peer_events": 60}
}
```

Use a stable ResourceID across restarts; each Redis scope also includes the
OpenViking Account ID. Production credentials and Redis durability are deployment
configuration. The regular OV Docker image already includes the expiry extra.
No external Python class path, wheel or overlay image is needed.
`ttl_adapter.config.redis` stores directory indexes; `expiry.redis` stores the
shared scheduler's tasks. The example uses the same Redis and runs the publisher
in-process. If auto commit already configures expiry, retain that configuration
and its publisher deployment. TTL also requires `expiry.service_name` and
`expiry.redis.endpoints`.

An omitted or disabled `server.ttl_adapter` installs no write hook, starts no TTL
worker and loads no TTL Redis client. Explicit policy writes then return
`501 UNIMPLEMENTED`: `Redis-backed TTL is not enabled in this deployment.`
An enabled adapter still skips Redis, stat and TTL locks when the target's
effective policy is disabled. UserConfig is read once on a cache miss or refresh,
not once per file. A reader uses `config.writer=false`: expiry display is
available, but it never scans or recycles. TTL is soft: searches and reads keep
returning expired content until physical deletion. Historical Event writes are
allowed; they do not renew the date directory's lifetime.

The existing write path buffers successful writes and flushes them asynchronously
in batches. Session directory scores use the write time (`ZADD GT`); Event date
directories use the directory date (`ZADD NX`). Deletion rechecks current policy
and Session `messages.jsonl` ModTime under the existing directory lock. Redis
index removal compares the original score to preserve a concurrent renewal.

User TTL lives in `settings/user_config.json` and uses the existing
`GET/PATCH /api/v1/admin/accounts/{account_id}/users/{user_id}/settings` API:

```json
{"ttl": {"sessions": 30, "user_events": 60, "peer_events": 60}}
```

For each field, User overrides Account, which overrides global configuration.
All Peers under one User share `peer_events`. `user_events` and `sessions`
remain independent. Type defaults precede `global`.
Missing fields inherit, `disabled` stops fallback, and PATCH `null` removes an
override. `roots` is no longer part of the cluster/Account configuration schema.
The existing UserConfig update lock, validation, backup and deletion apply.
TTL caches at most 1024 user snapshots, keyed by Account and User. A local save
publishes immediately; other processes refresh on demand after 30 seconds.
Concurrent misses share one load. This cache adds no periodic filesystem scan.

The hidden ROOT-authenticated `/api/v1/admin/ttl/initial` endpoint registers or
resets a fixed `initial` scan. Redis keeps its pending marker, checkpoint and done
marker across OV restarts; startup does not discover objects by scanning AGFS.
The OV writer registers hourly maintenance with the existing expiry scheduler,
using a stable ResourceID offset. Its TTL consumer starts on first registration;
Redis retains that activation across restarts. An overdue callback after restart
schedules the next window instead of immediately recycling. OV discovers initial
roots when needed, reuses saved checkpoints and checks due candidates itself.
`/api/v1/admin/ttl/recycle` also supports explicit internal requests. The hidden
GET `/api/v1/admin/ttl/initial` reads internal recovery state; no caller needs a
Redis connection. TTL policy PATCHes persist reset intent before saving, so the
next maintenance trigger can recover an interrupted handoff. Commercial Server
configures the writer and forwards internal repair requests; it does not run the
hourly scheduler. TTL adds no separate timer or callback queue.

Tests live in `tests/ttl/`. `TTL_TEST_REDIS` and `TTL_TEST_CLUSTER` opt into isolated
real Redis tests; ordinary tests use fakeredis with Lua support. Integration tests
cover writer scheduling, restart recovery and real queue-thread registration.
`tests/ttl/benchmark_ttl.py` is a local cost sample, not production acceptance.
