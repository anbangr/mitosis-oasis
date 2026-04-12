import pytest
from oasis.social_platform.config.user import UserInfo
from oasis.social_platform.config.neo4j import Neo4jConfig

def test_user_config_loads_from_valid_dict():
    u = UserInfo(
        user_name="alice",
        name="Alice",
        description="test",
        recsys_type="twitter",
        is_controllable=True
    )
    assert u.user_name == "alice"
    assert u.recsys_type == "twitter"
    assert u.is_controllable is True

def test_user_config_missing_optional_fields_defaults():
    u = UserInfo()
    assert u.user_name is None
    assert u.recsys_type == "twitter"
    assert u.is_controllable is False

def test_user_config_system_message():
    u = UserInfo(name="Bob")
    msg = u.to_system_message()
    assert "Your name is Bob" in msg
    assert "twitter" in msg.lower() or "choose some actions" in msg

def test_user_config_reddit_system_message():
    u = UserInfo(
        name="Charlie",
        recsys_type="reddit",
        profile={"other_info": {"user_profile": "Loves programming", "gender": "Male", "age": 25, "mbti": "INTJ", "country": "USA"}}
    )
    msg = u.to_system_message()
    assert "Charlie" in msg
    assert "Reddit user" in msg
    assert "Loves programming" in msg
    assert "Male" in msg

def test_neo4j_config_validates_uri():
    cfg = Neo4jConfig(uri="neo4j://localhost:7687", username="neo4j", password="password")
    assert cfg.is_valid() is True

def test_neo4j_config_invalid():
    cfg = Neo4jConfig(uri=None)
    assert cfg.is_valid() is False
    cfg2 = Neo4jConfig(uri="neo", username="test")
    assert cfg2.is_valid() is False
