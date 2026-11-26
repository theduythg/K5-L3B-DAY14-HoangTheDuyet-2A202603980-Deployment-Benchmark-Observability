# Benchmark & Observability Report — Day 14

> Số liệu lấy từ `reports/` (JSON), `benchmark-results/` (CSV), Prometheus và log thật.

**Họ tên:** Hoàng Thế Duyệt  
**Ngày chạy:** 2026-11-26  
**Môi trường:** Windows 11 + WSL2 Ubuntu, Docker 29.8.2; benchmark develop chạy bằng Python 3.14. LLM là mock.

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | < 500 ms | Request thường mất khoảng 150–250 ms; 500 ms chừa biên cho dao động. Đây cũng là ngưỡng `load_test.py` dùng. |
| Error rate `/ask` | < 2 % | Mock mặc định tạo khoảng 1 % lỗi (`MOCK_ERROR_RATE=0.01`); 2 % chừa biên cho dao động ngẫu nhiên. Trùng ngưỡng của `load_test.py`. |
| Accuracy trên golden dataset | ≥ 95 % | Với 23 câu, chỉ cho phép sai tối đa 1 câu. |

Alert của stack production dùng ngưỡng nới hơn (lỗi > 5 % trong 1 phút, p95 > 1 s trong 2 phút) để chỉ báo khi vi phạm rõ và kéo dài.

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2, 300 request mỗi mức)

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 4.08 | 191.8 | 224.5 | 1706.8 | 1.33 % | PASS |
| 10 | 35.82 | 193.8 | 233.4 | 1696.0 | 1.33 % | PASS |
| 50 | 57.36 | 332.9 | 2430.3 | 3405.7 | 1.00 % | FAIL |
| 100 | 47.80 | 1091.9 | 4422.0 | 5238.4 | 1.33 % | FAIL |

**Nhận xét:** RPS không tăng tuyến tính. Từ 1 lên 10, RPS tăng khoảng 8,8 lần và latency gần như giữ nguyên. Từ 10 lên 50 (gấp 5), RPS chỉ tăng 1,6 lần còn p95 tăng khoảng 10 lần. Ở 100, RPS còn giảm (57 → 48). Hệ thống đã bão hoà trong khoảng 10–50: request phải xếp hàng. Giả thuyết là nút thắt nằm ở một tiến trình uvicorn duy nhất (hoặc ở chính máy chạy load test); mình chưa profile để xác nhận. Lỗi 503 là lỗi mock sinh ngẫu nhiên, không tăng theo tải. Mỗi mức chỉ chạy một lần với 300 request, nên các mức cao kết thúc sau 5–6 giây và p99 dao động nhiều.

### 2.2 Tail latency (300 request, concurrency 20)

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|
| 0 | 201.7 | 251.2 | 287.5 |
| 0.03 (mặc định) | 268.7 | 286.8 | 1709.7 |
| 0.1 | 343.8 | 1695.1 | 1712.8 |

**Nhận xét:** Từ 0 lên 3 % request chậm, avg chỉ tăng 33 % còn p99 tăng gần 6 lần. p95 chưa đổi nhiều vì số request chậm vẫn dưới 5 %; khi lên 10 %, p95 nhảy lên khoảng 1,7 s. p99 nhạy nhất. Không nên đặt SLO theo average vì nó pha loãng số ít request rất chậm: ở mức 0.1, avg 344 ms trông vẫn ổn trong khi ít nhất 5 % người dùng chờ khoảng 1,7 s. Nên dùng p95 cho SLO và theo dõi thêm p99.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4.35 % (1/23) | 91.3 % (21/23) | 100 % (23/23) |
| Avg tokens / câu | 56.8 | 108.8 | 112.2 |
| Tổng cost (USD) | 0.000400 | 0.000758 | 0.000778 |
| Cost / câu đúng (USD) | 0.00039975 | 0.00003607 | 0.00003381 |
| Latency p95 (ms) | 187.3 | 213.5 | 357.3 |
| Quality gate (≥ 95 %) | FAIL | FAIL | PASS |

Gate cuối chạy với `--min-accuracy 1.0 --baseline reports/eval_v2.json`. Lần chạy lại để kiểm tra (không ghi đè file report) cho kết quả: 100 %, 2 câu cải thiện, 0 regression, `✅ PASS`, exit code 0. Latency p95 giữa các lần eval dao động (lần chạy lại là 225.6 ms) vì chỉ có 23 mẫu và mock có request chậm ngẫu nhiên.

**Những câu v2 trả lời sai ban đầu và cách sửa** (`develop/utils/mock_llm.py`, đã chép sang bản production):

| ID | Keyword bị thiếu | Đã sửa gì |
|---|---|---|
| `security-02` | `token`, `hết hạn`, `chữ ký` | Thêm mục JWT vào `KNOWLEDGE_BASE` |
| `scaling-03` | `cpu`, `memory`, `custom metrics` | Thêm mục Kubernetes HPA vào `KNOWLEDGE_BASE` |

