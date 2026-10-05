# Net Value frontend

React (Vite) + Axios. All backend calls go through `src/services/api.js`.

```sh
cd frontend
npm install
cp .env.example .env.local   # optional; defaults to sample data
npm run dev                  # http://localhost:5173
```

`VITE_USE_MOCK=true` (default) uses sample data from `src/services/mockData.js`.
Set it to `false` to call the Flask API. The dev server proxies `/api` to Flask
on port 5001, so run Flask there (see `docs/frontend-setup.md`).

Routes: `/players` (search + selected-player value panel), `/draft`, `/trade`.
