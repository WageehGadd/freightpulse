import pathlib

# Simple deterministic client used in tests.
# It reads the fixture JSON file and returns the 'expected_output' field.

class FakeFreightPulseAIClient:
    def __init__(self, fixture_path: pathlib.Path):
        self.fixture_path = pathlib.Path(fixture_path)
        # Load fixture once
        import json
        with self.fixture_path.open() as f:
            self.fixture = json.load(f)

    def generate_structured(self, *args, **kwargs):
        """Return the pre‑defined expected output for the fixture.

        The real AI client would accept a prompt and return a model instance.
        In tests we bypass that and just return the deterministic payload.
        """
        return self.fixture.get("expected_output")