**Trade-off v1 và v2:** v2 tốn gần gấp đôi token và chi phí mỗi câu do đưa context vào prompt, p95 trong eval cũng cao hơn một chút (214 ms so với 187 ms). Đổi lại số câu đúng tăng từ 1 lên 21, nên **cost / câu đúng rẻ hơn khoảng 11 lần**. So bằng cost / câu sẽ kết luận sai rằng v1 tốt hơn. Lưu ý: hai mục KB được viết sau khi đã biết câu sai, nên 100 % chỉ chứng minh không regression trên bộ này, không chứng minh chất lượng trên câu hỏi mới.

**Dùng exit code để chặn merge:** `run_eval.py` trả exit code 1 khi accuracy dưới `--min-accuracy` hoặc có regression so với `--baseline`. Trong CI (ví dụ GitHub Actions chạy trên `pull_request`), job khởi động agent rồi chạy script này. Exit code khác 0 làm job fail; bật branch protection bắt buộc job đó pass thì PR không merge được. Repo này chưa thêm file workflow.

### Metrics (Exercise 7.1)
- Counter: `http_requests_total`. Gauge: `agent_in_flight_requests`. Histogram: `agent_question_length_chars` (metric mới thêm; câu thử 40 ký tự nằm trong bucket `le="50"`).
- Nếu dùng URL thật làm label, mỗi URL lạ của bot tạo một time series mới, cardinality tăng không giới hạn và tốn bộ nhớ Prometheus. Khi thử gọi `/nope-123`, metric ghi `route="unmatched"`.

---

## 4. Observability stack (production)

### 4.1 Screenshot

- [x] [Dashboard Grafana khi có tải](screenshots/grafana-dashboard.png)
- [x] [Trace chậm trong Jaeger](screenshots/jaeger-slow-trace.png)
- [x] [Trace lỗi có event `exception`](screenshots/jaeger-error-trace.png)
- [x] [Prometheus: 3 alert cùng firing](screenshots/prometheus-alert-firing.png) (`AgentHighErrorRate`, `AgentHighLatencyP95`, `AgentInstanceDown`)

Ảnh được chụp khi bật đồng thời `MOCK_ERROR_RATE=0.2`, `MOCK_SLOW_RATE=0.3` và pause 1 trong 3 instance.

**Câu hỏi Exercise 7.4** (3 instance, 10 user Locust; không phải 2 instance, 30 user như đề gợi ý):
1. Lúc bình thường p95 khoảng 0,29 s, avg trên dashboard khoảng 0,2–0,25 s, p50 khoảng 0,2 s, còn p99 gần 1,8 s. avg và p95 gần nhau nghĩa là đa số request ổn định; khoảng cách lớn tới p99 cho thấy có một đuôi nhỏ rất chậm mà avg không thể hiện.
2. Khi cả 3 instance khoẻ, các đường trên panel "Requests/s theo instance" gần trùng nhau (khoảng 2 req/s mỗi instance): Nginx chia tương đối đều.
3. Input lớn hơn output (ví dụ một request: 81 và 46 token) vì v2 ghép context truy xuất được vào prompt.
4. `/metrics` qua Nginx trả **404** (đã gọi thử, trong khi `/health` trả 200) do cấu hình `location = /metrics`, để không lộ thông tin nội bộ ra ngoài. Prometheus scrape thẳng từng instance trong mạng Docker.

### 4.2 Thí nghiệm "phá hệ thống"

Cách đo: tải nền 10 user Locust, 3 instance. Thời gian tính từ lúc **bắt đầu** lệnh thay đổi (gồm cả thời gian tạo lại container) tới khi API Prometheus báo `firing`, kiểm tra mỗi 5 giây. Mỗi thí nghiệm chạy một lần.

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | `AgentHighErrorRate` | 90 s | Error rate (khoảng 1 % → 25 % tại thời điểm đo) |
| B | `MOCK_SLOW_RATE=0.3` | `AgentHighLatencyP95` | 140 s | Latency p95 (0,29 s → 1,91 s) |
| C | `LLM_MODEL=mock-llm-large` | `LLMCostBurnRateHigh` | 180 s | Cost burn rate (0,62 → 8,30 USD/giờ) |
| D | `docker pause` 1 instance | `AgentInstanceDown` | 40 s | Instances up, Requests/s theo instance |
| E | `AGENT_VERSION=v1` | Không alert nào firing (theo dõi 240 s) | — | Tokens/s (output khoảng 233 → 117 token/s) |

**Lưu ý về độ sạch của dữ liệu:** ở baseline của D, `LLMCostBurnRateHigh` còn firing từ thí nghiệm C. Nguyên nhân có khả năng là `--force-recreate` giữ lại volume dữ liệu của Prometheus, nên cửa sổ `rate(...[5m])` vẫn còn số liệu cũ. Vì vậy ở D chỉ tính `AgentInstanceDown`. Tương tự, baseline của E còn `AgentHighLatencyP95` ở trạng thái `pending` (p95 1,52 s); alert này không chuyển sang firing và p95 sau đó là 0,27 s.

