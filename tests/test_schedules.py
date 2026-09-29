"""End-to-end tests for the round-robin-schedules API."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.scheduling import minimum_rounds

client = TestClient(app)


def post_schedule(
    teams,
    rounds,
    unavailable_rounds=None,
    fixed_matches=None,
):
    body: dict = {"teams": teams, "rounds": rounds}
    if unavailable_rounds is not None:
        body["unavailable_rounds"] = unavailable_rounds
    if fixed_matches is not None:
        body["fixed_matches"] = fixed_matches
    return client.post("/round-robin-schedules", json=body)


def pairs_in(body):
    pairs = []
    for entry in body["schedule"]:
        for match in entry["matches"]:
            pairs.append((entry["round"], match["home"], match["away"]))
    return pairs


def assert_valid_schedule(body, teams, rounds, unavailable=None, fixed=None):
    """Check every hard constraint of a generated schedule."""
    n = len(teams)
    assert body["rounds"] == rounds
    assert [entry["round"] for entry in body["schedule"]] == list(
        range(1, rounds + 1)
    )

    seen_pairs: set[frozenset[str]] = set()
    homes = {team: 0 for team in teams}
    aways = {team: 0 for team in teams}
    # Venue sequence in the order each team actually plays.
    venues = {team: [] for team in teams}

    for entry in body["schedule"]:
        round_ = entry["round"]
        matches = [(m["home"], m["away"]) for m in entry["matches"]]
        # Rounds are sorted by home id then away id.
        assert matches == sorted(matches)
        busy: set[str] = set()
        for home, away in matches:
            assert home != away
            assert home in teams and away in teams
            # At most one match per team per round.
            assert home not in busy and away not in busy
            busy.update((home, away))
            # Unavailable rounds are respected.
            assert round_ not in (unavailable or {}).get(home, [])
            assert round_ not in (unavailable or {}).get(away, [])
            # Every pair meets exactly once.
            pair = frozenset((home, away))
            assert pair not in seen_pairs
            seen_pairs.add(pair)
            homes[home] += 1
            aways[away] += 1
            venues[home].append("H")
            venues[away].append("A")

    assert len(seen_pairs) == n * (n - 1) // 2
    for team in teams:
        assert abs(homes[team] - aways[team]) <= 1
        sequence = "".join(venues[team])
        assert "HHH" not in sequence
        assert "AAA" not in sequence

    for fixed in fixed or []:
        assert (fixed["round"], fixed["home"], fixed["away"]) in pairs_in(body)


def test_three_team_golden_schedule():
    response = post_schedule(["alpha", "bravo", "charlie"], 3)
    assert response.status_code == 200
    body = response.json()
    assert_valid_schedule(body, ["alpha", "bravo", "charlie"], 3)
    rounds = {
        entry["round"]: [(m["home"], m["away"]) for m in entry["matches"]]
        for entry in body["schedule"]
    }
    assert rounds == {
        1: [("alpha", "bravo")],
        2: [("bravo", "charlie")],
        3: [("charlie", "alpha")],
    }


def test_four_team_golden_schedule():
    response = post_schedule(["alpha", "bravo", "charlie", "delta"], 3)
    assert response.status_code == 200
    body = response.json()
    assert_valid_schedule(body, ["alpha", "bravo", "charlie", "delta"], 3)
    rounds = {
        entry["round"]: [(m["home"], m["away"]) for m in entry["matches"]]
        for entry in body["schedule"]
    }
    assert rounds == {
        1: [("alpha", "bravo"), ("charlie", "delta")],
        2: [("alpha", "charlie"), ("bravo", "delta")],
        3: [("bravo", "charlie"), ("delta", "alpha")],
    }


def test_schedule_is_valid_for_every_team_count_at_minimum_rounds():
    for n in range(2, 9):
        teams = [f"t{i}" for i in range(n)]
        response = post_schedule(teams, minimum_rounds(n))
        assert response.status_code == 200
        assert_valid_schedule(response.json(), teams, minimum_rounds(n))


def test_extra_rounds_contain_empty_round_entries():
    response = post_schedule(["alpha", "bravo"], 3)
    assert response.status_code == 200
    schedule = response.json()["schedule"]
    # The single match is pushed as late as possible: the empty round is
    # lexicographically smaller than any round containing a match.
    assert schedule[0]["matches"] == []
    assert schedule[1]["matches"] == []
    assert [(m["home"], m["away"]) for m in schedule[2]["matches"]] == [
        ("alpha", "bravo")
    ]


def test_schedule_is_independent_of_team_order_in_request():
    first = post_schedule(
        ["alpha", "bravo", "charlie", "delta"], 4
    ).json()["schedule"]
    second = post_schedule(
        ["delta", "charlie", "bravo", "alpha"], 4
    ).json()["schedule"]
    assert first == second


def test_repeated_requests_return_a_stable_result():
    payload = {"teams": ["a", "b", "c", "d", "e"], "rounds": 6}
    responses = [client.post("/round-robin-schedules", json=payload).json() for _ in range(3)]
    assert all(r == responses[0] for r in responses)


def test_unavailable_rounds_are_respected():
    # alpha cannot play in round 1; its three games must land in rounds 2-4.
    response = post_schedule(
        ["alpha", "bravo", "charlie", "delta"],
        4,
        unavailable_rounds={"alpha": [1]},
    )
    assert response.status_code == 200
    body = response.json()
    assert_valid_schedule(
        body,
        ["alpha", "bravo", "charlie", "delta"],
        4,
        unavailable={"alpha": [1]},
    )
    round_one = body["schedule"][0]["matches"]
    assert all(m["home"] != "alpha" and m["away"] != "alpha" for m in round_one)


def test_fixed_match_keeps_round_and_orientation():
    fixed = [{"round": 2, "home": "charlie", "away": "alpha"}]
    response = post_schedule(
        ["alpha", "bravo", "charlie", "delta"], 3, fixed_matches=fixed
    )
    assert response.status_code == 200
    body = response.json()
    assert_valid_schedule(
        body, ["alpha", "bravo", "charlie", "delta"], 3, fixed=fixed
    )
    round_two = body["schedule"][1]["matches"]
    assert {"home": "charlie", "away": "alpha"} in round_two
    # The reverse orientation must not appear.
    assert {"home": "alpha", "away": "charlie"} not in round_two


def test_no_feasible_schedule_is_422():
    # alpha would have to play two games in the only two rounds left.
    response = post_schedule(
        ["alpha", "bravo", "charlie"],
        3,
        unavailable_rounds={"alpha": [1, 2]},
    )
    assert response.status_code == 422
    assert "no feasible schedule" in response.json()["detail"]


def test_fixed_match_conflicting_with_unavailable_round_is_422():
    response = post_schedule(
        ["alpha", "bravo", "charlie"],
        3,
        unavailable_rounds={"alpha": [2]},
        fixed_matches=[{"round": 2, "home": "alpha", "away": "bravo"}],
    )
    assert response.status_code == 422
    assert "unavailable" in response.json()["detail"]


def test_two_fixed_matches_for_one_team_in_one_round_are_422():
    response = post_schedule(
        ["alpha", "bravo", "charlie", "delta"],
        3,
        fixed_matches=[
            {"round": 1, "home": "alpha", "away": "bravo"},
            {"round": 1, "home": "alpha", "away": "charlie"},
        ],
    )
    assert response.status_code == 422
    assert "two fixed matches" in response.json()["detail"]


def test_duplicate_fixed_matchup_is_422():
    response = post_schedule(
        ["alpha", "bravo", "charlie", "delta"],
        3,
        fixed_matches=[
            {"round": 1, "home": "alpha", "away": "bravo"},
            {"round": 2, "home": "bravo", "away": "alpha"},
        ],
    )
    assert response.status_code == 422
    assert "duplicate fixed matchup" in response.json()["detail"]


def test_fixed_match_with_unknown_team_is_422():
    response = post_schedule(
        ["alpha", "bravo", "charlie"],
        3,
        fixed_matches=[{"round": 1, "home": "alpha", "away": "echo"}],
    )
    assert response.status_code == 422
    assert "unknown team" in response.json()["detail"]


def test_fixed_self_match_is_422():
    response = post_schedule(
        ["alpha", "bravo"],
        1,
        fixed_matches=[{"round": 1, "home": "alpha", "away": "alpha"}],
    )
    assert response.status_code == 422


def test_fixed_match_outside_round_range_is_422():
    response = post_schedule(
        ["alpha", "bravo", "charlie"],
        3,
        fixed_matches=[{"round": 4, "home": "alpha", "away": "bravo"}],
    )
    assert response.status_code == 422
    assert "outside" in response.json()["detail"]


def test_rounds_below_round_robin_minimum_are_422():
    response = post_schedule(["alpha", "bravo", "charlie"], 2)
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "3" in detail and "minimum" in detail


def test_rounds_above_twelve_are_422():
    response = client.post(
        "/round-robin-schedules",
        json={"teams": ["alpha", "bravo"], "rounds": 13},
    )
    assert response.status_code == 422


def test_team_count_outside_two_to_eight_is_422():
    too_few = client.post(
        "/round-robin-schedules", json={"teams": ["alpha"], "rounds": 1}
    )
    assert too_few.status_code == 422
    too_many = client.post(
        "/round-robin-schedules",
        json={"teams": [f"t{i}" for i in range(9)], "rounds": 12},
    )
    assert too_many.status_code == 422


def test_duplicate_team_ids_are_422():
    response = post_schedule(["alpha", "alpha", "bravo"], 3)
    assert response.status_code == 422
    assert "duplicate team" in response.json()["detail"]


def test_unknown_team_in_unavailable_rounds_is_422():
    response = post_schedule(
        ["alpha", "bravo"], 1, unavailable_rounds={"echo": [1]}
    )
    assert response.status_code == 422
    assert "unknown team" in response.json()["detail"]


def test_unavailable_round_outside_range_is_422():
    response = post_schedule(
        ["alpha", "bravo"], 1, unavailable_rounds={"alpha": [0]}
    )
    assert response.status_code == 422
    assert "outside" in response.json()["detail"]


def test_fixed_home_overflow_makes_schedule_infeasible():
    # n=3 requires exactly one home per team; fixing alpha as home in
    # both of its games forces two homes.
    response = post_schedule(
        ["alpha", "bravo", "charlie"],
        3,
        fixed_matches=[
            {"round": 1, "home": "alpha", "away": "bravo"},
            {"round": 2, "home": "alpha", "away": "charlie"},
        ],
    )
    assert response.status_code == 422
    assert "no feasible schedule" in response.json()["detail"]


def test_three_consecutive_home_games_are_avoided_around_fixed_matches():
    # alpha starts HH at home; its remaining two games must both be away,
    # and the solver must find such a completion.
    fixed = [
        {"round": 1, "home": "alpha", "away": "bravo"},
        {"round": 2, "home": "alpha", "away": "charlie"},
    ]
    response = post_schedule(
        ["alpha", "bravo", "charlie", "delta", "echo"],
        5,
        fixed_matches=fixed,
    )
    assert response.status_code == 200
    body = response.json()
    assert_valid_schedule(
        body,
        ["alpha", "bravo", "charlie", "delta", "echo"],
        5,
        fixed=fixed,
    )
    alpha_venues = []
    for entry in body["schedule"]:
        for match in entry["matches"]:
            if match["home"] == "alpha":
                alpha_venues.append("H")
            elif match["away"] == "alpha":
                alpha_venues.append("A")
    assert "".join(alpha_venues) == "HHAA"


def test_openapi_documents_the_new_endpoint():
    spec = client.get("/openapi.json")
    assert spec.status_code == 200
    paths = spec.json()["paths"]
    assert "/round-robin-schedules" in paths
    # The existing endpoints remain documented.
    assert "/standings" in paths
    assert "/qualification-scenarios" in paths
    operation = paths["/round-robin-schedules"]["post"]
    assert "RoundRobinScheduleRequest" in str(operation["requestBody"])
    assert "RoundRobinScheduleResponse" in str(operation["responses"]["200"])
    assert "422" in operation["responses"]
