import topicparser.config as config
from topicparser.api import Api

def test_save_profiles_writes_yaml(tmp_path):
    path = str(tmp_path / "p.yaml")
    api = Api(profiles={"profiles": {}}, build_collectors=lambda: [],
              build_client=lambda: None, threshold=80, x_days=3, gh_days=21,
              profiles_path=path)
    api.save_profiles({"profiles": {"AI": {"github": {"topics": ["mcp"]}}}})
    assert config.load_profiles(path)["profiles"]["AI"]["github"]["topics"] == ["mcp"]
