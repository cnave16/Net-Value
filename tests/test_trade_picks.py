"""Check future ownership, Stepien uncertainty, and mixed trade API behavior."""

from copy import deepcopy
from unittest.mock import MagicMock

import pytest

from backend import create_app
from backend.routes import trades
from backend.services.trade_picks import check_pick_transfers, selectable_picks, load_pick_ownership
from backend.services import trade_picks
from database_config.copy_pick_ownership import remap_snapshot


def pick(year=2027, rnd=1, original=1, owner=None, resolved=True):
    return dict(draft_year=year, round=rnd, original_team_id=original,
                owner_team_id=original if owner is None else owner, is_resolved=resolved,
                ownership_type='owned' if resolved else 'conditional',
                original_team_abbreviation=f'T{original}', notes='', pool_id=None,
                source_url='https://example.test', retrieved_at=None)


def move(year=2027, rnd=1, original=1, source=1, dest=2):
    return dict(draft_year=year, round=rnd, original_team_id=original,
                from_team_id=source, to_team_id=dest)


@pytest.fixture
def ownership():
    return [pick(year, rnd, team) for year in range(2027, 2034)
            for rnd in (1, 2) for team in range(1, 31)]


def checks(rows, moves):
    return check_pick_transfers(rows, moves, [1, 2, 3], set(range(1, 31)))[0]


def stepien(rows, moves, team=1):
    return next(c for c in checks(rows, moves) if c['code'] == 'STEPIEN_RULE' and c['team_id'] == team)


def test_consecutive_firsts_fail_and_one_first_passes(ownership):
    assert stepien(ownership, [move()])['passed'] is True
    result = stepien(ownership, [move(), move(2028)])
    assert result['passed'] is False
    assert result['failed_year_pairs'] == [[2027, 2028]]


def test_incoming_different_original_first_satisfies_stepien(ownership):
    moves = [move(), move(2028), move(2027, original=2, source=2, dest=1)]
    assert stepien(ownership, moves)['passed'] is True
    assert stepien(ownership, list(reversed(moves)))['passed'] is True


def test_preexisting_traded_first_counts_as_missing(ownership):
    ownership[0]['owner_team_id'] = 3
    assert stepien(ownership, [move(2028)])['passed'] is False


def test_second_round_picks_never_satisfy_stepien(ownership):
    assert stepien(ownership, [move(), move(2028), move(2027, rnd=2, original=2, source=2, dest=1)])['passed'] is False
    assert not any(c['code'] == 'STEPIEN_RULE' for c in checks(ownership, [move(rnd=2)]))


def test_unresolved_claimant_does_not_prove_pass_or_failure(ownership):
    # Team 1 could receive this pick even though the row names Team 3.
    for row in ownership:
        if row['draft_year'] == 2028 and row['round'] == 1 and row['original_team_id'] == 3:
            row.update(is_resolved=False, ownership_type='pooled')
    result = stepien(ownership, [move(), move(2028)])
    assert result['passed'] is None
    assert result['uncertain_year_pairs'] == [[2027, 2028]]
    assert stepien(ownership, [move()])['passed'] is True


def test_missing_coverage_is_unknown(ownership):
    rows = [p for p in ownership if not (p['draft_year'] == 2028 and p['round'] == 1 and p['original_team_id'] == 30)]
    assert stepien(rows, [move(), move(2028)])['passed'] is None


def test_seventh_year_checks_missing_adjacent_year(ownership):
    result = stepien(ownership, [move(2033)])
    assert result['passed'] is None
    assert result['uncertain_year_pairs'] == [[2033, 2034]]


def test_freeze_history_is_unknown_even_with_resolved_ownership(ownership):
    result = checks(ownership, [move()])
    assert next(c for c in result if c['code'] == 'FIRST_ROUND_PICK_RESTRICTIONS')['passed'] is None


@pytest.mark.parametrize('change', [dict(owner_team_id=2), dict(is_resolved=False)])
def test_wrong_or_unresolved_owner_blocks_simulation(ownership, change):
    ownership[0].update(change)
    result, valid = check_pick_transfers(ownership, [move()], [1, 2], set(range(1, 31)))
    assert valid is False
    assert result[0]['passed'] is False


