# FileGo: A Local Network-Based Academic File Sharing and Resource Management System

*Share Files. Exchange Knowledge. Stay Connected.*

FileGo lets students upload study materials to a shared library, send files privately to classmates and track how every transfer performed. One laptop runs the Flask server. Phones and other laptops open it in a browser over the same Wi-Fi or hotspot. No internet is needed after setup.

Built for **CMSC310 Computer Architecture and Organization** (file I/O, buffering, CPU and memory use) and **CMSC306 Networks and Communication** (LAN addressing, client-server communication, TCP/IP and HTTP, throughput and response time).

| Module | What it does |
|---|---|
| 1. User accounts | Register with full name, username and password. Login, logout, profile, active sessions. |
| 2. Shared library | Upload PDF, DOCX, PPTX, TXT and images. Search, filter by subject and type, preview PDFs and images, download. |
| 3. Direct sharing | Send a private file to a registered user. Inbox, Sent tab, Delivered/Downloaded status. |
| 4. My Files | Rename, change subject and category, public or private, delete, see sizes and download counts. |
| 5. Monitoring | Upload progress, duration and speed per transfer, live server CPU and RAM, history, success rate, SHA-256 integrity check. |
| 6. Administration | Users, storage, remove any file, system-wide statistics, CSV export. |

---

## 1. Quick start (Windows)

You need **Python 3.11 or newer** (tick "Add python.exe to PATH" when installing) and **Node.js 20 or newer**.

1. Double-click **`setup.bat`** once. It creates the Python environment, installs everything, builds the web interface and creates the demo accounts. It needs an internet connection the first time.
2. Double-click **`start-demo.bat`**. The window prints the addresses, for example:
   ```
   This computer:  http://localhost:5000
   On the network: http://192.168.43.10:5000   (Wi-Fi)
   ```
3. Open `http://localhost:5000` on the laptop, or the "On the network" address on a phone.

Demo accounts (created by the setup, password `demo123`; **for demonstration only**):

| Username | Name | Role |
|---|---|---|
| `student` | Demo Student | administrator |
| `alex` | Alex Rivera | student |
| `jamie` | Jamie Cruz | student |

All sample files are fake demonstration data.

Stop the server with `Ctrl+C` in its window. Your data stays in `backend\filego.db` and `backend\storage\`.

<details><summary>Manual setup (PowerShell), if you prefer not to use the scripts</summary>

```powershell
cd FileGo\backend
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python seed.py                 # demo accounts (only on a fresh database)
cd ..
npm install
npm run build                  # creates dist\, which the server then serves
cd backend
python run.py --stream
```
</details>

## 2. Using a phone over a hotspot

1. Turn on the phone's hotspot and connect the laptop to it.
2. Make sure Windows treats that network as **Private**, and allow the port once: double-click **`allow-firewall.bat`** and accept the administrator prompt. (Or in Windows Security, Firewall, allow inbound TCP port 5000 for Private networks.)
3. Start the server (`start-demo.bat`) and note the "On the network" address.
4. On the phone, open `http://<laptop-address>:5000/api/ping`. If it shows `{"pong":true,...}` the connection works. Then open `http://<laptop-address>:5000` and log in.

If the phone's own browser cannot reach the laptop over the phone's own hotspot (some phones block this):

- Turn on **Windows Mobile Hotspot** on the laptop (Settings, Network and Internet, Mobile hotspot), connect the phone to it, and use the laptop address shown by the server (normally `192.168.137.1`). Windows needs an existing connection to share.
- If that is not possible, use `http://localhost:5000` on the laptop as the "laptop client" and any second device on the same network as the "phone client".

The page loads its font from Google Fonts. Without internet the font falls back to the system font; everything else works.

## 3. Server modes

| Command | Mode | Use it for |
|---|---|---|
| `start-demo.bat` or `python run.py --stream` | **stream** (Werkzeug, threaded) | The live demo and **all experiments**. The request body is read from the socket as it arrives, so the measured server time includes the network. |
| `start-demo.ps1 -Stable` or `python run.py` | waitress | Everyday use. Waitress receives the whole upload before the app sees it, so its server time covers only disk and hashing. |

Both modes handle simultaneous uploads. Every logged transfer records the mode it ran in, and the Performance page warns when waitress rows are mixed into a comparison.

## 4. How a transfer works

