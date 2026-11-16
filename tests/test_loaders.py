"""Parse Basketball-Reference contract and draft pages without network access."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "database_config"))

from load_contracts import name_key, parse_contracts_page  # noqa: E402
from load_draft import parse_draft_page  # noqa: E402

CONTRACTS = """<table id="contracts"><tbody>
<tr ><th scope="row" class="left " data-stat="player" csk="mitchdo01" ><a href='/players/m/mitchdo01.html'>Donovan Mitchell</a></th><td class="right " data-stat="y1" csk="50105628" >$50,105,628</td><td class="right " data-stat="y2" csk="60911900" >$60,911,900</td><td class="right salary-pl" data-stat="y3" csk="65784852" ><em>$65,784,852</em></td><td class="right iz" data-stat="y4" ></td></tr>
<tr ><th scope="row" class="left " data-stat="player" csk="portemi01" ><a href='/players/p/portemi01.html'>Michael Porter Jr.</a></th><td class="right " data-stat="y1" csk="40806150" ><em>$40,806,150</em></td></tr>
<tr ><th scope="row" class="left " data-stat="player" csk="omierno01" ><a href='/players/o/omierno01.html'>Norchad Omier</a></th><td class="right iz" data-stat="y1" ></td></tr>
<tr ><th scope="row" class="left " data-stat="player" csk="vukcetr01" ><a href='/players/v/vukcetr01.html'>Tristan Vukcevic</a></th><td class="right iz" data-stat="y1" ></td></tr>
<tr ><th scope="row" class="left " data-stat="player" >Team Totals</th><td class="right " data-stat="y1" >$95,000,000</td></tr>
</tbody></table>
<table id="payroll-notes"><tr ><th data-stat="player" ><a href='/players/o/omierno01.html'>Norchad Omier</a></th><td>Signed two-way contract November 5, 2026.</td></tr>
<tr ><th data-stat="player" ><a href='/players/v/vukcetr01.html'>Tristan Vukcevic</a></th><td>Signed 3-yr/$9M contract.</td></tr></table>"""

DRAFT = """<tr ><th data-stat="ranker" >1</th><td class="right " data-stat="pick_overall" csk="1" >1</td><td class="left " data-stat="team_id" csk="DAL.001" >DAL</td><td class="left " data-stat="player" csk="Flagg" ><a href='/players/f/flaggco01.html'>Cooper Flagg</a></td></tr>
<tr ><th data-stat="ranker" >31</th><td class="right " data-stat="pick_overall" csk="31" >31</td><td class="left " data-stat="team_id" csk="CHO.031" >CHO</td><td class="left " data-stat="player" csk="X" ><a href='/players/x/xx01.html'>Second Rounder</a></td></tr>"""


def test_contracts_salary_types():
    players, total = parse_contracts_page(CONTRACTS)
    by_name = {p["name"]: p for p in players}
    assert total == 95_000_000
    assert by_name["Donovan Mitchell"]["salary"] == 50_105_628
    assert by_name["Donovan Mitchell"]["later_salaries"] == [60_911_900, 65_784_852, None]
    assert by_name["Norchad Omier"]["later_salaries"] == []
    # Italic (non-guaranteed) salaries are still salaries, not two-way contracts.
    assert by_name["Michael Porter Jr."]["salary"] == 40_806_150
    assert by_name["Norchad Omier"] == {**by_name["Norchad Omier"], "salary": 0, "contract_type": "two_way"}
    # A blank salary without a two-way note is unknown, not zero.
    assert by_name["Tristan Vukcevic"]["salary"] is None
    assert by_name["Tristan Vukcevic"]["contract_type"] == "standard"


def test_draft_rounds_and_team_codes():
    first, second = parse_draft_page(DRAFT)
    assert (first["pick"], first["round"], first["team"], first["source_id"]) == (1, 1, "DAL", "flaggco01")
    assert (second["round"], second["team"]) == (2, "CHA")


def test_name_key_ignores_case_accents_and_suffixes():
    assert name_key("Ronald Holland II") == name_key("Ronald Holland Ii")
    assert name_key("Nikola Jokić") == name_key("Nikola Jokic")
    assert name_key("CJ McCollum") == name_key("Cj Mccollum")


def test_name_aliases_cover_nicknames():
    assert name_key("Ron Holland") == name_key("Ronald Holland II")


def test_nba_id_choice_safeguards():
    from load_nba_ids import choose_ids
    ids = {
        name_key("New Rookie"): {"1643407"},
        name_key("Old Namesake"): {"76001"},          # a retired player's ID
        name_key("Two Players"): {"1630001", "1630002"},
        name_key("Duplicate Row"): {"1641842"},
    }
    missing = [(1, "New Rookie", 2026), (2, "Old Namesake", 2025), (3, "Two Players", None),
               (4, "Duplicate Row", 2024), (5, "Nobody", None)]
    chosen, skipped = choose_ids(missing, ids, {"1641842": "Existing Player"})
    assert chosen == {1: "1643407"}
    reasons = dict(skipped)
    assert reasons["Old Namesake"] == "no match"   # too old for a recent draftee
    assert reasons["Two Players"] == "ambiguous"
    assert "duplicate of existing player 'Existing Player'" in reasons["Duplicate Row"]
    assert reasons["Nobody"] == "no match"
