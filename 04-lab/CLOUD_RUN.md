# Triển khai Weather MCP lên Cloud Run

Trạng thái: hướng dẫn chuẩn bị; chưa deploy vào Google Cloud.

Có thể dùng [gói source đã chuẩn bị](../reports/weather-mcp-cloud-run-source.zip) trong Cloud Shell: giải nén vào một thư mục rồi chạy lệnh deploy từ thư mục đó. Gói chỉ có năm file build, không chứa API key.

Image đã được build và kiểm tra MCP qua HTTP ở local với `PORT=8080`. Dependency server đã giới hạn `mcp<2` để giữ tương thích với `mcp.server.fastmcp`; kiểm tra container dùng MCP 1.30.0. Đây là bằng chứng local, chưa phải deployment Cloud Run.

Deploy từ source dùng Dockerfile trong `mcp-server`. Cloud Build và Artifact Registry thực hiện build/lưu image trên Google Cloud, nên không cần Docker local cho bước deploy. [Tài liệu chính thức](https://docs.cloud.google.com/run/docs/deploying-source-code).

## Chuẩn bị

Cần Google Cloud project có billing và API cần thiết, `gcloud` đã đăng nhập, service account dùng cho runtime, và WeatherAPI key. Các quyền deploy/build được mô tả trong [tài liệu deploy từ source](https://docs.cloud.google.com/run/docs/deploying-source-code).

Lưu key trong Secret Manager, rồi ánh xạ secret thành biến môi trường `WEATHERAPI_KEY`. Service account runtime cần quyền `roles/secretmanager.secretAccessor` trên secret đó. Dùng phiên bản secret cụ thể, không ghi key vào Dockerfile hoặc lệnh deploy. [Tài liệu secrets](https://docs.cloud.google.com/run/docs/configuring/services/secrets).

## Lệnh deploy dự kiến

Các lệnh Bash dưới đây dùng project, region, service account và secret đã có. Thay các giá trị mẫu trước khi chạy:

```bash
cd 04-lab/mcp-server

PROJECT_ID="keen-honor-491605-r5"
REGION="asia-southeast1"
SERVICE="weather-mcp"
RUNTIME_SERVICE_ACCOUNT="your-service-account@keen-honor-491605-r5.iam.gserviceaccount.com"
WEATHER_SECRET="weatherapi-key"
WEATHER_SECRET_VERSION="1"

gcloud run deploy "$SERVICE" \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --source=. \
  --service-account="$RUNTIME_SERVICE_ACCOUNT" \
  --update-secrets="WEATHERAPI_KEY=$WEATHER_SECRET:$WEATHER_SECRET_VERSION" \
  --port=8080 \
  --min=0 \
  --max=1 \
  --timeout=300 \
  --invoker-iam-check
```

Cloud Run đặt `PORT`; `weather.py` đã bind `0.0.0.0` và chọn Streamable HTTP khi biến này có mặt. [Container contract](https://docs.cloud.google.com/run/docs/container-contract).

Lệnh dự kiến giữ kiểm tra IAM. Client hiện tại chưa gửi Google identity token, nên kết nối trực tiếp tới service private còn cần cấu hình xác thực phía client. Nếu chọn public cho lab, có thể dùng `--no-invoker-iam-check` sau khi chủ project đồng ý cho phép truy cập công khai. [Tài liệu public access](https://docs.cloud.google.com/run/docs/authenticating/public).

Hai file `.dockerignore` và `.gcloudignore` giới hạn context/upload vào Dockerfile, `pyproject.toml`, `weather.py` và file ignore. `.env` và `.venv` không nằm trong source upload.

## Chuyển client và kiểm chứng

Lấy URL sau khi deploy:

```bash
gcloud run services describe "$SERVICE" \
  --project="$PROJECT_ID" --region="$REGION" \
  --format='value(status.url)'
```

Trong `04-lab/mcp-client/.env`, giữ `GOOGLE_API_KEY` và thêm URL thực tế:

```dotenv
MCP_SERVER_URL=https://your-service.run.app/mcp
```

Khởi động lại ADK rồi chạy:

```bash
cd ../mcp-client
uv run --frozen python verify_setup.py
uv run --frozen adk web
```

Checkpoint cần URL Cloud Run trong output verification và hai câu trả lời có dữ liệu thật từ tool. Lưu ảnh verification thành `screenshots/05-cloud-run.png` tại thư mục gốc repo, che phần key script in ra. GET có phản hồi dưới 500 chỉ chứng minh endpoint phản hồi; cần kiểm chứng `list_tools` và lời gọi thời tiết nữa.
