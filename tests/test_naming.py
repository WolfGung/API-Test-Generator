from api_test_gen.naming import plural, to_class_name, to_identifier, unique


def test_camel_case_becomes_snake_case():
    assert to_identifier("findPetsByStatus") == "find_pets_by_status"
    assert to_identifier("getPetById") == "get_pet_by_id"


def test_separators_and_case_are_normalised():
    assert to_identifier("Pet ID") == "pet_id"
    assert to_identifier("GET /pet/{petId}") == "get_pet_pet_id"
    assert to_identifier("  weird--name__ ") == "weird_name"


def test_identifiers_are_valid_python():
    assert to_identifier("2fa") == "field_2fa"
    assert to_identifier("class") == "class_"
    assert to_identifier("") == "value"
    assert to_identifier("___") == "value"


def test_class_names_are_pascal_case():
    assert to_class_name("pet") == "Pet"
    assert to_class_name("find_pets_by_status") == "FindPetsByStatus"
    assert to_class_name("ApiResponse") == "ApiResponse"
    assert to_class_name("api-response") == "ApiResponse"
    assert to_class_name("2fa token") == "Model2faToken"
    assert to_class_name("") == "Model"


def test_unique_appends_a_counter_and_records_the_name():
    taken: set[str] = set()
    assert unique("pet", taken) == "pet"
    assert unique("pet", taken) == "pet_2"
    assert unique("pet", taken) == "pet_3"
    assert taken == {"pet", "pet_2", "pet_3"}


def test_plural():
    assert (plural(1, "test"), plural(0, "test"), plural(2, "operation")) == ("1 test", "0 tests", "2 operations")
