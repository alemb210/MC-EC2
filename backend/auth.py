from dataclasses import dataclass
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from config import Settings

@dataclass(frozen=True)
class Principal:
    """The authenticated caller. sub is the Cognito user ID (identities.provider_id)."""
    sub: str

# Mock mode has no Cognito; every request acts as this user.
MOCK_PRINCIPAL = Principal(sub="mock-user")

class InvalidToken(Exception):
    pass

class AuthUnavailable(Exception):
    pass

class CognitoVerifier:
    """Verifies Cognito access tokens: signature, issuer, expiry, token_use and app client."""

    def __init__(self, region: str, user_pool_id: str, client_id: str):
        self.issuer = f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}"
        self.client_id = client_id
        # Keys are cached across requests in a warm Lambda.
        self.jwks = jwt.PyJWKClient(f"{self.issuer}/.well-known/jwks.json", cache_keys=True, timeout=3)

    def verify(self, token: str) -> Principal:
        try:
            key = self.jwks.get_signing_key_from_jwt(token).key
            # Cognito access tokens carry client_id instead of aud.
            claims = jwt.decode(token, key, algorithms=["RS256"], issuer=self.issuer,
                                options={"verify_aud": False,
                                         "require": ["exp", "iss", "sub", "token_use", "client_id"]})
        except jwt.PyJWKClientConnectionError as exc:
            raise AuthUnavailable from exc
        except (jwt.InvalidTokenError, jwt.PyJWKClientError) as exc:
            raise InvalidToken from exc
        if claims["token_use"] != "access" or claims["client_id"] != self.client_id:
            raise InvalidToken
        if not isinstance(claims["sub"], str) or not claims["sub"].strip():
            raise InvalidToken
        return Principal(sub=claims["sub"])

def build_verifier(settings: Settings) -> CognitoVerifier | None:
    if settings.mock_mode or not (settings.cognito_user_pool_id and settings.cognito_client_id):
        return None
    return CognitoVerifier(settings.aws_region, settings.cognito_user_pool_id, settings.cognito_client_id)

def current_user_dependency(settings: Settings, verifier: CognitoVerifier | None):
    bearer = HTTPBearer(auto_error=False)

    def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> Principal:
        if settings.mock_mode:
            return MOCK_PRINCIPAL
        # Fail closed: without Cognito configuration no request is authenticated.
        if verifier is None:
            raise HTTPException(503, "Authentication is not configured.")
        if credentials is None:
            raise HTTPException(401, "Missing bearer token.", headers={"WWW-Authenticate": "Bearer"})
        try:
            return verifier.verify(credentials.credentials)
        except AuthUnavailable:
            raise HTTPException(503, "Unable to verify token right now. Try again shortly.") from None
        except InvalidToken:
            raise HTTPException(401, "Invalid or expired token.", headers={"WWW-Authenticate": "Bearer"}) from None

    return current_user
