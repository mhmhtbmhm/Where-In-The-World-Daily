# شغّله مرة واحدة على حاسوبك لكل قناة: pip install google-auth-oauthlib
from google_auth_oauthlib.flow import InstalledAppFlow
flow = InstalledAppFlow.from_client_secrets_file(
    "client_secret.json", ["https://www.googleapis.com/auth/youtube.upload"])
creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
print("REFRESH TOKEN:", creds.refresh_token)
