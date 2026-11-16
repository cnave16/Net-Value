"""Check Chase's optional budget filter and selected-season data adapter."""

from unittest.mock import MagicMock

import pytest

from backend.services import recommendations
from data_model.roster_optimizer import _rank_single_players_from_data
from data_model.salary_value import _PlayerSeason


def test_unbudgeted_ranking_preserves_scores_without_claiming_affordability():
    players = [_PlayerSeason('100', 'Roster', 1, 2000), _PlayerSeason('200', 'Target', 3, 2000)]
    args = (players, {'100': 10_000_000, '200': 30_000_000}, ['100'])
    prices = {'200': 20_000_000}
    unbudgeted = _rank_single_players_from_data(*args, None, prices)
    affordable = _rank_single_players_from_data(*args, 25_000_000, prices)
    excluded = _rank_single_players_from_data(*args, 0, prices)
    target = unbudgeted['recommendations'][0]
    assert target['score'] == affordable['recommendations'][0]['score']
    assert target['fits_budget'] is None
    assert target['remaining_salary_if_selected'] is None
    assert unbudgeted['affordable_candidate_count'] is None
    assert unbudgeted['eligible_candidate_count'] == 1
    assert affordable['recommendations'][0]['remaining_salary_if_selected'] == 5_000_000
    assert excluded['recommendations'] == []
    assert excluded['over_budget_candidate_count'] == 1


@pytest.mark.parametrize('budget', [-1, float('nan'), float('inf')])
def test_invalid_budget_still_rejected(budget):
    with pytest.raises(ValueError, match='available_salary'):
        _rank_single_players_from_data([], {}, [], budget, {})


def test_league_values_use_exact_requested_season_and_all_players(monkeypatch):
    rows = [{'external_id': str(i), 'name': str(i), 'lebron': 1, 'minutes': 2000}
            for i in range(300)]
    query = MagicMock(return_value=rows)
    monkeypatch.setattr(recommendations, 'query', query)
    result = recommendations.load_recommendation_values(42)
    assert result['reason'] is None
    assert len(result['fair']) == 300
    sql, params = query.call_args.args
    assert params == (42,)
    assert 'ps.season_id = %s' in sql
    assert 'player_contracts' not in sql


def test_incomplete_league_does_not_invent_values(monkeypatch):
    query = MagicMock(return_value=[{'external_id': '1', 'name': 'Only', 'lebron': 3, 'minutes': 2000}])
    monkeypatch.setattr(recommendations, 'query', query)
    assert recommendations.load_recommendation_values(7) == {
        'fair': {}, 'reason': 'insufficient_season_coverage',
    }
