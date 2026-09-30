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

Nó mở **2 cửa sổ đen** và in ra **một đường link**:

| Cửa sổ | Tên | Nhiệm vụ |
|---|---|---|
| 1 | `Clarivo AI backend - port 8000` | Chạy AI Giọng nói + Hình ảnh |
| 2 | `Clarivo tunnel` | Nối máy bạn ra internet |

Sau khoảng 5–10 giây, cửa sổ chính in ra:

```
  ==================================================================
   LINK GUI CHO NGUOI KHAC (da co san dia chi AI ben trong):

   https://clarivo-kohl.vercel.app/?ai=https://abc-xyz.trycloudflare.com

  ==================================================================
```

**Gửi đúng đường link đó** cho ban giám khảo / bạn bè. Link đã được copy sẵn vào
clipboard và lưu ở file `SHARE_LINK.txt`, nên chỉ cần Ctrl+V.

Ai mở link đó sẽ dùng được **đầy đủ** Nội dung + Giọng nói + Hình ảnh.

> **Cả 2 cửa sổ phải để yên, không được đóng.** Đóng là phần Giọng nói / Hình
> ảnh tắt ngay (phần Nội dung và Q&A vẫn chạy bình thường).

Bạn **không cần** chạy `start.bat` nữa — `start-tunnel.bat` đã bao gồm backend.
Frontend đã nằm trên Vercel, máy bạn không cần chạy frontend.

### Tại sao phải có `?ai=...` trong link

Địa chỉ tunnel **đổi mỗi lần chạy**. Trang web đọc địa chỉ đó **lúc chạy**, từ
chính đường link — chứ không phải lúc build. Nhờ vậy đổi địa chỉ **không cần
build lại Vercel**, chỉ cần gửi link mới.

Link cũ (không có `?ai=`) vẫn mở được trang, nhưng sẽ báo *Voice + Visual: not
connected*. Khi đó bấm vào chữ đó ở góc trên bên phải rồi dán địa chỉ tunnel
vào ô hiện ra — cũng ra kết quả như nhau.

Trình duyệt **nhớ** địa chỉ này. Người đã mở link một lần thì lần sau vào thẳng
`https://clarivo-kohl.vercel.app` vẫn còn — cho tới khi bạn chạy lại tunnel và
địa chỉ đổi, lúc đó gửi lại link mới.

## Tóm tắt

| Bạn muốn | Mở cái gì | Gửi gì cho người khác |
|---|---|---|
| Làm việc một mình | `start.bat` | — |
| Người khác vào được | `start-tunnel.bat` | Đường link nó in ra |

---

# PHẦN 2 — Trang hoạt động thế nào

```
                 Frontend Vercel (luôn bật, miễn phí)
                               │
          ┌────────────────────┴─────────────────────┐
   VITE_API_BASE_URL                   ?ai=... trong đường link
   (nhúng lúc build, cố định)          (đọc lúc chạy, đổi được)
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
ALLOWED_ORIGIN_REGEX=https://clarivo-[a-z0-9-]+\.vercel\.app
PUBLIC_FRONTEND_URL=https://clarivo-kohl.vercel.app
```

| Biến | Để làm gì |
|---|---|
| `LOCAL_SCORING_ENABLED` | Bật Giọng nói + Hình ảnh trên máy này |
| `ALLOWED_ORIGINS` | Cho phép trang Vercel gọi vào máy này (CORS) |
| `ALLOWED_ORIGIN_REGEX` | Cho phép luôn các bản deploy preview của Vercel |
| `PUBLIC_FRONTEND_URL` | Để `start-tunnel.bat` tự ghép đường link chia sẻ |

> ⚠️ **Lỗi hay gặp nhất.** `ALLOWED_ORIGINS` phải khớp **từng ký tự** với địa chỉ
> frontend. Không có dấu `/` ở cuối. `localhost` và `127.0.0.1` là hai địa chỉ
> **khác nhau**. Sai một ký tự là trình duyệt chặn (CORS) và bạn chỉ thấy
> "Failed to fetch" mà không rõ lý do.

Vercel đặt tên khác nhau cho mỗi bản deploy (`clarivo-git-main-...`,
`clarivo-abc123-...`). Liệt kê từng cái thì không xuể, nên có
`ALLOWED_ORIGIN_REGEX` — một mẫu khớp mọi bản deploy **của riêng project bạn**.
Giữ phần `clarivo-` ở đầu; bỏ đi là mở cửa cho mọi trang `.vercel.app` trên đời.

Nhiều địa chỉ cố định thì ngăn bằng dấu phẩy, không có khoảng trắng:

```env
ALLOWED_ORIGINS=https://clarivo-kohl.vercel.app,https://clarivo.io.vn
```

## 3.3 — Mở tunnel và lấy link

