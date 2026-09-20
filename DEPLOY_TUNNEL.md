# Deploy: Vercel + Cloudflare Tunnel

Trang public **đầy đủ tính năng**, **miễn phí**. Đổi lại phần Giọng nói / Hình
ảnh chỉ chạy khi máy bạn đang mở.

---

# PHẦN 1 — MỖI LẦN MUỐN CHẠY THÌ MỞ GÌ

Đây là phần bạn cần nhất. Đọc xong phần này là dùng được hằng ngày.

## Trường hợp A — Chỉ làm việc trên máy mình (không cần ai khác vào)

Bấm đúp **`start.bat`**.

Nó tự mở 2 cửa sổ đen và tự mở trình duyệt vào `http://localhost:5173`.
Xong. Không cần gì thêm.

> Tắt: đóng 2 cửa sổ đen đó.

## Trường hợp B — Muốn người khác vào trang public được

Bấm đúp **`start-tunnel.bat`**.

Nó mở **2 cửa sổ đen**:

| Cửa sổ | Tên | Nhiệm vụ |
|---|---|---|
| 1 | `Clarivo AI backend - port 8000` | Chạy AI Giọng nói + Hình ảnh |
| 2 | `Clarivo tunnel` | Nối máy bạn ra internet |

**Cả 2 cửa sổ phải để yên, không được đóng.** Đóng là trang public mất phần
Giọng nói / Hình ảnh ngay.

Bạn **không cần** chạy `start.bat` nữa — `start-tunnel.bat` đã bao gồm backend.
Frontend thì đã nằm trên Vercel rồi, máy bạn không cần chạy frontend.

### Nếu dùng quick tunnel (địa chỉ ngẫu nhiên)

Mỗi lần mở `start-tunnel.bat`, địa chỉ **đổi mới**. Nên mỗi lần bạn phải:

1. Nhìn cửa sổ **Clarivo tunnel**, tìm dòng `https://....trycloudflare.com`
2. Vào Vercel → project frontend → Settings → Environment Variables
3. Sửa `VITE_LOCAL_AI_BASE_URL` thành địa chỉ mới
4. Deployments → Redeploy

Mất khoảng 2 phút mỗi lần. **Phiền** — nên làm Phần 4 (đường hầm cố định) để
không bao giờ phải làm lại bước này nữa.

## Tóm tắt

| Bạn muốn | Mở cái gì | Để yên cửa sổ nào |
|---|---|---|
| Làm việc một mình | `start.bat` | 2 cửa sổ đen |
| Người khác vào được | `start-tunnel.bat` | 2 cửa sổ đen |

---

# PHẦN 2 — Trang hoạt động thế nào

```
                 Frontend Vercel (luôn bật, miễn phí)
                               │
          ┌────────────────────┴─────────────────────┐
   VITE_API_BASE_URL                     VITE_LOCAL_AI_BASE_URL
          │                                          │
  Backend Vercel (luôn bật)              Cloudflare Tunnel → máy bạn
  • Phiên âm Whisper                     • Giọng nói
  • Chấm nội dung (Qwen)                 • Hình ảnh (OpenVINO, NPU/GPU)
  • Q&A drills                           • Upload tới 1 GB
  • Thư viện chủ đề
```

Hai đường **tách biệt**. Máy bạn tắt thì trang **vẫn sống**:

| Máy bạn | Nội dung + Q&A | Giọng nói | Hình ảnh |
|---|---|---|---|
| Đang mở | ✅ | ✅ | ✅ |
| Đã tắt | ✅ | ⚠️ tạm ngừng | ⚠️ tạm ngừng |

Khi bạn bật máy lại, trang **tự nhận ra trong ~15 giây** và Giọng nói / Hình ảnh
hiện lại — người dùng không cần tải lại trang.

---

# PHẦN 3 — Cài đặt lần đầu

Chỉ làm một lần.

## 3.1 — Cài cloudflared

Mở PowerShell:

```powershell
winget install --id Cloudflare.cloudflared
```

Đóng PowerShell, mở lại (để lệnh `cloudflared` nhận vào hệ thống).

## 3.2 — Sửa `backend\.env`

```env
LOCAL_SCORING_ENABLED=true
ALLOWED_ORIGINS=https://clarivo-kohl.vercel.app
```

> ⚠️ **Lỗi hay gặp nhất.** `ALLOWED_ORIGINS` phải khớp **từng ký tự** với địa chỉ
> frontend. Không có dấu `/` ở cuối. `localhost` và `127.0.0.1` là hai địa chỉ
> **khác nhau**. Sai một ký tự là trình duyệt chặn (CORS) và bạn chỉ thấy
> "Failed to fetch" mà không rõ lý do.

Nhiều địa chỉ thì ngăn bằng dấu phẩy, không có khoảng trắng:

