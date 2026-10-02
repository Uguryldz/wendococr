# Aktif-aktif kurulum (DC1 + DC2, ortak Valkey, 20 worker)

## Kurulum
Her iki makinede bu klasörü kopyala, env dosyasındaki `REDIS_URL`'i düzelt:

```bash
# DC1
docker compose --env-file dc1.env pull && docker compose --env-file dc1.env up -d
# DC2
docker compose --env-file dc2.env pull && docker compose --env-file dc2.env up -d
```

DNS: aynı isim için iki A kaydı (DC1 IP, DC2 IP). İstemci bağlantı hatasında diğer IP'yi denesin.

## Valkey'de olması gerekenler
| Ayar | Değer | Neden |
|---|---|---|
| `maxmemory-policy` | `noeviction` | Bellek dolunca iş silinmez, API yer açılana kadar bekler |
| `appendonly` / `save` | `no` / `""` | Belge içeriği diske yazılmaz (KVKK); kayıp iş API tarafından yeniden gönderilir |
| `maxmemory` | ≥ 2 GB | 500 iş × ~2 MB × 1.4 (base64) |
| `requirepass` | dolu | Port iki DC'ye açık |

## Valkey ACL kullanıcısı (en az yetki, test edildi)
```
ACL SETUSER wendococr on >SIFRE ~wendococr:* resetchannels -@all +ping +select +llen +lpush +lrange +lrem +blmove +blpop +hset +hgetall +hdel +exists +expire +set +del
ACL SETUSER haproxy   on >HAPSIFRE -@all +ping +info
```
`REDIS_KEY_PREFIX` değiştirirsen `~wendococr:*` kısmını da değiştir.

## HAProxy (Valkey önünde)
`option redis-check` KULLANMA: şifresiz PING atar, Valkey NOAUTH döner, HAProxy backend'i DOWN
sayıp her bağlantıyı kapatır (uygulamada "Connection closed by server").
```
backend valkey
    mode tcp
    timeout server 60s
    option tcp-check
    tcp-check send AUTH\ haproxy\ HAPSIFRE\r\n
    tcp-check expect string +OK
    tcp-check send PING\r\n
    tcp-check expect string +PONG
    tcp-check send info\ replication\r\n
    tcp-check expect string role:master
    server valkey1 10.x.x.x:6379 check inter 2s
```
`timeout client` / `timeout server` en az 30 sn olmalı (worker'lar 5 sn'lik bloklayan komutla dinler).

## Kontrol
```bash
curl -s localhost:8099/health   # workers_alive: 20 (iki DC'nin toplamı) görünmeli
```

## Notlar
- Worker sayısını değiştirmek: env'de `WORKER_REPLICAS`, sonra `up -d`.
- Toplam eş zamanlı işlenen belge = iki DC'deki worker toplamı (20). Fazlası ortak kuyrukta bekler.
- Valkey'in bulunduğu taraf düşerse iki DC de iş alamaz (ortak kuyruk = tek bağımlılık).
