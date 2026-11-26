# Deployment Information

## Public URL
https://agent-production-f5fff8e6.up.railway.app

## Platform
Railway: project `day14-production-agent`, gồm service `agent` (build từ `06-lab-complete/Dockerfile`, cấu hình `railway.toml`) và Redis managed của Railway. Deploy ngày 2026-11-26 bằng Railway CLI 5.75.0, code lấy từ commit trên nhánh `theduythg/hieu`.

## Kết quả kiểm tra trên URL public (2026-11-26 19:47 GMT+7)

| Kiểm tra | Kết quả |
|---|---|
| `GET /health` | 200 |
| `GET /ready` (Redis kết nối được) | 200 |
| `POST /ask` không có key | 401 |
| `POST /ask` có key | 200 |
| `POST /ask` với `question` rỗng | 422 |
| Gọi liên tiếp quá 10 request/phút | 429 |

Kiểm tra lại lúc 20:35 cùng ngày: `/health` 200, `/ready` 200, `/ask` không key 401, có key 200.

Cost guard (402) được kiểm bằng `check_production_ready.py` trên máy, chưa thử trên cloud.

## Test Commands

```bash
BASE=https://agent-production-f5fff8e6.up.railway.app
read -rs AGENT_API_KEY    # key lấy ở Railway -> service agent -> Variables

curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"     # 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"      # 200
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -d '{"question":"Hello"}'   # 401
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"Hello"}'   # 200
```

## Environment Variables Set (trên Railway)

| Biến | Giá trị |
|---|---|
| `AGENT_API_KEY` | Chuỗi ngẫu nhiên 43 ký tự, chỉ lưu trên Railway |
| `REDIS_URL` | `${{Redis.REDIS_URL}}` (tham chiếu tới service Redis) |
| `ENVIRONMENT` | `production` |
| `RATE_LIMIT_PER_MINUTE` | `10` |
| `DAILY_BUDGET_USD` | `1.0` |
| `PORT` | `8000` |

Ghi chú: Railway CLI cảnh báo cấu hình bằng `railway.toml` sắp bị thay thế (file hiện có còn được hỗ trợ tới 2026-12-01).

## Screenshots
- [Service running](screenshots/running.png): trang `/docs` mở từ URL public
- [Test results](screenshots/test.png): ảnh chụp cửa sổ Git Bash chạy 4 lệnh tự kiểm (21:13 ngày 2026-11-26), API key không hiển thị
- [Deployment dashboard](screenshots/dashboard.png): ảnh chụp trang dashboard Railway, `agent` và `Redis` Online, giá trị biến được che