```env
ALLOWED_ORIGINS=https://clarivo-kohl.vercel.app,https://clarivo-git-main-khoanhd.vercel.app
```

## 3.3 — Mở tunnel và lấy địa chỉ

Bấm đúp `start-tunnel.bat`. Trong cửa sổ **Clarivo tunnel**, tìm:

```
https://random-words-here.trycloudflare.com
```

## 3.4 — Nối Vercel với tunnel

Vercel → project **frontend** → Settings → Environment Variables:

| Tên | Giá trị |
|---|---|
| `VITE_API_BASE_URL` | `https://clarivo-phi.vercel.app` |
| `VITE_LOCAL_AI_BASE_URL` | địa chỉ tunnel ở bước 3.3 |

Rồi **Deployments → Redeploy**.

> `VITE_*` được **nhúng vào lúc build**, không đọc lúc chạy. Đổi giá trị là
> **bắt buộc phải build lại**.

## 3.5 — Nghiệm thu

```bash
curl https://<dia-chi-tunnel>/api/health
```

Phải thấy `"audio_ready": true, "vision_ready": true`.

Rồi mở trang Vercel, kiểm 5 việc:

- [ ] Chọn một chủ đề → thấy nút **"+ Reference content"**
- [ ] Nộp transcript → ra báo cáo nội dung
- [ ] Tải lên một video → ra điểm **Giọng nói** và **Hình ảnh**
- [ ] Đóng cửa sổ tunnel → tải lại trang → nội dung vẫn chạy, Hình ảnh báo
      *"The machine that runs voice and visual analysis is offline right now"*
- [ ] Mở lại `start-tunnel.bat` → **không** tải lại trang → Hình ảnh tự hiện lại

---

# PHẦN 4 — Đường hầm cố định (named tunnel)

## Nó là gì, và tại sao cần

Có hai loại đường hầm:

| | Quick tunnel | Named tunnel |
|---|---|---|
| Lệnh | `cloudflared tunnel --url ...` | `cloudflared tunnel run <tên>` |
| Địa chỉ | `abc-xyz.trycloudflare.com` | `ai.tenmiencuaban.com` |
| **Đổi mỗi lần chạy?** | **Có** ❌ | **Không** ✅ |
| Cần tài khoản Cloudflare? | Không | Có |
| Cần tên miền? | Không | **Có** |
| Phải redeploy Vercel mỗi lần? | **Có** | Không |

Vấn đề của quick tunnel: `VITE_LOCAL_AI_BASE_URL` nhúng lúc build. Địa chỉ đổi
→ phải sửa biến → phải redeploy → chờ vài phút. **Mỗi lần bật máy.**

Named tunnel gắn đường hầm vào một tên miền bạn sở hữu. Địa chỉ cố định vĩnh
viễn → đặt `VITE_LOCAL_AI_BASE_URL` **một lần duy nhất**, không bao giờ đụng lại.

## Điều kiện

Bạn cần **một tên miền** đã được quản lý bởi Cloudflare. Nếu chưa có:

1. Mua một tên miền rẻ (`.io.vn`, `.site`, `.xyz` — khoảng 50–250 nghìn/năm)
2. Vào <https://dash.cloudflare.com> → Add a site → nhập tên miền
3. Cloudflare cho bạn 2 địa chỉ nameserver → vào nơi mua tên miền, đổi
   nameserver sang 2 địa chỉ đó
4. Chờ Cloudflare báo "Active" (thường vài phút đến vài giờ)

> Không có tên miền thì **không làm được** named tunnel. Lúc đó cứ dùng quick
> tunnel và chấp nhận redeploy mỗi lần.

## Các bước

### Bước 1 — Đăng nhập

```powershell
cloudflared tunnel login
```

Trình duyệt mở ra → chọn tên miền của bạn → Authorize.
Lệnh này lưu chứng chỉ vào `%USERPROFILE%\.cloudflared\cert.pem`.

### Bước 2 — Tạo đường hầm

```powershell
cloudflared tunnel create clarivo
```

In ra một dòng như:

```
Created tunnel clarivo with id 6ff42ae2-765d-4adf-8112-31c55c1551ef
```

**Ghi lại cái id đó**, lát nữa cần.

Nó cũng tạo file `%USERPROFILE%\.cloudflared\<id>.json` — đây là khoá bí mật,
**không đưa cho ai, không commit lên GitHub**.

### Bước 3 — Gắn tên miền vào đường hầm

```powershell
cloudflared tunnel route dns clarivo ai.tenmiencuaban.com
```

Đổi `ai.tenmiencuaban.com` thành tên miền phụ bạn muốn. Lệnh này tự tạo bản ghi
DNS trên Cloudflare, bạn không phải vào web bấm gì.

### Bước 4 — Viết file cấu hình

