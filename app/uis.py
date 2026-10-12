"""Fudan UIS authorization-code contract shared with WordTxT, without type filtering."""
import os
from typing import Annotated, Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

NonEmptyString = Annotated[str, Field(min_length=1)]


class AuthModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, str_strip_whitespace=True)


class UISUserInfo(AuthModel):
    user_id: NonEmptyString
    user_name: NonEmptyString
    user_type: NonEmptyString
    sessionId: NonEmptyString
    mobile: str | None = None
    email: str | None = None
    department: str | None = None


class OAuthToken(AuthModel):
    access_token: NonEmptyString
    token_type: str | None = None
    expires_in: int | None = Field(default=None, ge=0)
    refresh_token: str | None = None
    scope: str | None = None


class UISSettings(BaseModel):
    client_id: str = ''
    client_secret: SecretStr = SecretStr('')
    authorization_url: str = 'https://id.fudan.edu.cn/idp/authCenter/authenticate'
    token_url: str = 'https://id.fudan.edu.cn/idp/api/v3/oauth2/token'
    user_info_url: str = 'https://id.fudan.edu.cn/idp/api/v3/oauth2/userInfo'
    logout_url: str = 'https://id.fudan.edu.cn/idp/authCenter/GLO'
    redirect_uri: str = 'https://lushangstudio.fudan.edu.cn/leave/api/auth/callback'
    frontend_url: str = 'https://lushangstudio.fudan.edu.cn/leave/'
    state_ttl: int = Field(default=600, ge=1, le=3600)
    session_ttl: int = Field(default=28800, ge=1, le=604800)

    @property
    def configured(self):
        return bool(self.client_id.strip() and self.client_secret.get_secret_value().strip() and self.redirect_uri.strip())

    @classmethod
    def from_env(cls):
        fields={'client_id':'UIS_OAUTH_CLIENT_ID','client_secret':'UIS_OAUTH_CLIENT_SECRET',
                'authorization_url':'UIS_OAUTH_AUTHORIZATION_URL','token_url':'UIS_OAUTH_TOKEN_URL',
                'user_info_url':'UIS_OAUTH_USER_INFO_URL','logout_url':'UIS_OAUTH_LOGOUT_URL',
                'redirect_uri':'UIS_OAUTH_REDIRECT_URI','frontend_url':'AUTH_FRONTEND_URL',
                'state_ttl':'AUTH_STATE_TTL_SECONDS','session_ttl':'AUTH_SESSION_TTL_SECONDS'}
        try:return cls(**{field:os.environ[key] for field,key in fields.items() if key in os.environ})
        except ValidationError:raise RuntimeError('Invalid UIS environment configuration') from None


class OAuthProviderError(RuntimeError):
    pass


class UISOAuthClient:
    def __init__(self,settings:UISSettings,client:httpx.AsyncClient|None=None):
        self.settings,self.client=settings,client

    def build_authorization_url(self,state):
        return str(httpx.URL(self.settings.authorization_url).copy_merge_params({
            'response_type':'code','client_id':self.settings.client_id,
            'redirect_uri':self.settings.redirect_uri,'state':state}))

    async def exchange_code(self,code):
        data=await self._request('POST',self.settings.token_url,
                                 auth=httpx.BasicAuth(self.settings.client_id,self.settings.client_secret.get_secret_value()),
                                 data={'grant_type':'authorization_code','code':code})
        try:return OAuthToken.model_validate(data)
        except ValidationError:raise OAuthProviderError('Invalid UIS token response') from None

    async def fetch_user_info(self,token):
        data=await self._request('GET',self.settings.user_info_url,headers={'Authorization':f'Bearer {token}'})
        try:return UISUserInfo.model_validate(data)
        except ValidationError:raise OAuthProviderError('Invalid UIS user info response') from None

    async def _request(self,method,url,**kwargs:Any):
        try:
            if self.client is None:
                async with httpx.AsyncClient(timeout=15) as client:response=await client.request(method,url,**kwargs)
            else:response=await self.client.request(method,url,**kwargs)
            if not response.is_success:raise OAuthProviderError('UIS request failed')
            data=response.json()
        except (httpx.RequestError,ValueError):raise OAuthProviderError('UIS request failed') from None
        if not isinstance(data,dict) or 'errcode' in data:raise OAuthProviderError('UIS request failed')
        return data