**Thí nghiệm E không làm alert nào firing. Phát hiện loại sự cố này thế nào?** Latency, error rate và cost không đo được câu trả lời đúng hay sai. Cần đo chất lượng trực tiếp: (1) chạy eval golden dataset trong CI để chặn trước khi deploy (v1 chỉ đạt 4,35 %); (2) chạy eval định kỳ trên môi trường thật, đẩy accuracy thành metric và đặt alert; (3) chấm mẫu traffic thật (người chấm hoặc LLM-as-judge) và theo dõi feedback người dùng. Tín hiệu gián tiếp như output token giảm một nửa, panel phiên bản đổi sang v1, hay mất span `agent.retrieve_context` giúp phát hiện sớm nhưng không thay được eval.

Unit test cho alert rules (`promtool test rules alert_rules_test.yml`): `SUCCESS`.

### 4.3 Debug bằng trace

Trace chậm nhất trong log của 4 phút ngay trước khi chụp:

- `trace_id`: `7adc38e8738cc9019dfcc43d242d7e2f`
- Tổng thời gian (span `POST /ask`): 1723.0 ms
- Span chiếm nhiều thời gian nhất: `chat mock-llm-small` (1696.3 ms, 98,5 %); `agent.retrieve_context` chỉ 24.6 ms
- Dòng log cùng `trace_id`:

```json
{"ts": "2026-11-26T10:40:14.334966+00:00", "level": "INFO", "service": "observable-agent", "instance": "51810c44fe4e", "event": "llm_call", "trace_id": "7adc38e8738cc9019dfcc43d242d7e2f", "span_id": "126df79acd8c63ed", "request_id": "0c7c15e99e24", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 81, "output_tokens": 46, "cost_usd": 4e-05, "llm_ms": 1695.9}
```

Kết luận: request chậm là do bước gọi LLM, không phải retrieval hay code của agent.

**Trace lỗi:** `7f51141a41383f01bd2c97a73343e79c`, tổng 94.2 ms, span `chat mock-llm-small` có event `exception` (`utils.mock_llm.LLMError`), HTTP 503.

```json
{"ts": "2026-11-26T10:41:32.251359+00:00", "level": "INFO", "service": "observable-agent", "instance": "51810c44fe4e", "event": "llm_error", "trace_id": "7f51141a41383f01bd2c97a73343e79c", "span_id": "142d65b98fa88701", "request_id": "d1b38cd1dc1b", "error": "Upstream LLM error: 503 Service Unavailable (mock)"}
```

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

Số liệu dòng `/ask` trong `scale_1_stats.csv` và `scale_3_stats.csv`.

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | 50.81 | 210 | 1800 | 3800 | 51 / 6047 (0.84 %) |
| 3 | 59.02 | 190 | 260 | 1700 | 80 / 7023 (1.14 %) |

Chạy bằng `docker compose run --rm --no-deps locust ...`. Cần `--no-deps`: lần đo trước không có cờ này cho kết quả gần như giống nhau giữa "1" và "3" instance, và log của lượt "1 instance" có cả `agent-2`. Nhiều khả năng `compose run` đã đưa số agent về `replicas: 2` trong file compose, nên số đó đã bị loại. Ở lần đo này, `docker ps` giữa mỗi lượt xác nhận đúng 1 và 3 container agent.

**Giải thích:** Scale từ 1 lên 3 cải thiện rõ đuôi latency: p95 giảm từ 1800 xuống 260 ms, p99 từ 3800 xuống 1700 ms. p50 gần như không đổi vì phần lớn thời gian là độ trễ cố định của mock LLM. RPS chỉ tăng 16 % vì Locust mô phỏng 100 user có nghỉ 0,5–2 giây giữa các request, nên tải bị giới hạn từ phía người dùng. p99 còn khoảng 1,7 s là các request chậm do mock cố ý tạo (`MOCK_SLOW_RATE=0.03`), scale không loại được.

Nút thắt ở 1 instance **có khả năng** là giới hạn 0,5 CPU của container (request phải chờ nhau). Bằng chứng chưa đủ: chỉ có một mẫu `docker stats` giữa lượt (khoảng 33 % một core), chưa đo CPU throttling. Mỗi cấu hình chỉ chạy một lần; trong lượt 1 instance, Grafana lúc lấy mẫu dùng khoảng 77 % CPU (vừa khởi động), có thể làm số của lượt đó xấu hơn.

---

## 6. Kết luận

- 3 điều rút ra về benchmark & observability:
  1. Average che mất đuôi latency; SLO nên dựa trên percentile.
  2. Phải kiểm tra điều kiện đo, không chỉ đọc kết quả: một cờ thiếu (`--no-deps`) đã làm so sánh scaling vô nghĩa.
  3. Metrics, trace và log trả lời ba câu khác nhau (có vấn đề không, chậm ở bước nào, request đó bị gì), nhưng không cái nào đo được câu trả lời đúng; cần eval riêng.
- Nếu đưa lên production thật, sẽ thêm: điểm chất lượng từ eval định kỳ và alert khi giảm; tỷ lệ retrieval không tìm thấy tài liệu; alert p99; CPU throttling và bộ nhớ của container; số request bị 429 và 402; alert khi không còn request nào đi qua; gửi alert qua Alertmanager tới kênh trực.
