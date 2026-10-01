# Frontend setup

Elias can build team and season selection, player search, and roster win
projections against the current API. Trade validation, player values, and draft
picks still return 501. See [the API contract](api.md) for the exact fields.

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

## Connect React

Use `http://localhost:5001/api` as the API base URL in the frontend's existing
configuration. This repository does not contain a React app yet. If the frontend
uses Vite, a local setting can be:

```dotenv
VITE_API_BASE_URL=http://localhost:5001/api
```

Vite exposes these settings to the browser, so never put database credentials
in a `VITE_` variable. With Axios, an example service is:

```javascript
import axios from "axios";

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL,
});

export async function getPlayers(seasonId, page = 1) {
  const response = await api.get("/players", {
    params: { season_id: seasonId, page, limit: 20 },
  });
  // Axios's data is the response body; our data field holds the player list.
  return response.data;
}
```

The returned body has `data`, `meta`, and `error`. Use `body.data` for players and
`body.meta.total_pages` for pagination. Axios sends non-2xx responses to its
error handler; read `error.response?.data?.error?.message` for the API message,
and provide a fallback for network failures with no response.

The backend allows frontend origins `http://localhost:5173` and
`http://localhost:3000` by default. For another address, update `CORS_ORIGINS`
in the backend `.env` and restart Flask. Use exact origins without a trailing
slash; add a `127.0.0.1` origin separately if that is how you open the frontend.

## Try the first complete flow

1. Request `GET /seasons` and let the user choose a returned season ID.
2. Request `GET /teams` for team options.
3. Request `GET /players?season_id=<id>&page=1&limit=20`. Add a team abbreviation
   or search text when needed. Keep the season when filtering by team.
4. Let the user select 12–15 distinct players and collect their integer `id`
   values, not the external NBA IDs.
5. Submit those IDs with the selected season:

```javascript
const response = await api.post("/projections/wins", {
  player_ids: selectedPlayerIds,
  season_id: selectedSeasonId,
});
const projectedWins = response.data.data.projected_wins;
```

The example uses IDs selected from real responses, rather than assuming IDs
are identical in every database. A 422 means some players are missing or lack
usable data for that season; display the explanation instead of an estimate.

## Display incomplete features clearly

| API behavior | Frontend behavior |
| --- | --- |
| Empty player list | Show “No players found” |
| `null` salary, team, or value | Show “Unavailable,” not zero |
| 400, 413, 415, or 422 | Explain the input or data issue |
| 503 | Show that the database is unavailable and allow a retry |
| 501 on trade, valuation, or picks | Show that the feature is not available yet |

Player team filters describe historical season membership. The win projection
uses historical minutes and does not confirm that a proposed roster is legal,
belongs to one current team, or has a realistic new rotation. Display it as an
estimate. Mock trade results can support UI development but should be labeled
as examples and kept separate from live API results.
