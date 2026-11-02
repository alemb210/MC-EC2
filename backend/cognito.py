import boto3
from botocore.config import Config

# No client at import time, matching ec2.py.
client = None

def get_client(region):
    return client if client is not None else boto3.client(
        "cognito-idp", region_name=region,
        config=Config(connect_timeout=3, read_timeout=5, retries={"total_max_attempts": 1}))

def _find_sub(cognito, user_pool_id, email):
    # The caller validated email, which can't contain quotes or backslashes.
    users = cognito.list_users(UserPoolId=user_pool_id, Filter=f'email = "{email}"', Limit=1)["Users"]
    for user in users:
        # An unconfirmed signup hasn't proved it owns this email.
        if user.get("Enabled") and user.get("UserStatus") != "UNCONFIRMED":
            return next((a["Value"] for a in user["Attributes"] if a["Name"] == "sub"), None)
    return None

#The Cognito sub of the confirmed user with this email, or None.
def find_user_sub(email, user_pool_id, region):
    cognito = get_client(region)
    # Cognito may store the email as typed at signup, so try it as given before lowercase.
    for candidate in dict.fromkeys([email, email.lower()]):
        sub = _find_sub(cognito, user_pool_id, candidate)
        if sub:
            return sub
    return None
