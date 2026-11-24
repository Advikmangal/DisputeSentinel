import pytest
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.models import Merchant
from app.routers.auth import signup_attempts
from app.services.auth import verify_password
from app.tests.test_payments import api, create


@pytest.fixture(autouse=True)
def reset_signup_limit():
    signup_attempts.clear()
    yield
    signup_attempts.clear()


def test_public_registration_login_and_isolation(api):
    client, _, engine = api
    existing = create(client).json()['transaction']
    client.headers.pop('Authorization')
    password = 'synthetic-strong-password'
    response = client.post('/api/auth/register', json={'email': ' Visitor@Example.com ', 'password': password})
    assert response.status_code == 201
    client.headers['Authorization'] = 'Bearer ' + response.json()['access_token']
    items = client.get('/api/transactions').json()['items']
    assert len(items) == 3
    assert all(t['is_demo'] and t['status'] == 'CREATED' and t['paypal_capture_id'] is None for t in items)
    assert client.get(f"/api/transactions/{existing['id']}").status_code == 404
    assert client.get(f"/api/transactions/{existing['id']}/evidence").status_code == 404
    assert client.post('/api/payments/capture', json={'order_id': items[0]['paypal_order_id']}).status_code == 409
    with Session(engine) as db:
        merchant = db.scalar(select(Merchant).where(Merchant.email == 'visitor@example.com'))
        assert merchant.password_hash != password
        assert verify_password(password, merchant.password_hash)
    client.headers.pop('Authorization')
    assert client.post('/api/auth/login', json={'email': 'VISITOR@example.com', 'password': password}).status_code == 200
    duplicate = client.post('/api/auth/register', json={'email': 'visitor@example.com', 'password': 'different-password'})
    assert duplicate.status_code == 409
    assert client.post('/api/auth/login', json={'email': 'visitor@example.com', 'password': password}).status_code == 200


@pytest.mark.parametrize('email,password', [('invalid', 'long-enough-password'), ('a@b', 'long-enough-password'), ('a..b@example.com', 'long-enough-password'), ('visitor@example.com', 'short'), ('visitor@example.com', 'x' * 129)])
def test_invalid_registration_does_not_create_account(api, email, password):
    client, _, engine = api
    client.headers.pop('Authorization')
    response = client.post('/api/auth/register', json={'email': email, 'password': password})
    assert response.status_code == 422
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(Merchant)) == 2


def test_registration_rate_limit(api):
    client, _, _ = api
    client.headers.pop('Authorization')
    for _ in range(5):
        assert client.post('/api/auth/register', json={'email': 'bad', 'password': 'short'}).status_code == 422
    response = client.post('/api/auth/register', json={'email': 'bad', 'password': 'short'})
    assert response.status_code == 429
    assert response.headers['Retry-After'] == '60'
