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

## Kontrol
```bash
curl -s localhost:8099/health   # workers_alive: 20 (iki DC'nin toplamı) görünmeli
```

## Notlar
- Worker sayısını değiştirmek: env'de `WORKER_REPLICAS`, sonra `up -d`.
- Toplam eş zamanlı işlenen belge = iki DC'deki worker toplamı (20). Fazlası ortak kuyrukta bekler.
- Valkey'in bulunduğu taraf düşerse iki DC de iş alamaz (ortak kuyruk = tek bağımlılık).
