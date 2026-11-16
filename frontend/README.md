# Net Value frontend

React (Vite) + Axios. All backend calls go through `src/services/api.js`.

```sh
cd frontend
npm install
cp .env.example .env.local   # optional; defaults to the live API
npm run dev                  # http://localhost:5173
```

By default the app calls the Flask API: the dev server proxies `/api` to Flask
on port 5001, so run Flask there (see `docs/frontend-setup.md`). Set
`VITE_USE_MOCK=true` to use sample data from `src/services/mockData.js` instead.

Routes: `/players` (search + selected-player value panel), `/draft`, `/trade`.