- **Upload.** The browser sends the file as the raw request body (`XMLHttpRequest`, which also gives the progress bar). Metadata travels in the query string and the original name in the `X-File-Name` header. The server reads the body in chunks of the **buffer size** (64, 256 or 1024 KB; default 256), writes each chunk to a temporary file, updates the SHA-256 hash, then moves the file into `backend\storage\` under a random name. The user's filename is never used as a path.
- **Download.** The stored file is streamed back in chunks of the same buffer size, with `Content-Length` and an `X-File-SHA256` header. Downloads are always attachments. Only PDFs and images can be previewed inline.
- **What is measured for each transfer** (upload and download separately, success or failure): server time (first byte to last byte), time spent writing or reading the disk, time spent hashing, size, buffer size, system CPU average and peak, server process memory, number of simultaneous transfers, client device, server mode, response time to first byte, experiment label and network note. The browser also reports its own total time, shown beside the server's.
- **Integrity (SHA-256), three layers.** (1) The server hashes while writing and stores the digest. (2) A client may send `X-Expected-SHA256`; a mismatch rejects the upload (the benchmark tool does this, and verifies downloads against `X-File-SHA256`). (3) **Verify** in My Files re-reads the stored bytes and compares them with the stored digest, which detects disk corruption or tampering.
- **Failures** (client disconnect, size limit, disk full, hash mismatch) write a `failed` row, remove the partial file and leave no file or transfer behind.
- **Who can access what.** Public files: any logged-in user. Private files: the owner, the named recipient of a direct send, and administrators. Anyone else gets a 404, so a private file's existence is not revealed.
- **Download counter.** `Downloads` counts how many times *other* users downloaded a file you shared. Your own downloads, and a recipient downloading a file sent to them, do not count there. Every download still appears in Transfer History.

## 5. Running the experiments

Use stream mode, the laptop plugged in with the High performance power plan, and heavy apps closed. Record the network (Wi-Fi name, band, distance) as the *network note*.

**With the benchmark tool** (repeatable, no clicking). From the project folder, using the backend environment:

```powershell
backend\.venv\Scripts\python tools\benchmark.py --server http://localhost:5000 --user student --password demo123 `
  --test sizes --sizes 1,10,50 --repeat 5 --label "Test 1" --note "phone hotspot 2.4GHz, laptop on AC"
```

| Evaluation test | Command (add the server, user, label and note options above) |
|---|---|
| 1. File sizes 1, 10, 50 MB | `--test sizes --sizes 1,10,50 --repeat 5` |
| 2. Buffer sizes 64, 256, 1024 KB | `--test buffers --size-mb 10 --repeat 5` (administrator account) |
| 3. One vs two simultaneous uploads | `--test concurrency --size-mb 10 --repeat 5` |
| 4. Repeated transfers, success rate and SHA-256 | `--test repeat --size-mb 5 --repeat 20` |
| 5. Laptop vs phone, response time | `--test response --count 200` on the laptop; repeat Test 1 from the phone's browser with the same label scheme |

Run the tool from the laptop against `http://localhost:5000` for a no-network baseline, or from another computer against the laptop's address to include the network.

The first run of every batch is a warm-up: it is performed but left out of the statistics. The tool prints min, mean, median, 95th percentile and standard deviation, saves every measurement to `tools\results\<time>_<test>.csv` (open it in Excel) and deletes the files it uploaded. Its transfers also appear in the web interface as device `tool`.

**From the browser.** On the **Performance** page, an administrator can set an *experiment label* and *network note* that are stored with every following transfer, so uploads from the phone and the laptop can be grouped and compared. The comparison charts group by file size, buffer size, simultaneous transfers, client device or label. **History** and the Admin page export CSV files with every column.

## 6. Defense-day checklist

1. Laptop and phone on the same hotspot. Note the network name and band.
2. Run `allow-firewall.bat` once; confirm the hotspot network is Private.
3. Start the server with `start-demo.bat`. Open `http://<laptop-ip>:5000/api/ping` on the phone.
4. Plug the laptop in, High performance power plan, close heavy apps.
5. Rehearse the whole flow the night before: register, upload, send, download from the phone, Verify, open Performance.
6. Run the benchmark tool beforehand and keep the CSV files and chart screenshots as a backup in case the venue network is unreliable.
7. Keep a hotspot-capable phone as a backup network.
8. Copy the **whole project folder** to a USB drive. If you back up data only, copy `backend\filego.db` **and** `backend\storage\` together: the database refers to the stored files.

## 7. Development

```powershell
# backend (Windows PowerShell)
cd backend
.\.venv\Scripts\Activate.ps1
python run.py --stream           # API on http://localhost:5000
pytest                           # 278 tests, about 25 seconds

