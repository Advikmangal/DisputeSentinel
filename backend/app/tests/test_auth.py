from datetime import datetime, timedelta, timezone
import jwt
import pytest
from sqlalchemy.orm import Session
from app.config import get_settings
from app.models import Merchant
from app.services.auth import hash_password, verify_password
from app.tests.test_payments import api, create


def test_login_success_and_twelve_hour_expiry(api):
    client, state, _ = api
    response = client.post('/api/auth/login', json={'email': 'one@example.invalid', 'password': state['password']})
    assert response.status_code == 200
    data = response.json()
    assert data['expires_in'] == 43200 and data['token_type'] == 'bearer'
    claims = jwt.decode(data['access_token'], get_settings().jwt_secret.get_secret_value(), algorithms=['HS256'], audience='payoutsentinel-api')
    assert claims['exp'] - claims['iat'] == 43200 and claims['sub'] == '1'


@pytest.mark.parametrize('email', ['one@example.invalid', 'missing@example.invalid'])
def test_wrong_password(api, email):
    client, _, _ = api
    response = client.post('/api/auth/login', json={'email': email, 'password': 'incorrect-test-input'})
    assert response.status_code == 401 and response.json()['detail'] == 'Invalid email or password.'


@pytest.mark.parametrize('kind', ['expired', 'tampered', 'wrong_audience', 'no_expiry', 'none_algorithm', 'invalid_expiry'])
def test_invalid_tokens(api, kind):
    client, _, _ = api
    now = datetime.now(timezone.utc)
    claims = {'sub': '1', 'iss': 'payoutsentinel', 'aud': 'payoutsentinel-api', 'iat': now - timedelta(hours=13), 'exp': now + timedelta(hours=1)}
    if kind == 'expired': claims['exp'] = now - timedelta(seconds=1)
    if kind == 'wrong_audience': claims['aud'] = 'other'
    if kind == 'no_expiry': del claims['exp']
    if kind == 'invalid_expiry': claims['exp'] = {'invalid': True}
    key = get_settings().jwt_secret.get_secret_value()
    token = jwt.encode(claims, '' if kind == 'none_algorithm' else key, algorithm='none' if kind == 'none_algorithm' else 'HS256')
    if kind == 'tampered': token = token[:-5] + 'XXXXX'
    client.headers['Authorization'] = 'Bearer ' + token
    assert client.get('/api/transactions').status_code == 401


@pytest.mark.parametrize('method,path,body', [('GET','/api/transactions',None),('GET','/api/transactions/1',None),('POST','/api/payments/create-order',{}),('POST','/api/payments/capture',{})])
def test_all_api_routes_require_token(api, method, path, body):
    client, _, _ = api
    client.headers.pop('Authorization')
    assert client.request(method, path, json=body).status_code == 401
    assert client.get('/health').status_code == 200


def test_other_merchant_token_cannot_read_or_capture(api):
    client, state, _ = api
    created = create(client).json()['transaction']
    response = client.post('/api/auth/login', json={'email': 'two@example.invalid', 'password': state['password']})
    client.headers['Authorization'] = 'Bearer ' + response.json()['access_token']
    assert client.get(f"/api/transactions/{created['id']}").status_code == 404
    assert client.get('/api/transactions').json() == {'items': []}
    assert client.post('/api/payments/capture', json={'order_id': created['paypal_order_id']}).status_code == 404


def test_password_hash_salted_and_not_plaintext(api):
    _, state, engine = api
    with Session(engine) as db:
        encoded = db.get(Merchant, 1).password_hash
    assert state['password'] not in encoded
    assert verify_password(state['password'], encoded)
    assert encoded != hash_password(state['password'])
    assert not verify_password('wrong', encoded)


def test_seed_requires_password_and_preserves_existing_hash(api):
    import runpy
    from pathlib import Path
    seed = runpy.run_path(str(Path(__file__).resolve().parents[3] / 'scripts/seed_merchant.py'))['seed']
    _, state, engine = api
    with Session(engine) as db:
        with pytest.raises(ValueError):
            seed(db, 'new@example.invalid', '')
        assert seed(db, 'new@example.invalid', state['password'])
        from sqlalchemy import select
        merchant = db.scalar(select(Merchant).where(Merchant.email == 'new@example.invalid'))
        encoded = merchant.password_hash
        assert verify_password(state['password'], encoded)
        assert not seed(db, 'new@example.invalid', 'different-test-password')
        db.refresh(merchant)
        assert merchant.password_hash == encoded
