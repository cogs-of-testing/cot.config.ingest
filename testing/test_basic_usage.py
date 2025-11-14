from cot.config import Config, field


class SampleConfig(Config):
    name: str = field()


def test_basic_from_data() -> None:
    input = {"name": "John"}
    loaded = SampleConfig.from_data(input)

    assert loaded == SampleConfig(name="John")
