from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Role(str, Enum):
    TESTER = "T"
    PEER = "P"


@dataclass
class Person:
    name: str
    role: Role
    availability: dict[str, bool]
    pref_loc_flags: dict[str, int]  # location -> 0 (hard ban) | 1 (penalise) | 2 (ok/preferred)
    date_loc2_only: dict[str, str]
    date_loc2_banned: dict[str, str]
    month_max: int = 0
    month_avg: int = 0
    idx: int = field(default=-1, repr=False, compare=False)

    def is_available(self, date: str) -> bool:
        return bool(self.availability.get(date, True))

    def loc_flag(self, location: str) -> int:
        return self.pref_loc_flags.get(location, 2)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "role": self.role.value,
            "availability": self.availability,
            "pref_loc_flags": self.pref_loc_flags,
            "date_loc2_only": self.date_loc2_only,
            "date_loc2_banned": self.date_loc2_banned,
            "month_max": self.month_max,
            "month_avg": self.month_avg,
        }


@dataclass
class Shift:
    location: str
    day: str
    date: str
    weeknummer: int
    team: int
    allow_peer: bool = True
    allow_tester: bool = True
    testers: list[str] = field(default_factory=list)
    idx: int = field(default=-1, repr=False, compare=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "location": self.location,
            "day": self.day,
            "date": self.date,
            "weeknummer": self.weeknummer,
            "team": self.team,
            "testers": self.testers,
        }


@dataclass
class PenaltyRow:
    component: str
    person: str
    units: int
    weighted: int
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "component": self.component,
            "person": self.person,
            "units": self.units,
            "weighted": self.weighted,
            **self.extra,
        }


@dataclass
class DiagnosticDay:
    date: str
    location: str
    required: int
    assigned: int
    available: int
    available_T: int
    available_P: int
    reason: str
    c_availability: bool = False
    c_max_per_day: bool = False
    c_max_per_week: bool = False
    c_single_first: bool = False
    c_exclusions: bool = False

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass
class Weights:
    location: int = 0
    fairness: int = 0
    monthly: int = 0
    monthly_avg: int = 0
    weekly_multi: int = 0
    monthly_min_avail: int = 0
    location_fairness: int = 0
    coverage: int = 0

    @classmethod
    def from_config(cls, weights_conf: dict[str, Any], selected: set[str]) -> Weights:
        def _pick(key: str, default: int = 0) -> int:
            return int(weights_conf.get(key, default)) if key in selected else 0

        return cls(
            location=_pick("location"),
            fairness=_pick("fairness"),
            monthly=_pick("monthly"),
            monthly_avg=_pick("monthly_avg"),
            weekly_multi=_pick("weekly_multi"),
            monthly_min_avail=_pick("monthly_min_avail"),
            location_fairness=_pick("location_fairness"),
            coverage=_pick("coverage", 100),
        )

    def enable_coverage(self, weights_conf: dict[str, Any]) -> None:
        if self.coverage == 0:
            self.coverage = int(weights_conf.get("coverage", 100))

    def as_dict(self) -> dict[str, int]:
        return dataclasses.asdict(self)