@pytest.mark.parametrize('year', [2026, 2034])
def test_outside_seven_drafts_rejected(year, ownership):
    ownership.append(pick(year))
    result, valid = check_pick_transfers(ownership, [move(year)], [1, 2], set(range(1, 31)))
    assert valid is False
    assert result[1]['passed'] is False


def test_selector_excludes_unresolved_wrong_owner_and_outside_years(ownership):
    ownership[0]['is_resolved'] = False
    ownership.extend([pick(2026), pick(2034)])
    available = selectable_picks(ownership, 1)
    assert len(available) == 13
    assert all(p['owner_team_id'] == 1 and p['is_resolved'] and 2027 <= p['draft_year'] <= 2033 for p in available)
    assert all('value' not in p and 'salary' not in p for p in available)


@pytest.fixture
def client(monkeypatch, ownership):
    app = create_app({'TESTING': True, 'DATABASE_URL': None})
    teams = {i: {'id': i, 'abbreviation': f'T{i}', 'name': f'Team {i}', 'players': [
        {'player_id': i, 'name': f'Player {i}', 'minutes': 2000, 'lebron': 2,
         'actual_salary': 1000000, 'external_id': str(i)},
        {'player_id': i + 100, 'name': 'Retained player', 'minutes': 2000, 'lebron': 1,
         'actual_salary': 1000000, 'external_id': str(i + 100)}]} for i in (1, 2, 3)}
    monkeypatch.setattr(trades, 'load_trade_rosters', MagicMock(return_value=teams))
    monkeypatch.setattr(trades, 'load_pick_ownership', MagicMock(return_value=ownership))
    monkeypatch.setattr(trades, 'query', MagicMock(return_value=[{'team_id': i} for i in range(1, 31)]))
    return app.test_client()


def body(picks=None, players=None, team_ids=None):
    return dict(season_id=1, team_ids=team_ids or [1, 2], transfers=players or [],
                pick_transfers=[move(rnd=2)] if picks is None else picks)


@pytest.mark.parametrize('path', ['/api/trade/analyze', '/api/trade/validate'])
def test_pick_only_api_does_not_change_wins_payroll_or_database(client, ownership, path):
    original = deepcopy(ownership)
    response = client.post(path, json=body())
    assert response.status_code == 200
    data = response.json['data']
    assert data['analysis_available'] is True
    assert data['legality']['passes_supported_rules'] is True
    assert data['legality']['is_legal'] is None
    for team in data['teams']:
        assert team['roster_before'] == team['roster_after']
        assert team['projected_wins']['net_difference'] == 0
        assert team['payroll']['net_difference'] == '0.00'
    assert data['teams'][1]['incoming_picks'][0]['owner_team_id'] == 2
    assert ownership == original


def test_mixed_three_way_trade_and_pick_result(client):
    response = client.post('/api/trade/analyze', json=body(
        picks=[move(rnd=2, source=1, dest=2)],
        players=[dict(player_id=2, from_team_id=2, to_team_id=3)], team_ids=[1, 2, 3]))
    assert response.status_code == 200
    assert response.json['data']['teams'][1]['incoming_picks'][0]['original_team_id'] == 1
    assert response.json['data']['teams'][2]['incoming_player_ids'] == [2]


def test_unknown_pick_returns_failed_analysis(client):
    response = client.post('/api/trade/analyze', json=body([move(original=500)]))
    assert response.status_code == 200
    assert response.json['data']['analysis_available'] is False
    assert response.json['data']['legality']['status'] == 'failed'


def test_stepien_failure_still_shows_trade_effects(client):
    response = client.post('/api/trade/analyze', json=body([move(), move(2028)]))
    assert response.json['data']['analysis_available'] is True
    assert response.json['data']['legality']['passes_supported_rules'] is False


