# Deploy: Vercel + Cloudflare Tunnel

Cách này cho trang public **đầy đủ tính năng** mà **không tốn tiền**, đổi lại
phần Giọng nói / Hình ảnh chỉ chạy khi máy bạn đang mở.

## Kiến trúc

```
                        Frontend Vercel (luôn bật, miễn phí)
                                    │
             ┌──────────────────────┴───────────────────────┐
             │                                              │
   VITE_API_BASE_URL                          VITE_LOCAL_AI_BASE_URL
             │                                              │
    Backend Vercel (luôn bật)                  Cloudflare Tunnel
    • phiên âm Whisper                                  │
    • chấm nội dung (Qwen)                       Máy của bạn
    • Q&A drills                                 • Giọng nói
    • thư viện chủ đề                            • Hình ảnh (OpenVINO, NPU/GPU)
                                                 • upload tới 1 GB
```

Hai đường tách biệt. **Máy bạn tắt thì trang vẫn chạy** — chỉ Giọng nói và
Hình ảnh báo tạm thời không khả dụng, và **tự hiện lại** khi bạn bật máy, không
cần người dùng tải lại trang.

| Máy bạn | Nội dung + Q&A | Giọng nói | Hình ảnh |
|---|---|---|---|
| Mở | ✅ | ✅ | ✅ |
| Tắt | ✅ | ⚠️ tạm ngừng | ⚠️ tạm ngừng |

---

## Bước 1 — Backend Vercel (đã xong)

Giữ nguyên như hiện tại. Kiểm tra:

```bash
curl https://clarivo-phi.vercel.app/api/health
```

Cần thấy `"provider":"cloudflare"`. Phần `delivery_analysis` ở đây **không
quan trọng nữa** — frontend sẽ hỏi backend tunnel về khả năng Giọng nói/Hình ảnh.

> Nếu bạn đã bật `LOCAL_SCORING_ENABLED=true` trên Vercel thì đổi lại thành
> `false`. Backend serverless không chạy được phần đó, để `true` chỉ gây nhầm.

## Bước 2 — Cài cloudflared trên máy bạn

Mở PowerShell:

```powershell
winget install --id Cloudflare.cloudflared
```

Đóng và mở lại PowerShell để `cloudflared` vào PATH.

## Bước 3 — Cho backend máy bạn chấp nhận frontend Vercel

Mở `backend\.env`, đặt đúng địa chỉ frontend (**không có dấu `/` ở cuối**):

```env
ALLOWED_ORIGINS=https://clarivo-kohl.vercel.app
LOCAL_SCORING_ENABLED=true
```

> **Đây là lỗi hay gặp nhất.** Origin phải khớp **từng ký tự**. `localhost` và
> `127.0.0.1` là hai origin khác nhau; có hay không dấu `/` cuối cũng khác nhau.
> Sai một ký tự là trình duyệt chặn bằng CORS và bạn sẽ thấy "Failed to fetch"
> mà không rõ lý do.

Nhiều địa chỉ thì ngăn bằng dấu phẩy:

```env
ALLOWED_ORIGINS=https://clarivo-kohl.vercel.app,https://clarivo-git-main-khoanhd.vercel.app
```

## Bước 4 — Mở đường hầm

Bấm đúp **`start-tunnel.bat`**. Script sẽ:

1. kiểm tra `.venv`, thư viện AI, model OpenVINO, `cloudflared`
2. bật backend AI ở cổng 8000 (tắt `--reload` vì đây là phục vụ công khai)
3. mở đường hầm và in ra địa chỉ

Tìm dòng này trong cửa sổ **Clarivo tunnel**:

```
https://random-words-here.trycloudflare.com
```

## Bước 5 — Nối frontend Vercel với đường hầm

Vercel → project **frontend** → Settings → Environment Variables → thêm:

| Tên | Giá trị |
|---|---|
| `VITE_API_BASE_URL` | `https://clarivo-phi.vercel.app` |
| `VITE_LOCAL_AI_BASE_URL` | `https://random-words-here.trycloudflare.com` |

Rồi **Redeploy** frontend.

