"""Tests du découpage de la CLI (lot 5) : un module par groupe, transfert d'arguments de `aospy l3`."""

from __future__ import annotations

import argparse
import sys
import types

import pytest

from aospy import cli
from aospy.cli import commands, l3
from aospy.tournament_kit.modes import MODES

_GROUP_COMMANDS = ["init", "reset", "army", "unit", "comp", "battle", "import", "cost", "roster",
                   "ability", "chassis", "encounter", "l3"]


def _subparsers(parser: argparse.ArgumentParser) -> argparse._SubParsersAction:
    return next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))


def test_groups_registered_in_help_order():
    assert list(_subparsers(cli._build_parser()).choices) == _GROUP_COMMANDS


def test_every_subcommand_has_a_handler():
    def walk(parser):
        sub = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]
        if not sub:
            assert callable(parser.get_default("func")), parser.prog
        for action in sub:
            for child in action.choices.values():
                walk(child)

    walk(cli._build_parser())


def test_roster_mode_choices_follow_modes():
    roster = _subparsers(cli._build_parser()).choices["roster"]
    pdf = _subparsers(roster).choices["pdf"]
    mode = next(a for a in pdf._actions if a.dest == "mode")
    assert mode.choices == list(MODES)


def test_commands_facade_reexports_handlers():
    assert commands.cmd_unit_duel.__module__ == "aospy.cli.unit"
    assert commands.cmd_roster_pdf.__module__ == "aospy.cli.roster"


def test_unknown_argument_still_rejected(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["army", "list", "--bogus"])
    assert exc.value.code == 2
    assert "unrecognized arguments: --bogus" in capsys.readouterr().err


@pytest.mark.parametrize("argv", [[], ["--rank", "5"], ["--help"], ["diff", "a", "--md"]])
def test_l3_forwards_arguments_verbatim(monkeypatch, argv):
    seen = {}
    fake = types.ModuleType("aospy.l3.diag")
    fake.main = lambda a: seen.setdefault("argv", a) and 0
    monkeypatch.setitem(sys.modules, "aospy.l3.diag", fake)
    assert cli.main(["l3", "diag", *argv]) == 0
    assert seen["argv"] == argv


def test_l3_commands_point_to_modules_with_main():
    import importlib.util

    for module, _help in l3._COMMANDS.values():
        assert importlib.util.find_spec(f"aospy.l3.{module}") is not None