Bấm đúp `start-tunnel.bat` rồi đợi khoảng 10 giây. Cửa sổ chính in ra đường link
đã ghép sẵn địa chỉ tunnel, đồng thời copy vào clipboard và lưu vào
`SHARE_LINK.txt`.

Nếu muốn tự chạy lại phần ghép link (tunnel đang mở sẵn):

```powershell
cd backend
.venv\Scripts\python.exe -m tools.share_link
```

## 3.4 — Đặt biến trên Vercel (một lần duy nhất)

Vercel → project **frontend** → Settings → Environment Variables:

| Tên | Giá trị |
|---|---|
| `VITE_API_BASE_URL` | `https://clarivo-phi.vercel.app` |

Rồi **Deployments → Redeploy**.

> ⚠️ **Nếu trên Vercel đang có biến `VITE_LOCAL_AI_BASE_URL` — hãy XOÁ nó đi**
> (Settings → Environment Variables → dấu ba chấm → Remove → rồi Redeploy).
>
> Biến đó nhúng lúc build. Nếu nó đang trỏ tới một địa chỉ quick tunnel cũ (đã
> chết), thì người mở trang **không kèm** `?ai=...` sẽ thấy *Voice + Visual:
> offline* — cả Giọng nói lẫn Hình ảnh đều tắt.
>
> Xoá nó đi thì người mở trang trơn sẽ thấy *Voice ready · Visual off*: Giọng
> nói vẫn chấm được bằng backend Vercel, chỉ Hình ảnh là cần tunnel. Đó là mặc
> định đúng hơn.
>
> Chỉ đặt lại biến này khi bạn có **đường hầm cố định** (Phần 4) — địa chỉ không
> đổi nên nhúng lúc build mới có ý nghĩa.

## 3.5 — Nghiệm thu

```bash
curl https://<dia-chi-tunnel>/api/health
```

Phải thấy `"audio_ready": true, "vision_ready": true`.

Rồi mở **đường link mà `start-tunnel.bat` in ra** và kiểm 6 việc:

- [ ] Góc trên bên phải hiện **Voice + Visual: ready** (chấm xanh)
- [ ] Chọn một chủ đề → thấy nút **"+ Reference content"**
- [ ] Nộp transcript → ra báo cáo nội dung
- [ ] Tải lên một video → ra điểm **Giọng nói** và **Hình ảnh**
- [ ] Đóng cửa sổ tunnel → chờ ~15 giây → chip đổi thành **offline**, nội dung
      vẫn chạy bình thường
- [ ] Mở lại `start-tunnel.bat`, dán link mới → Hình ảnh hiện lại

> Nhờ người khác (khác máy, khác mạng — ví dụ điện thoại dùng 4G) mở thử đúng
> đường link đó. Đây là phép thử thật: máy bạn thì địa chỉ nào cũng chạy.

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
| Cần tên miền? | Không | **Có (tốn tiền)** |
| Phải gửi link mới mỗi lần? | **Có** | Không |
| Phải redeploy Vercel mỗi lần? | Không | Không |

**Quick tunnel đã đủ dùng.** Từ khi trang đọc địa chỉ lúc chạy, quick tunnel
không còn bắt bạn redeploy nữa — phiền duy nhất còn lại là mỗi lần chạy phải
gửi lại đường link mới.

Named tunnel giải quyết nốt phần đó: địa chỉ cố định vĩnh viễn, nên bạn đặt
`VITE_LOCAL_AI_BASE_URL` một lần trên Vercel rồi thôi — link chia sẻ trở thành
`https://clarivo-kohl.vercel.app` trơn, không cần `?ai=`.

Đổi lại: **phải có tên miền, và tên miền tốn tiền**. Bản thân Cloudflare Tunnel
và tài khoản Cloudflare đều miễn phí, không giới hạn băng thông.

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
- [ ] Gửi **đường link mới** mà `start-tunnel.bat` vừa in ra (địa chỉ tunnel
      đổi mỗi lần chạy, nên link của hôm qua đã chết).
- [ ] Mở link đó trên máy khác, xác nhận góc phải hiện **Voice + Visual: ready**.

---

# PHẦN 6 — Khi có lỗi

| Hiện tượng | Nguyên nhân thường gặp |
|---|---|
| "Failed to fetch", console báo CORS | `ALLOWED_ORIGINS` không khớp **chính xác** địa chỉ frontend |
| Giọng nói / Hình ảnh luôn "unavailable" | Mở bằng link **không có** `?ai=...`; hoặc chưa chạy `start-tunnel.bat` |
| Người khác không dùng được nhưng máy bạn thì được | Bạn đang mở `localhost`, họ mở Vercel. Gửi đúng link `?ai=...` |
| Link hôm qua nay không chạy | Quick tunnel đổi địa chỉ mỗi lần chạy. Gửi link mới |
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