> `VITE_*` được **nhúng lúc build**, không đọc lúc chạy. Đổi giá trị là **phải
> build lại**. Đây là lý do nên dùng đường hầm cố định ở phần dưới.

## Bước 6 — Nghiệm thu

```bash
curl https://random-words-here.trycloudflare.com/api/health
```

Phải thấy:

```json
"delivery_analysis": {
  "enabled": true, "audio_ready": true, "vision_ready": true,
  "mode": "local_openvino",
  "limits": { "max_video_bytes": 1024000000 }
}
```

Rồi mở trang Vercel và kiểm:

- [ ] Chọn một chủ đề → thấy nút **"+ Reference content"**
- [ ] Nộp một transcript → ra báo cáo nội dung
- [ ] Thu hoặc tải lên một video → thấy điểm **Giọng nói** và **Hình ảnh**
- [ ] Tắt `start-tunnel.bat` → tải lại trang → nội dung vẫn chạy, Hình ảnh báo
      *"The machine that runs voice and visual analysis is offline right now"*
- [ ] Bật lại → **không tải lại trang** → Hình ảnh tự hiện lại trong ~15 giây

---

## Đường hầm cố định (nên làm trước buổi chấm)

Quick tunnel đổi địa chỉ mỗi lần chạy, mà đổi là phải build lại Vercel. Với
named tunnel, địa chỉ cố định vĩnh viễn. Cần một domain đã trỏ về Cloudflare.

```powershell
cloudflared tunnel login
cloudflared tunnel create clarivo
cloudflared tunnel route dns clarivo ai.tenmiencuaban.com
```

Tạo file `%USERPROFILE%\.cloudflared\config.yml`:

```yaml
tunnel: clarivo
credentials-file: C:\Users\<ten-user>\.cloudflared\<tunnel-id>.json

ingress:
  - hostname: ai.tenmiencuaban.com
    service: http://127.0.0.1:8000
  - service: http_status:404
```

Chạy:

```powershell
cloudflared tunnel run clarivo
```

Rồi đặt `VITE_LOCAL_AI_BASE_URL=https://ai.tenmiencuaban.com` **một lần duy nhất**.

---

## Trước buổi chấm

- [ ] **Tắt chế độ ngủ của Windows.** Settings → Power → Screen and sleep →
      đặt *Never*. Máy ngủ là đường hầm đứt.
- [ ] Cắm sạc.
- [ ] Dùng mạng dây hoặc Wi-Fi ổn định. Video của giám khảo đi qua mạng nhà bạn.
- [ ] Chạy thử toàn bộ từ một máy khác (điện thoại 4G là nhanh nhất để kiểm).
- [ ] Nếu dùng quick tunnel: mở `start-tunnel.bat` **trước**, lấy địa chỉ mới,
      cập nhật Vercel, redeploy, rồi mới bắt đầu demo.

## Khi có lỗi

| Hiện tượng | Nguyên nhân thường gặp |
|---|---|
| "Failed to fetch", console báo CORS | `ALLOWED_ORIGINS` không khớp **chính xác** địa chỉ frontend |
| Giọng nói/Hình ảnh luôn "unavailable" | Chưa redeploy frontend sau khi đặt `VITE_LOCAL_AI_BASE_URL`; hoặc `start-tunnel.bat` chưa chạy |
| Chạy được rồi bỗng dừng | Máy ngủ, hoặc cửa sổ tunnel bị đóng |
| Tải video lên bị từ chối | Kiểm tra `limits.max_video_bytes` ở `/api/health` của tunnel |
| Nội dung cũng hỏng | Đây là backend Vercel, không liên quan tunnel — kiểm `clarivo-phi.vercel.app/api/health` |

## Nếu sau này muốn bỏ hẳn việc phải mở máy

Xem `DEPLOY_PUBLIC_VERCEL.md` mục về giới hạn nền tảng. Hai hướng:

- container trả phí (~5 USD/tháng) — chạy Hình ảnh 24/7 nhưng chỉ có CPU
- chuyển Hình ảnh vào trình duyệt — miễn phí và luôn bật, nhưng phải viết lại
  tầng model (~30% code vision; phần chấm điểm giữ nguyên)
