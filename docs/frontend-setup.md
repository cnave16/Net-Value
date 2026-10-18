# Frontend setup

Elias can build team and season selection, player search, and roster win
projections against the current API. Two-team trade analysis is now available
in the backend; player valuation and draft picks still return 501. See
[the API contract](api.md) for the exact fields.

## Start the backend

Follow the [README setup](../README.md#backend-development) in a terminal at the
repository root. Obtain the development database URL privately from the team;
do not commit it. You do not need production credentials or to run the importer.

```sh
python -m flask --app backend run --port 5001
```

Keep this terminal running and start React in a second terminal. Open these
addresses to confirm the backend is available:

- `http://localhost:5001/api/health`: Flask can respond.
- `http://localhost:5001/api/health/db`: the configured database accepts a query.
- `http://localhost:5001/api/seasons`: the database has the expected season table.

A successful health check does not guarantee that player data has been loaded.
An empty list is valid; coordinate data loading with the team if necessary.

## Start React

The React app is in `frontend/`. Use Node.js 22.12 or newer and install the
locked dependencies from that directory:

```sh
cd frontend
npm ci
npm run dev
```

The app defaults to sample data. For live backend requests, create or update
`frontend/.env.local` with:

```dotenv
VITE_USE_MOCK=false
```

Restart Vite after changing environment settings. Open the address printed by
Vite (normally `http://localhost:5173`). Keep Flask running on port 5001.
The default API base URL is `/api`; Vite forwards those requests to
`http://127.0.0.1:5001`. No direct backend URL is needed for local development.

The shared client in `frontend/src/services/api.js` already unwraps the backend
response into `{ data, meta }` and converts errors to `ApiError`. Use its helpers
instead of creating another Axios client. It handles the valuation endpoint's
501 response by showing unavailable values.

`VITE_API_BASE_URL` is only needed to call another backend directly. That backend
must allow the frontend origin through CORS. Vite variables are visible in the
browser: never put database credentials in them. The development proxy is not
part of a production build; hosting will need an API proxy or an explicit API URL.

## Check the combined app

1. Open `/players` with `VITE_USE_MOCK=false` and confirm real names load.
2. Search for a player, select the result, and confirm the detail panel loads.
3. Salary and value should show unavailable, with the valuation-model message.
4. Open `/draft` and `/trade`; these are still placeholder screens.

The current player screen shows the first page of results and has no pagination
controls yet. Search still queries the full database. Season stats in the sample
UI are optional; the current player API does not return a `seasons` field, so
those stats are absent in live mode. Team selection and win-projection screens
remain frontend work, even though API helpers are available for them.

## Integrate win projections next

The existing client exposes `getSeasons`, `getTeams`, and `projectWins`:

```javascript
import { projectWins } from './services/api.js';

const { data } = await projectWins(selectedPlayerIds, selectedSeasonId);
const projectedWins = data.projected_wins;
```

Select a season ID from `/seasons` and 12–15 distinct internal player IDs from
`/players`. These must be actual database IDs, not external NBA IDs. A 422 means
some players are missing or lack usable season data; display the explanation
instead of an estimate. `getTeams`, `getSeasons`, and `projectWins` always call
the backend, even when the player screens use sample data.

## Display incomplete features clearly

The trade screen remains a placeholder. When wiring it up, update the existing
`validateTrade` helper to send team IDs and the selected season as described in
[the trade contract](trades.md). Show results only when `analysis_available`
is true, and label legality as incomplete rather than showing a legal-trade badge.

| API behavior | Frontend behavior |
| --- | --- |
| Empty player list | Show “No players found” |
| `null` salary, team, or value | Show “Unavailable,” not zero |
| 400, 413, 415, or 422 | Explain the input or data issue |
| 503 | Show that the database is unavailable and allow a retry |
| 501 on valuation or picks | Show that the feature is not available yet |
| Trade `analysis_available: false` | Show the failed roster checks, not predictions |

Player team filters describe historical season membership. The win projection
uses historical minutes and does not confirm that a proposed roster is legal,
belongs to one current team, or has a realistic new rotation. Display it as an
estimate. Mock trade results can support UI development but should be labeled
as examples and kept separate from live API results.
