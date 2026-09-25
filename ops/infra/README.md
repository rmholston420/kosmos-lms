# Kosmos-LMS Shared Infrastructure

All data stores are **shared infrastructure owned by Kosmos-LMS**. Tektos,
Hermes, and Rigpa-LMS are co-tenants that point at these instances — none of
them may run a private copy.

## Inventory (Collosus)

| Store | Endpoint | Owner service | Scope |
|---|---|---|---|
| Postgres 18 (+pgvector) | `127.0.0.1:5432` | `postgresql.service` (system, native) | shared — kosmos (DB `kosmos`, role `kosmos`), hindsight_kosmos, tektos hindsight, rigpa |
| Redis 7 | `127.0.0.1:6379` | `redis-server.service` (system, native) | shared — kosmos event bus + co-tenants |
| Neo4j Community | `127.0.0.1:7474` (http) / `:7687` (bolt) | `neo4j.service` (system, native) | shared — kosmos MemoryPort (dozerdb-style), tektos procedural memory |
| Qdrant 1.19 | `127.0.0.1:6333` (REST) / `:6334` (gRPC) | `kosmos-qdrant.service` (user) | shared vector store |
| Hindsight (kosmos) | `127.0.0.1:9178` | `kosmos-hindsight.service` (user) | Kosmos-owned cross-session memory (own DB `hindsight_kosmos` on shared Postgres, shared GPU LLM :8090) |

### Hindsight co-tenants (independent copies, independent of Hermes Agent)
| Instance | Endpoint | Profile | Database | LLM |
|---|---|---|---|---|
| **Kosmos (owned)** | `:9178` | `~/.hindsight/profiles/kosmos.env` | `hindsight_kosmos` | `:8090` Qwen3.8-27B (GPU) |
| Tektos | `:9000` | `~/dev/tektos-ultima-v1/.env` | `hindsight` | `:8092` Granite (CPU) |
| Hermes | `:9177` | `~/.hindsight/profiles/hermes.env` | `hindsight` | `:8081` |

## User-level systemd units

- `kosmos-qdrant.service` — native Qdrant binary
  (`~/opt/kosmos/qdrant/qdrant`, config `~/opt/kosmos/qdrant/config.yaml`,
  storage `~/var/lib/kosmos/qdrant/storage`).
  Migrated 2026-09-24 from podman volume `rigpa-lms_qdrant_data`
  (podman overlay store was corrupt; the container path was abandoned).
  Binary: Qdrant 1.19.1 x86_64 linux-gnu.
- `kosmos-hindsight.service` — Hindsight daemon on :9178, profile
  `~/.hindsight/profiles/kosmos.env`, workdir `~/var/lib/kosmos/hindsight`.
- `kosmos-infra.target` — aggregator for the user-level pieces
  (`Wants=` on the system-level postgres/redis/neo4j is not possible from
  a user session; those are enabled at the system level and start at boot).

Bring up / check:

```bash
systemctl --user status kosmos-infra.target kosmos-qdrant kosmos-hindsight
systemctl --user start kosmos-infra        # user-level pieces
# system-level (needs sudo or logged-in session already booted):
sudo systemctl status postgresql redis-server neo4j
```

## Kernel wiring

- `KOSMOS_QDRANT_URL` — default `http://127.0.0.1:6333`
  (`kernel/app.py::_boot_vector`).
- `KOSMOS_VALKEY_URL` — event bus, default `redis://127.0.0.1:6379/0`
  (`adapters/event_bus/valkey/adapter.py`).
- Memory Port / DozerDB — `bolt://127.0.0.1:7687`
  (`ops/systemd/kosmos-kernel.env`).
- Relational memory — `KOSMOS_POSTGRES_URI` (ADR-102) on `:5432`.

## Postgres ownership (Kosmos app-level home)

Kosmos owns the shared Postgres as its **app-level home**: role `kosmos`,
database `kosmos`, `vector` extension installed.

- Password: `ops/systemd/kosmos.pg.password` (gitignored, chmod 600).
- Ready-to-source URI: `ops/systemd/kosmos-kernel.local.env` (gitignored,
  chmod 600) — contains `KOSMOS_POSTGRES_URI` for the `kosmos` DB.
- To wire the orchestrator (Stage 8 exit gate) end-to-end:
  `KOSMOS_RELATIONAL_MEMORY=postgres` + source
  `kosmos-kernel.local.env`. Until then the orchestrator soft-degrades
  per ADR-101 (engine family offline, kernel stays up).

> Note: `ops/systemd/kosmos-kernel.env` is tracked and already carries a
> Neo4j password (pre-existing). Do **not** add new secrets to tracked
> files; keep credentials in the gitignored local files above or the
> age-encrypted store (`KOSMOS_AGE_IDENTITY_PATH`).

## Historical notes

- The `rigpa-*` podman container units under
  `~/.config/containers/systemd/` are **stale orphans**: they reference a
  deleted `~/Rigpa-v3/.env` and would create *empty* containers on the
  same ports. Do not start them.
- Podman overlay storage on Collosus is corrupt (missing layers, image
  inspect fails) — container-based services are not viable until the store
  is rebuilt; native host services are the standard path.
