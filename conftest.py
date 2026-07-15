import os


def pytest_configure(config):
    if not config.option.basetemp:
        base = os.path.join(os.path.dirname(__file__), ".pytest_tmp", "tmp")
        os.makedirs(base, exist_ok=True)
        config.option.basetemp = base
