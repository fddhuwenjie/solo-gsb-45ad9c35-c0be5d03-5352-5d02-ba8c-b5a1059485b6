"""Pydantic schemas for the standings API."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class MatchIn(BaseModel):
    """A completed match between two teams."""

    home: str = Field(min_length=1, examples=["alpha"])
    away: str = Field(min_length=1, examples=["bravo"])
    home_score: int = Field(ge=0, examples=[2])
    away_score: int = Field(ge=0, examples=[1])


class StandingsRequest(BaseModel):
    """Teams participating in the round-robin and the completed matches."""

    teams: list[str] = Field(min_length=1, examples=[["alpha", "bravo", "charlie"]])
    matches: list[MatchIn] = Field(default_factory=list)


class StandingEntry(BaseModel):
    """One row of the final table."""

    rank: int
    team: str
    played: int
    wins: int
    draws: int
    losses: int
    goals_for: int
    goals_against: int
    goal_difference: int
    points: int


class StandingsResponse(BaseModel):
    standings: list[StandingEntry]


class ScoreCandidate(BaseModel):
    """One possible score for an unplayed fixture."""

    home_score: int = Field(ge=0, examples=[2])
    away_score: int = Field(ge=0, examples=[1])


class RemainingFixture(BaseModel):
    """An unplayed fixture together with its finite candidate scores."""

    home: str = Field(min_length=1, examples=["delta"])
    away: str = Field(min_length=1, examples=["alpha"])
    candidates: list[ScoreCandidate] = Field(min_length=1)


class QualificationRequest(BaseModel):
    """Completed matches plus candidate scores for every unplayed fixture."""

    teams: list[str] = Field(min_length=1, examples=[["alpha", "bravo", "charlie"]])
    matches: list[MatchIn] = Field(default_factory=list)
    top_k: int = Field(ge=1, examples=[2])
    remaining: list[RemainingFixture] = Field(default_factory=list)


class ScenarioEntry(BaseModel):
    """Best/worst reachable rank for one team, each with a witness.

    A witness is a complete set of results for the unplayed fixtures
    (one entry per fixture, in request order) under which the team
    finishes at the corresponding extreme rank.
    """

    team: str
    status: Literal["guaranteed", "possible", "eliminated"]
    best_rank: int
    worst_rank: int
    best_witness: list[MatchIn]
    worst_witness: list[MatchIn]


class QualificationResponse(BaseModel):
    top_k: int
    combinations: int
    scenarios: list[ScenarioEntry]


class FixedMatchIn(BaseModel):
    """A match pinned to a round with a fixed home/away orientation."""

    round: int = Field(ge=1, examples=[1])
    home: str = Field(min_length=1, examples=["alpha"])
    away: str = Field(min_length=1, examples=["bravo"])


class RoundRobinScheduleRequest(BaseModel):
    """Teams, total rounds, per-team unavailable rounds and fixed matches."""

    teams: list[str] = Field(
        min_length=2,
        max_length=8,
        examples=[["alpha", "bravo", "charlie", "delta"]],
    )
    rounds: int = Field(
        ge=1,
        le=12,
        examples=[3],
        description=(
            "Total number of rounds; must be at least the round-robin "
            "minimum (n-1 for even n, n for odd n) and at most 12."
        ),
    )
    unavailable_rounds: dict[str, list[int]] = Field(
        default_factory=dict,
        description=(
            "Rounds (1-based) in which each team cannot play. Rounds in "
            "which a team rests are simply left without a match for it."
        ),
    )
    fixed_matches: list[FixedMatchIn] = Field(
        default_factory=list,
        description="Matches pinned to a round; their home/away order is kept.",
    )


class ScheduledMatch(BaseModel):
    """One scheduled fixture (no result yet)."""

    home: str = Field(examples=["alpha"])
    away: str = Field(examples=["bravo"])


class ScheduleRound(BaseModel):
    """All matches played in one round, sorted by home id then away id."""

    round: int
    matches: list[ScheduledMatch]


class RoundRobinScheduleResponse(BaseModel):
    teams: list[str]
    rounds: int
    schedule: list[ScheduleRound]