Tạo file `%USERPROFILE%\.cloudflared\config.yml` (mở Notepad, Save as, chọn
"All files", đặt tên đúng `config.yml`):

```yaml
tunnel: clarivo
credentials-file: C:\Users\dangkhoa\.cloudflared\6ff42ae2-765d-4adf-8112-31c55c1551ef.json

ingress:
  - hostname: ai.tenmiencuaban.com
    service: http://127.0.0.1:8000
  - service: http_status:404
```

Ba chỗ phải sửa cho đúng máy bạn:

- `credentials-file` — đường dẫn thật tới file `.json` ở Bước 2
- `hostname` — tên miền ở Bước 3
- `service` — để nguyên `http://127.0.0.1:8000` (backend chạy ở cổng 8000)

> Dòng `- service: http_status:404` cuối là bắt buộc. Nó nói "mọi thứ khác thì
> trả 404". Thiếu dòng này cloudflared sẽ báo lỗi cấu hình.

### Bước 5 — Chạy thử

```powershell
cloudflared tunnel run clarivo
```

Mở trình duyệt vào `https://ai.tenmiencuaban.com/api/health` — phải thấy JSON có
`"vision_ready": true`.

### Bước 6 — Đặt vào Vercel (lần cuối cùng)

`VITE_LOCAL_AI_BASE_URL=https://ai.tenmiencuaban.com` → Redeploy.

**Từ giờ không bao giờ phải sửa biến này nữa.**

### Bước 7 — Sửa `start-tunnel.bat` để dùng named tunnel

Mở `start-tunnel.bat`, tìm dòng gần cuối:

```bat
start "Clarivo tunnel" cmd /k "cloudflared tunnel --url http://127.0.0.1:%PORT%"
```

Đổi thành:

```bat
start "Clarivo tunnel" cmd /k "cloudflared tunnel run clarivo"
```

Xong. Từ nay mỗi lần chỉ cần bấm đúp `start-tunnel.bat`, không phải làm gì thêm.

---

# PHẦN 5 — Trước buổi chấm

- [ ] **Tắt chế độ ngủ của Windows.** Settings → System → Power & battery →
      Screen and sleep → đặt tất cả thành **Never**. Máy ngủ là đường hầm đứt.
- [ ] Cắm sạc.
- [ ] Dùng mạng dây hoặc Wi-Fi ổn định (video của người chấm đi qua mạng nhà bạn).
- [ ] Mở `start-tunnel.bat`, đợi cả 2 cửa sổ chạy ổn định.
- [ ] Thử toàn bộ từ **một máy khác** (điện thoại dùng 4G là cách kiểm nhanh
      nhất — nó chắc chắn không đi qua mạng nhà bạn).
- [ ] Nếu còn dùng quick tunnel: cập nhật `VITE_LOCAL_AI_BASE_URL` và redeploy
      **trước**, rồi mới demo.

---

# PHẦN 6 — Khi có lỗi

| Hiện tượng | Nguyên nhân thường gặp |
|---|---|
| "Failed to fetch", console báo CORS | `ALLOWED_ORIGINS` không khớp **chính xác** địa chỉ frontend |
| Giọng nói / Hình ảnh luôn "unavailable" | Chưa redeploy sau khi đặt `VITE_LOCAL_AI_BASE_URL`; hoặc chưa chạy `start-tunnel.bat` |
| Đang chạy tự nhiên dừng | Máy ngủ, hoặc lỡ đóng một trong 2 cửa sổ đen |
| Upload video bị từ chối vì dung lượng | Kiểm `limits.max_video_bytes` ở `/api/health` của tunnel |
| Tải video lên nhưng transcript trống | Bình thường nếu video không có tiếng. Cứ tự gõ transcript — Hình ảnh vẫn chấm được |
| Nội dung cũng hỏng | Đây là backend Vercel, không liên quan tunnel — kiểm `clarivo-phi.vercel.app/api/health` |
| `cloudflared` báo lỗi config | Thiếu dòng `- service: http_status:404` ở cuối `ingress` |

## Xem lỗi thật của backend

Cửa sổ **Clarivo AI backend** in đầy đủ traceback khi có lỗi. Đó là nơi đầu tiên
nên nhìn khi có gì không chạy.

---

# PHẦN 7 — Nếu sau này muốn bỏ hẳn việc phải mở máy

Xem `DEPLOY_PUBLIC_VERCEL.md` về giới hạn nền tảng. Hai hướng:

- **Container trả phí** (~5 USD/tháng, Railway hoặc Fly.io) — Hình ảnh chạy
  24/7 nhưng chỉ có CPU, chậm hơn khoảng 2,6 lần
- **Chuyển Hình ảnh vào trình duyệt** — miễn phí và luôn bật, nhưng phải viết
  lại tầng model (~30% code vision; toàn bộ phần chấm điểm giữ nguyên)