# frontend with hot reload, second terminal
cd ..
npm run dev                      # http://localhost:5173, forwards /api to port 5000
```

The browser always calls relative `/api` URLs. In development Vite forwards them to Flask (`VITE_API_PROXY` changes the target); in the demo the same Flask server serves the built `dist\` folder, so there is one address, one port and no CORS to configure.

Useful commands (run in `backend` with the environment active; `FLASK_APP` is set by `--app run`):

```powershell
python seed.py --reset                    # wipe and recreate the demo data
flask --app run create-admin              # real administrator account
flask --app run reset-password <username> # set a new password from the console
```

Configuration is by environment variables (all optional; see `backend\.env.example`): `SECRET_KEY`, `DATABASE_URL`, `STORAGE_DIR`, `MAX_UPLOAD_MB` (100), `BUFFER_KB` (256), `MIN_FREE_DISK_MB` (100), `REGISTRATION_MODE` (`open` or `closed`), `PORT` (5000), `CORS_ORIGINS`, `FRONTEND_DIST`, `FLASK_ENV`. With `FLASK_ENV=production` the server refuses to start without a real `SECRET_KEY`.

## 8. API reference

Base path `/api`. JSON in and out (camelCase keys), except uploads (raw body) and downloads (binary). Errors always look like `{"error": {"code": "not_found", "message": "..."}}`. Lists accept `page` and `perPage` (default 50, maximum 200) and return `{items, total, page, perPage}`.

Authentication is a server-side session in an `HttpOnly`, `SameSite=Lax` cookie. Login returns a `csrfToken`, which every request that changes data must send as the `X-CSRF-Token` header.

| Method and path | Purpose |
|---|---|
| `GET /health`, `GET /ping`, `GET /meta`, `GET /network` | Status, latency probe, subjects, categories, limits and server mode, LAN addresses |
| `POST /auth/register`, `POST /auth/login`, `POST /auth/logout`, `GET /auth/me` | Account and session |
| `GET /auth/sessions`, `DELETE /auth/sessions/:id` | List and revoke your sessions |
| `GET /users?q=`, `PATCH /users/me`, `POST /users/me/password` | Find recipients (id, name, username only), edit profile, change password |
| `GET /files?scope=library\|mine&q=&subject=&category=` | Library or your own files |
| `POST /files?title=&subject=&category=&visibility=` | Upload: file bytes are the body, `X-File-Name` header, optional `X-Expected-SHA256` |
| `GET /files/:id`, `PATCH /files/:id`, `DELETE /files/:id` | Details, edit title, subject, category, visibility, delete |
| `GET /files/:id/download`, `GET /files/:id/preview`, `POST /files/:id/verify` | Download, inline preview (PDF and images), integrity check |
| `POST /transfers?recipientId=` | Send a file privately (same body rules as an upload) |
| `GET /transfers?box=received\|sent`, `GET /transfers/unread-count` | Inbox, Sent, new-file badge |
| `GET /stats/me` | Dashboard counters |
| `GET /history`, `GET /history/export.csv`, `POST /history/:id/client-timing` | Your transfer log, CSV export, report the browser's own timing |
| `GET /metrics/live`, `GET /metrics/summary?groupBy=size\|buffer\|concurrency\|device\|label`, `GET`/`PUT /metrics/experiment` | Live CPU and RAM, comparison data for the charts, experiment label (PUT: administrators) |
| `GET /admin/users`, `PATCH /admin/users/:id`, `POST /admin/users/:id/reset-password` | Administrators: list, activate or deactivate, change role, issue a temporary password |
| `GET /admin/files`, `DELETE /admin/files/:id`, `GET /admin/stats`, `GET /admin/transfers/export.csv` | Administrators: all files, remove, system statistics, every transfer as CSV |

Limits: 100 MB per file (`Content-Length` is required and checked again while reading). Allowed types: `pdf`, `docx`, `pptx`, `txt`, `png`, `jpg`, `jpeg`, `gif`, `webp`; the first bytes must match the extension. Only administrators may choose the buffer size (`?bufferKb=64|256|1024`).

## 9. Security notes and limitations

- **Plain HTTP.** The demo runs over HTTP on a private network, so a person sniffing that network could read passwords and session cookies. Use a hotspot or classroom network you trust, and do not reuse a password from another service.
- **Passwords** are stored as salted scrypt hashes. Login is rate limited (5 failures per 15 minutes per username, 20 per address). Deactivating an account, an administrator password reset, or changing your own password signs the affected sessions out immediately.
- **Registration is open** by default: anyone who can reach the server can create a student account and read the public library. Set `REGISTRATION_MODE=closed` to stop that. Administrator accounts can only be created from the seed script or `flask create-admin`.
- **Administrators can see and remove every file, including private ones.**
- **Deleting a file you sent also removes it from the recipient's inbox.**
- Uploaded files are not scanned for malware. They are never executed or opened by the server.
- The rate limiter lives in memory and resets when the server restarts.
- Measurements come from the same laptop that serves the files, and Python adds its own overhead. Compare conditions against each other rather than against hardware limits, and repeat each test.
- The demo accounts and `demo123` are for development and the defense only.
- `node_modules` is currently tracked in Git. To remove it from the repository run `git rm -r --cached node_modules`, then commit and push; `.gitignore` already prevents it from being added again.

## 10. Project layout

```
backend/
  app/            Flask application (auth, files, transfers, insights, admin, monitor, spa)
  tests/          pytest suite
  run.py          starts the server (--stream or waitress)
  seed.py         demo accounts and fake sample files
  requirements.txt
scripts/          Windows setup, start and firewall scripts (used by the .bat files)
tools/benchmark.py  automated experiments, results in tools/results/
src/              React interface (main.jsx, api.js, style.css)
dist/             built interface (created by npm run build; not committed)
```
