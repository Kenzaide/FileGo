# Deploy FileGo to Render — free temporary test

This Blueprint deploys the built React frontend and the Flask API together as one Render web service. It is intended **only for temporary testing with fake accounts and dummy files**.

## Important limitations

- The Blueprint selects Render's **free** instance and **does not attach a persistent disk**.
- SQLite is stored at `/tmp/filego.db` and uploads at `/tmp/filego-storage`. These are **ephemeral**. Accounts, files, and transfer history can disappear after a restart, spin-down, or redeployment. Do not rely on them for real coursework.
- Free services may sleep when idle and take time to wake. Free-plan limits and availability are determined by Render.
- Do **not** use the known demo credentials or upload real student information. The database starts empty; create a new disposable account.
- Public cloud testing does not measure LAN throughput. Keep `start-demo.bat` for offline LAN experiments.

## Deployment

1. Merge this pull request to `main`.
2. Visit [Render Dashboard](https://dashboard.render.com/), choose **New > Blueprint**, and connect `Kenzaide/FileGo`.
3. Choose the `main` branch, with the Blueprint path `render.yaml`. Review the displayed services: the web service should be **Free**, with **no disk**. If asked for a card or shown a paid plan, **cancel** and review the configuration before proceeding.
4. Deploy and watch build logs. The build installs Node packages, builds React, and installs Flask dependencies.
5. When the service is live, open `https://<service-name>.onrender.com/api/ping` and then the root URL.
6. Register a **temporary test account**, upload a dummy file, and test download on desktop and phone.

The server reads Render's `PORT` environment variable and uses a generated production `SECRET_KEY`. Never commit secrets. The free service is **not** a production-grade storage solution.

If Render's Python runtime cannot find `npm` during the build, stop and report the build log; the build environment will need adjustment.

## Going live later

For real users, first provision durable database and file storage, backups, and security review. Do not merely change the instance plan while keeping the temporary `/tmp` paths.