class PersonList(list):
    """list[Person] with fluent chainable filters.

    Each Person.idx is stamped with its position in the original (unfiltered) list.
    Indices survive all filter operations so person.idx always maps to
    assignment_vars[(person.idx, ...)].
    """

    def __init__(self, iterable=()):
        super().__init__(iterable)
        for i, p in enumerate(self):
            p.idx = i

    @classmethod
    def _from_filtered(cls, iterable) -> PersonList:
        """Create a PersonList from pre-indexed objects without resetting their idx."""
        inst = cls.__new__(cls)
        list.__init__(inst, iterable)
        return inst

    def enumerate(self):
        """Yield (person.idx, person) — indices survive filtering."""
        return ((p.idx, p) for p in self)

    def filter_role(self, role: Role) -> PersonList:
        return PersonList._from_filtered(p for p in self if p.role == role)

    def filter_available_on(self, date: str) -> PersonList:
        return PersonList._from_filtered(p for p in self if p.is_available(date))

    def filter_location_pref(self, location: str, min_flag: int = 1) -> PersonList:
        """Keep persons whose loc_flag for *location* is >= *min_flag*.
        min_flag=1 → include penalised (1) and preferred (2), exclude hard-banned (0).
        min_flag=2 → only explicitly preferred.
        """
        return PersonList._from_filtered(p for p in self if p.loc_flag(location) >= min_flag)

    def filter_location_not_banned(self, location: str) -> PersonList:
        """Exclude anyone hard-banned (flag == 0) from *location*."""
        return PersonList._from_filtered(p for p in self if p.loc_flag(location) > 0)

    def filter_month_max(self, month: int, current_count: dict[str, int]) -> PersonList:
        """Keep persons who have not yet hit their month_max for *month*.
        *current_count* maps person.name -> shifts already assigned this month.
        """
        return PersonList._from_filtered(
            p for p in self if p.month_max == 0 or current_count.get(p.name, 0) < p.month_max
        )

    def names(self) -> list[str]:
        return [p.name for p in self]

    def by_name(self, name: str) -> Person | None:
        return next((p for p in self if p.name == name), None)


class ShiftList(list):
    """list[Shift] with fluent chainable filters.

    Each Shift.idx is stamped with its position in the original (unfiltered) list.
    Indices survive all filter operations so shift.idx always maps to
    assignment_vars[(..., shift.idx)].
    """

    def __init__(self, iterable=()):
        super().__init__(iterable)
        for i, s in enumerate(self):
            s.idx = i

    @classmethod
    def _from_filtered(cls, iterable) -> ShiftList:
        """Create a ShiftList from pre-indexed objects without resetting their idx."""
        inst = cls.__new__(cls)
        list.__init__(inst, iterable)
        return inst

    def enumerate(self):
        """Yield (shift.idx, shift) — indices survive filtering."""
        return ((s.idx, s) for s in self)

    def filter_date(self, date: str) -> ShiftList:
        return ShiftList._from_filtered(s for s in self if s.date == date)

    def filter_location(self, location: str) -> ShiftList:
        return ShiftList._from_filtered(s for s in self if s.location == location)

    def filter_week(self, weeknummer: int) -> ShiftList:
        return ShiftList._from_filtered(s for s in self if s.weeknummer == weeknummer)

    def filter_team(self, team: int) -> ShiftList:
        return ShiftList._from_filtered(s for s in self if s.team == team)

    def filter_allows_role(self, role: Role) -> ShiftList:
        if role == Role.TESTER:
            return ShiftList._from_filtered(s for s in self if s.allow_tester)
        return ShiftList._from_filtered(s for s in self if s.allow_peer)

    def filter_unplanned(self, required: int = 2) -> ShiftList:
        """Shifts that have fewer testers assigned than *required*."""
        return ShiftList._from_filtered(s for s in self if len(s.testers) < required)

    def dates(self) -> list[str]:
        return sorted({s.date for s in self})

    def locations(self) -> list[str]:
        return sorted({s.location for s in self})


class AssignmentVars(dict):
    """dict[(person.idx, shift.idx) -> BoolVar] for the solver assignment variables."""

    @classmethod
    def create(cls, persons: PersonList, shifts: ShiftList, model) -> AssignmentVars:
        inst = cls()
        for person in persons:
            for shift in shifts:
                inst[(person.idx, shift.idx)] = model.NewBoolVar(
                    f"{person.name}_op_{shift.location}_{shift.day}_team{shift.team}_date_{shift.date}"
                )
        return inst


@dataclass
class SolverResult:
    """Wraps the (solver, status) pair returned by cp_model.CpSolver.Solve()."""
    solver: Any  # cp_model.CpSolver
    status: int  # cp_model status constant


@dataclass
class SolverContext:
    """Bundles all solver state so functions take one arg instead of four."""
    model: Any  # cp_model.CpModel
    persons: PersonList
    shifts: ShiftList
    assignment_vars: AssignmentVars = field(default_factory=lambda: AssignmentVars())
    weights: Weights = field(default_factory=Weights)
