"""Options pytest communes à toute la suite."""


def pytest_addoption(parser):
    parser.addoption(
        "--update-golden",
        action="store_true",
        default=False,
        help="Régénère les références de tests/fixtures/golden/ au lieu de les comparer.",
    )
