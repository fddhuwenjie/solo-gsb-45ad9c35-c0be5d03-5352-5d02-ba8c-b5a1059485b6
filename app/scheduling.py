"""Single round-robin schedule generation with venue balancing.

Given 2 to 8 teams and a number of rounds between the round-robin
minimum (``n - 1`` rounds for an even number of teams, ``n`` for an
odd one) and 12, a complete single round-robin schedule is built:

- every unordered pair of teams meets exactly once;
- a team plays at most once per round (extra rounds are byes);
- fixed matches keep their prescribed round and home/away order;
- all other matches avoid the teams' unavailable rounds;
- for every team the difference between home and away games is at
  most one;
- no team plays three consecutive games (in the order of the games it
  plays, ignoring rounds in which it rests) all at home or all away.

Among all feasible schedules the lexicographically smallest one is
returned. Rounds are compared in order; each round is the sorted list
of its ``(home, away)`` pairs, sorted by home id then away id. The
search enumerates round candidates in exactly that order and returns
the first complete schedule, so the result is also stable across
requests: identical payloads always yield identical schedules, and
reordering the ``teams`` array does not change the result.
"""
from __future__ import annotations

from typing import Protocol, Sequence

MIN_TEAMS = 2
MAX_TEAMS = 8
MAX_ROUNDS = 12

HOME = "H"
AWAY = "A"


class FixedGameLike(Protocol):
    round: int
    home: str
    away: str


class ScheduleValidationError(ValueError):
    """Raised when a schedule request is inconsistent or unsatisfiable."""


def minimum_rounds(n: int) -> int:
    """Minimum rounds needed to complete a single round robin with n teams."""
    return n - 1 if n % 2 == 0 else n


def _bipartite_match(
    opponents: Sequence[int], rounds_for: dict[int, list[int]]
) -> bool:
    """Match every opponent of one team to a distinct allowed round.

    Kuhn's algorithm on the opponent -> round bipartite graph. This is
    a necessary-condition relaxation of the full problem (the shared
    rounds still have to agree across teams) used to prune dead ends.
    """
    holder: dict[int, int] = {}

    def augment(opponent: int, seen: set[int]) -> bool:
        for round_ in rounds_for[opponent]:
            if round_ in seen:
                continue
            seen.add(round_)
            current = holder.get(round_)
            if current is None or augment(current, seen):
                holder[round_] = opponent
                return True
        return False

    for opponent in opponents:
        if not augment(opponent, set()):
            return False
    return True


