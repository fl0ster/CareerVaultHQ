BASE = "/api/candidate-details"

DETAILS = {
    "first_name": " Jane ",
    "last_name": "Doe",
    "email": "jane@example.com",
    "phone": "+48 600 000 000",
    "website": "janedoe.dev",
    "github": "github.com/jane",
    "linkedin": "",
    "location": "Kraków",
    "languages": [{"language": "Polish", "level": "Native"}, {"language": "", "level": "B2"}],
}


def test_get_is_null_until_saved(client):
    res = client.get(BASE)
    assert res.status_code == 200
    assert res.json() is None


def test_put_creates_then_replaces_the_single_row(client):
    res = client.put(BASE, json=DETAILS)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["first_name"] == "Jane"
    # education and certifications are career timeline entries now (work history)
    assert "education" not in body and "certifications" not in body
    assert body["languages"] == [{"language": "Polish", "level": "Native"}]
    assert client.get(BASE).json() == body

    again = client.put(BASE, json={"first_name": "Janet", "last_name": "Doe"}).json()
    assert again["id"] == body["id"]
    assert again["first_name"] == "Janet"
    assert again["email"] == ""
    assert again["languages"] == []


def test_put_validates_lengths(client):
    res = client.put(BASE, json={"first_name": "x" * 200})
    assert res.status_code == 422


PHOTO = "data:image/jpeg;base64,/9j/4AAQSkZJRg=="


def test_photo_is_saved_and_cleared(client):
    body = client.put(BASE, json={**DETAILS, "photo": PHOTO}).json()
    assert body["photo"] == PHOTO
    assert client.get(BASE).json()["photo"] == PHOTO
    assert client.put(BASE, json=DETAILS).json()["photo"] == ""


def test_photo_must_be_an_image_data_url(client):
    for bad in ["https://example.com/me.png", "data:text/html;base64,PGI+", "data:image/png;base64,<b>"]:
        assert client.put(BASE, json={**DETAILS, "photo": bad}).status_code == 422
