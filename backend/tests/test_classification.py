from app.classification import metadata_guess, parse_model_answer

def test_metadata():
    assert metadata_guess("The Red Planet Mars", "") == "Mars"
    assert metadata_guess("Earth and Mars", "") == "Unknown"
    assert metadata_guess("Unlabeled crater", "Mars") == "Unknown"

def test_model_parse():
    assert parse_model_answer('{"label":"Jupiter","confidence":"high","reason":"bands","visible_features":["cloud bands"]}')["label"] == "Jupiter"
    assert parse_model_answer('{"label":"Pluto","confidence":"high"}')["label"] == "Unknown"
