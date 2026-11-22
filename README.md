# FileGo — Academic Sharing Hub (Frontend Prototype)

A responsive React + Vite frontend for an academic file-sharing system, with shared library, direct sharing, file management, inbox, transfer history, performance demo, and administration.

## Start

1. Install Node.js 20+.
2. In this folder, run `npm install`.
3. Run `npm run dev`.
4. Open the address shown in the terminal (typically `http://localhost:5173`).

Demo login: `student@filego.local` / `demo123` (administrator). Additional demo users: `alex@filego.local` and `jamie@filego.local`, both with password `demo123`.

## Included routes

`/login`, `/register`, `/dashboard`, `/library`, `/my-files`, `/send`, `/inbox`, `/history`, `/performance`, `/settings`, `/admin`.

## IMPORTANT: Frontend only

- All demo data is stored in the browser's `localStorage`. It is NOT shared between devices.
- File upload reads files as data URLs for demo persistence; browser storage quotas apply. Keep files small. This is not production storage.
- Demo seed materials have metadata only, no actual file bytes. Upload a real file to download it later in the same browser.
- Private sharing only simulates an inbox among users inside one browser's stored dataset.
- Browser file-read timings are NOT network transfer measurements. CPU/RAM/network statistics require a server.
- Authentication is demo-only with plaintext credentials in localStorage and is NOT secure.
- The intended Flask backend will implement secure authentication, LAN-accessible file storage, recipient authorization, actual upload/download streams, SHA-256 integrity checks, and psutil performance measurements.

## Recommended backend API contract

- `POST /api/auth/login`, `POST /api/auth/register`, `GET /api/auth/me`
- `GET /api/files`, `POST /api/files`, `PATCH /api/files/:id`, `DELETE /api/files/:id`
- `GET /api/files/:id/download`
- `POST /api/transfers`, `GET /api/transfers`
- `GET /api/metrics`, `GET /api/history`
- `GET /api/users`

## Build

Run `npm run build` to produce the static site in `dist/`.