@pytest.mark.parametrize('picks', [None, {}, 'pick', [move(), move()], [move(rnd=3)],
    [move(source=2, dest=2)], [move(source=3)], [dict(move(), protection='top 5')],
    [dict(move(), draft_year=True)], [dict(move(), original_team_id='1')], [move()] * 101])
def test_bad_pick_payload_returns_400(client, picks):
    payload = body()
    payload['pick_transfers'] = picks
    assert client.post('/api/trade/analyze', json=payload).status_code == 400


def test_empty_trade_and_uninvolved_team_rejected(client):
    assert client.post('/api/trade/analyze', json=body([])).status_code == 400
    assert client.post('/api/trade/analyze', json=body(team_ids=[1, 2, 3])).status_code == 400


def test_player_only_requests_do_not_query_ownership(client, monkeypatch):
    loader = MagicMock(side_effect=AssertionError('not needed'))
    monkeypatch.setattr(trades, 'load_pick_ownership', loader)
    payload = body(players=[dict(player_id=1, from_team_id=1, to_team_id=2)])
    del payload['pick_transfers']
    assert client.post('/api/trade/analyze', json=payload).status_code == 200
    loader.assert_not_called()


def test_pick_listing_endpoint(client, ownership):
    ownership[0]['is_resolved'] = False
    response = client.get('/api/trade/teams/1/picks')
    assert response.status_code == 200
    assert len(response.json['data']) == 13
    assert response.json['meta']['estimated_values'] is False
    assert client.get('/api/trade/teams/1/picks?season_id=1').status_code == 400


def test_loader_uses_real_ownership_table(monkeypatch):
    query = MagicMock(return_value=[pick()])
    monkeypatch.setattr(trade_picks, 'query', query)
    assert load_pick_ownership()[0]['draft_year'] == 2027
    assert 'draft_pick_ownership' in query.call_args[0][0]


def test_copy_maps_team_ids_without_changing_asset_identity(ownership):
    source = [dict(team_id=i, abbreviation=f'T{i}') for i in range(1, 31)]
    target = [dict(team_id=i + 100, abbreviation=f'T{i}') for i in range(1, 31)]
    mapped = remap_snapshot(ownership, source, target, 2027, 2033)
    assert mapped[0]['original_team_id'] == mapped[0]['owner_team_id'] == 101
    assert ownership[0]['owner_team_id'] == 1
    with pytest.raises(ValueError):
        remap_snapshot(ownership[:-1], source, target, 2027, 2033)
    with pytest.raises(ValueError):
        remap_snapshot(ownership, source, target[:-1], 2027, 2033)


def test_picks_do_not_create_salary_matching_room(client, monkeypatch):
    # Team 2 is over the first apron and sends only a second-round pick.
    loaded = trades.load_trade_rosters.return_value
    for player in loaded[2]['players']:
        player['actual_salary'] = 110000000
    response = client.post('/api/trade/analyze', json=body(
        picks=[move(rnd=2, original=2, source=2, dest=1)],
        players=[dict(player_id=1, from_team_id=1, to_team_id=2)]))
    assert response.status_code == 200
    matching = next(c for c in response.json['data']['legality']['checks']
                    if c['code'] == 'SALARY_MATCHING' and c['team_id'] == 2)
    assert matching['outgoing_salary'] == '0.00'
    assert matching['incoming_salary'] == '1000000.00'
    assert matching['passed'] is False


def test_pick_only_preserves_unknown_payroll(client):
    trades.load_trade_rosters.return_value[1]['players'][0]['actual_salary'] = None
    response = client.post('/api/trade/analyze', json=body())
    team = response.json['data']['teams'][0]
    assert team['payroll']['before'] is None and team['payroll']['after'] is None
    assert team['projected_wins']['net_difference'] == 0
    assert team['outgoing_picks'][0]['ownership_type'] == 'traded'
    assert response.json['data']['legality']['passes_supported_rules'] is True


def test_missing_team_pick_inventory_returns_404(client, monkeypatch):
    monkeypatch.setattr(trades, 'query', MagicMock(return_value=[]))
    assert client.get('/api/trade/teams/999/picks').status_code == 404