def generate_schedule(
    teams: Sequence[str],
    total_rounds: int,
    unavailable_rounds: dict[str, Sequence[int]] | None = None,
    fixed_matches: Sequence[FixedGameLike] | None = None,
) -> list[list[tuple[str, str]]]:
    """Build the lexicographically smallest feasible round-robin schedule.

    Returns one entry per round (1-based positions are list indices plus
    one); each entry is a list of ``(home, away)`` team id pairs sorted
    by home id then away id. Rounds without matches contain an empty
    list.

    Raises :class:`ScheduleValidationError` for inconsistent input, a
    fixed-match conflict or when no feasible schedule exists.
    """
    team_list = list(teams)
    if any(not isinstance(team, str) or not team for team in team_list):
        raise ScheduleValidationError("team identifiers must be non-empty strings")
    if len(team_list) != len(set(team_list)):
        raise ScheduleValidationError("duplicate team identifiers are not allowed")
    n = len(team_list)
    if not (MIN_TEAMS <= n <= MAX_TEAMS):
        raise ScheduleValidationError(
            f"teams must contain between {MIN_TEAMS} and {MAX_TEAMS} teams"
        )

    needed = minimum_rounds(n)
    if not (needed <= total_rounds <= MAX_ROUNDS):
        raise ScheduleValidationError(
            f"rounds must be between {needed} (minimum for {n} teams) "
            f"and {MAX_ROUNDS}"
        )

    # Indices follow the team ids, never the request order, so that the
    # answer is independent of how the teams array is ordered.
    names = sorted(team_list)
    index = {name: i for i, name in enumerate(names)}

    unavail: list[set[int]] = [set() for _ in range(n)]
    for name, rounds_ in (unavailable_rounds or {}).items():
        if name not in index:
            raise ScheduleValidationError(f"unknown team: '{name}'")
        for round_ in rounds_:
            if not 1 <= round_ <= total_rounds:
                raise ScheduleValidationError(
                    f"unavailable round {round_} for team '{name}' is outside "
                    f"the round range 1..{total_rounds}"
                )
        unavail[index[name]].update(rounds_)

    fixed_by_pair: dict[tuple[int, int], tuple[int, int, int]] = {}
    fixed_by_round: dict[int, list[tuple[int, int, tuple[int, int]]]] = {}
    busy: list[set[int]] = [set() for _ in range(n)]
    for game in fixed_matches or []:
        if game.home not in index:
            raise ScheduleValidationError(f"unknown team: '{game.home}'")
        if game.away not in index:
            raise ScheduleValidationError(f"unknown team: '{game.away}'")
        if game.home == game.away:
            raise ScheduleValidationError(
                f"team '{game.home}' cannot play against itself"
            )
        if not 1 <= game.round <= total_rounds:
            raise ScheduleValidationError(
                f"fixed match '{game.home}' vs '{game.away}' uses round "
                f"{game.round}, outside 1..{total_rounds}"
            )
        h, a = index[game.home], index[game.away]
        if game.round in unavail[h] or game.round in unavail[a]:
            raise ScheduleValidationError(
                f"fixed match '{game.home}' vs '{game.away}' in round "
                f"{game.round} conflicts with a team's unavailable rounds"
            )
        for team in (h, a):
            if game.round in busy[team]:
                raise ScheduleValidationError(
                    f"team '{names[team]}' is placed in two fixed matches "
                    f"in round {game.round}"
                )
        pair = (h, a) if h < a else (a, h)
        if pair in fixed_by_pair:
            raise ScheduleValidationError(
                f"duplicate fixed matchup: '{game.home}' vs '{game.away}'"
            )
        fixed_by_pair[pair] = (game.round, h, a)
        fixed_by_round.setdefault(game.round, []).append((h, a, pair))
        busy[h].add(game.round)
        busy[a].add(game.round)

    all_pairs = [(i, j) for i in range(n) for j in range(i + 1, n)]
    total_matches = len(all_pairs)
    # A team plays n-1 games: home count is fixed for odd n and may
    # differ by one for even n.
    home_lo = (n - 1) // 2
    home_hi = n // 2

    venues: list[list[str]] = [[] for _ in range(n)]
    played: set[tuple[int, int]] = set()
    placements: dict[int, list[tuple[int, int, tuple[int, int]]]] = {}
    failed: set[
        tuple[
            int,
            frozenset[tuple[int, int]],
            tuple[int, ...],
            tuple[str, ...],
        ]
    ] = set()

    def home_counts() -> tuple[int, ...]:
        return tuple(venues[t].count(HOME) for t in range(n))

    def state_key(round_: int):
        return (
            round_,
            frozenset(played),
            home_counts(),
            tuple("".join(venues[t][-2:]) for t in range(n)),
        )

    def can_complete(next_round: int) -> bool:
        """Necessary conditions for finishing from the current state."""
        remaining = total_matches - len(played)
        capacity = 0
        for round_ in range(next_round, total_rounds + 1):
            available = sum(
                1 for t in range(n) if round_ not in unavail[t]
            )
            capacity += available // 2
        if remaining > capacity:
            return False

        for t in range(n):
            homes = venues[t].count(HOME)
            remaining_games = n - 1 - len(venues[t])
            if homes > home_hi or homes + remaining_games < home_lo:
                return False
            # Each of the team's still-unscheduled opponents must be
            # assignable to a distinct future round in which both sides
            # can play.
            opponents: list[int] = []
            rounds_for: dict[int, list[int]] = {}
            for v in range(n):
                if v == t:
                    continue
                pair = (t, v) if t < v else (v, t)
                if pair in played or pair in fixed_by_pair:
                    continue
                allowed = [
                    round_
                    for round_ in range(next_round, total_rounds + 1)
                    if round_ not in unavail[t]
                    and round_ not in busy[t]
                    and round_ not in unavail[v]
                    and round_ not in busy[v]
                ]
                if not allowed:
                    return False
                opponents.append(v)
                rounds_for[v] = allowed
            if not _bipartite_match(opponents, rounds_for):
                return False
        return True

    def dfs(round_: int) -> bool:
        if round_ > total_rounds:
            return len(played) == total_matches

        key = state_key(round_)
        if key in failed:
            return False

        seed = fixed_by_round.get(round_, ())
        for h, a, _pair in seed:
            # A fixed match could force a third consecutive venue.
            if venues[h][-2:] == [HOME, HOME]:
                failed.add(key)
                return False
            if venues[a][-2:] == [AWAY, AWAY]:
                failed.add(key)
                return False

        occupied = {team for h, a, _ in seed for team in (h, a)}
        free = [
            t
            for t in range(n)
            if t not in occupied and round_ not in unavail[t]
        ]

        # Every oriented matching on the free teams is a candidate for
        # this round, always including the fixed matches.
        candidates: list[
            tuple[tuple[tuple[int, int], ...], list[tuple[int, int, tuple[int, int]]]]
        ] = []

        def extend(
            pool: list[int],
            edges: list[tuple[int, int, tuple[int, int]]],
        ) -> None:
            if not pool:
                ordered = tuple(sorted((h, a) for h, a, _ in edges))
                candidates.append((ordered, edges))
                return
            i = pool[0]
            rest = pool[1:]
            # Team i rests in this round.
            extend(rest, edges)
            for k, j in enumerate(rest):
                pair = (i, j) if i < j else (j, i)
                if pair in played or pair in fixed_by_pair:
                    continue
                i_may_home = venues[i][-2:] != [HOME, HOME]
                i_may_away = venues[i][-2:] != [AWAY, AWAY]
                j_may_home = venues[j][-2:] != [HOME, HOME]
                j_may_away = venues[j][-2:] != [AWAY, AWAY]
                without_j = rest[:k] + rest[k + 1 :]
                if i_may_home and j_may_away:
                    extend(without_j, edges + [(i, j, pair)])
                if j_may_home and i_may_away:
                    extend(without_j, edges + [(j, i, pair)])

        extend(free, list(seed))
        candidates.sort(key=lambda candidate: candidate[0])

        for _ordered, edges in candidates:
            for h, a, pair in edges:
                venues[h].append(HOME)
                venues[a].append(AWAY)
                played.add(pair)
            placements[round_] = edges
            if (
                max(home_counts()) <= home_hi
                and can_complete(round_ + 1)
                and dfs(round_ + 1)
            ):
                return True
            for h, a, pair in edges:
                venues[h].pop()
                venues[a].pop()
                played.remove(pair)
            placements.pop(round_, None)

        failed.add(key)
        return False

    if not can_complete(1) or not dfs(1):
        raise ScheduleValidationError(
            "no feasible schedule exists: the unavailable rounds and "
            "fixed matches leave no way to complete the round robin "
            "while satisfying the home/away constraints"
        )

    schedule: list[list[tuple[str, str]]] = []
    for round_ in range(1, total_rounds + 1):
        matches = sorted((h, a) for h, a, _ in placements.get(round_, []))
        schedule.append([(names[h], names[a]) for h, a in matches])
    return schedule
