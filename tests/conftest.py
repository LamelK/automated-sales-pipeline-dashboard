import pytest
from prefect.testing.utilities import prefect_test_harness


@pytest.fixture(scope="session", autouse=True)
def prefect_ephemeral_api():
    """
    Run flows against a throwaway local Prefect API.

    Without this, every test that executes a flow registers a real flow run in the
    workspace the local machine is logged into.
    """
    with prefect_test_harness():
        yield
