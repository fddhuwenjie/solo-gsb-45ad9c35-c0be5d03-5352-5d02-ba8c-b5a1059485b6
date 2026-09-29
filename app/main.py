"""FastAPI application exposing the round-robin standings endpoint."""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .scheduling import ScheduleValidationError, generate_schedule
from .scenarios import compute_scenarios
from .schemas import (
    MatchIn,
    QualificationRequest,
    QualificationResponse,
    RoundRobinScheduleRequest,
    RoundRobinScheduleResponse,
    ScenarioEntry,
    ScheduledMatch,
    ScheduleRound,
    StandingEntry,
    StandingsRequest,
    StandingsResponse,
)
from .standings import StandingsValidationError, compute_standings

app = FastAPI(
    title="Round-Robin Standings API",
    version="1.2.0",
    description=(
        "Compute a round-robin league table from completed matches. "
        "Win = 3 points, draw = 1. Ties are broken by head-to-head "
        "mini-league (points, goal difference, goals scored, rebuilt "
        "recursively for still-tied subgroups), then overall goal "
        "difference, overall goals scored and team id. "
        "POST /qualification-scenarios enumerates the candidate scores "
        "of the remaining fixtures and reports each team's best and "
        "worst reachable rank (guaranteed / possible / eliminated "
        "against top_k), backed by witnessing result sets. "
        "POST /round-robin-schedules generates a complete single "
        "round-robin schedule with per-team unavailable rounds, fixed "
        "matches and home/away balancing; the lexicographically "
        "smallest feasible schedule is returned."
    ),
)


@app.exception_handler(StandingsValidationError)
async def standings_validation_handler(
    request: Request, exc: StandingsValidationError
) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(ScheduleValidationError)
async def schedule_validation_handler(
    request: Request, exc: ScheduleValidationError
) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.post(
    "/standings",
    response_model=StandingsResponse,
    responses={422: {"description": "Invalid teams or matches"}},
)
def post_standings(payload: StandingsRequest) -> StandingsResponse:
    """Compute the league table for the given teams and completed matches."""
    ordered, stats = compute_standings(payload.teams, payload.matches)
    entries = []
    for index, team in enumerate(ordered):
        row = stats[team]
        entries.append(
            StandingEntry(
                rank=index + 1,
                team=team,
                played=row.played,
                wins=row.wins,
                draws=row.draws,
                losses=row.losses,
                goals_for=row.goals_for,
                goals_against=row.goals_against,
                goal_difference=row.goal_difference,
                points=row.points,
            )
        )
    return StandingsResponse(standings=entries)


@app.post(
    "/qualification-scenarios",
    response_model=QualificationResponse,
    responses={422: {"description": "Invalid teams, matches or remaining fixtures"}},
)
def post_qualification_scenarios(
    payload: QualificationRequest,
) -> QualificationResponse:
    """Enumerate candidate results of the remaining fixtures.

    Every combination of candidate scores is evaluated with the same
    ranking rules as /standings. For each team the best and worst
    reachable rank is reported, together with a witnessing set of
    unplayed results for each extreme, and the team is classified as
    guaranteed / possible / eliminated against top_k.
    """
    scenarios, combinations = compute_scenarios(
        payload.teams, payload.matches, payload.top_k, payload.remaining
    )
    entries = []
    for scenario in scenarios:
        entries.append(
            ScenarioEntry(
                team=scenario.team,
                status=scenario.status,
                best_rank=scenario.best_rank,
                worst_rank=scenario.worst_rank,
                best_witness=[
                    MatchIn(
                        home=result.home,
                        away=result.away,
                        home_score=result.home_score,
                        away_score=result.away_score,
                    )
                    for result in scenario.best_witness
                ],
                worst_witness=[
                    MatchIn(
                        home=result.home,
                        away=result.away,
                        home_score=result.home_score,
                        away_score=result.away_score,
                    )
                    for result in scenario.worst_witness
                ],
            )
        )
    return QualificationResponse(
        top_k=payload.top_k, combinations=combinations, scenarios=entries
    )


@app.post(
    "/round-robin-schedules",
    response_model=RoundRobinScheduleResponse,
    responses={
        422: {
            "description": (
                "Invalid request, fixed-match conflict or no feasible schedule"
            )
        }
    },
)
def post_round_robin_schedule(
    payload: RoundRobinScheduleRequest,
) -> RoundRobinScheduleResponse:
    """Generate the lexicographically smallest feasible round-robin schedule.

    Every pair of teams meets exactly once and no team plays more than
    once per round. Fixed matches keep their round and home/away order;
    all other matches avoid the unavailable rounds. Each team's home
    and away counts differ by at most one and no team plays three
    consecutive games all home or all away. Rounds are sorted lists of
    ``(home, away)`` pairs and the schedule with the lexicographically
    smallest round-by-round sequence is returned.
    """
    rounds = generate_schedule(
        payload.teams,
        payload.rounds,
        {team: list(values) for team, values in payload.unavailable_rounds.items()},
        payload.fixed_matches,
    )
    schedule = [
        ScheduleRound(
            round=index + 1,
            matches=[ScheduledMatch(home=home, away=away) for home, away in matches],
        )
        for index, matches in enumerate(rounds)
    ]
    return RoundRobinScheduleResponse(
        teams=payload.teams, rounds=payload.rounds, schedule=schedule
    )
