"""Kuyruk korumaları: çift iş, deneme sınırı, reaper tek kopya, yetim iş.
Çalıştır: boş bir Valkey/Redis ile  REDIS_URL=redis://127.0.0.1:6379/15 PYTHONPATH=. python tests/test_queue_guards.py
DİKKAT: seçilen DB FLUSHDB ile silinir."""
import json, os, time
assert os.environ.get("REDIS_URL"), "REDIS_URL gerekli (boş bir test DB)"
os.environ["REDIS_KEY_PREFIX"] = "tq"
import app.core.worker_pool as wp
r=wp._redis_client(); r.flushdb()
PK=f"{wp.REDIS_QUEUE_NAME}:processing"
now=str(time.time())
r.hset(wp.WORKER_HEARTBEAT_KEY,"A",now); r.hset(wp.WORKER_HEARTBEAT_KEY,"B",now)
# çift iş: A sahiplenir, B atlar
assert wp._claim_job(r,"j1","A") is None
assert "baska worker" in wp._claim_job(r,"j1","B")
# sahibi ölü -> devralır
r.hset(wp.WORKER_HEARTBEAT_KEY,"A","0")
assert wp._claim_job(r,"j1","B") is None
# deneme sınırı (2): üçüncü sahiplenme reddedilir
r.hdel(wp.PROCESSING_META_KEY,"j1")
s=wp._claim_job(r,"j1","B"); assert s and s.startswith("deneme"), s
# done -> atla
r.set(wp._ATTEMPTS_PREFIX+"j2",b"done")
assert wp._claim_job(r,"j2","B")=="zaten tamamlandi"
# reaper: ölü worker işinin İKİ kopyası -> kuyruğa TEK kopya
r.delete(wp.REDIS_QUEUE_NAME,PK,wp.PROCESSING_META_KEY)
raw=json.dumps({"job_id":"j3"}).encode()
r.lpush(PK,raw,raw); r.hset(wp.PROCESSING_META_KEY,"j3",json.dumps({"worker_id":"A","started_at":time.time()}))
assert wp._reap_stale_jobs(r,PK)==1 and r.llen(wp.REDIS_QUEUE_NAME)==1 and r.llen(PK)==0
# yetim (meta'sız): ilk taramada dokunulmaz, ikincide toplanır
r.delete(wp.REDIS_QUEUE_NAME); r.lpush(PK,json.dumps({"job_id":"j4"}).encode())
assert wp._reap_stale_jobs(r,PK)==0 and r.llen(PK)==1
assert wp._reap_stale_jobs(r,PK)==1 and r.llen(wp.REDIS_QUEUE_NAME)==1
print("OK")
