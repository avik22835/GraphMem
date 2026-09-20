import boto3
import subprocess

CLIENT_ID     = "706dfajvla7jbsgllh22ki5c45"
REGION        = "us-east-1"
USERNAME      = "avik22835@gmail.com"
TEMP_PASSWORD = "GraphMem2026!"
PASSWORD      = "GraphMem2026!"
ALB           = "http://graphmem-alb-1377576243.us-east-1.elb.amazonaws.com"

cognito = boto3.client("cognito-idp", region_name=REGION)

print("Authenticating...")
resp = cognito.initiate_auth(
    ClientId=CLIENT_ID,
    AuthFlow="USER_PASSWORD_AUTH",
    AuthParameters={"USERNAME": USERNAME, "PASSWORD": TEMP_PASSWORD},
)

if resp.get("ChallengeName") == "NEW_PASSWORD_REQUIRED":
    print("Setting permanent password...")
    resp = cognito.respond_to_auth_challenge(
        ClientId=CLIENT_ID,
        ChallengeName="NEW_PASSWORD_REQUIRED",
        Session=resp["Session"],
        ChallengeResponses={"USERNAME": USERNAME, "NEW_PASSWORD": PASSWORD},
    )

id_token = resp["AuthenticationResult"]["IdToken"]
print("Got JWT. Calling ALB directly...")

result = subprocess.run([
    "curl.exe", "-s", "-w", "\nHTTP_STATUS:%{http_code}", "-X", "POST",
    f"{ALB}/auth/keys",
    "-H", f"Authorization: Bearer {id_token}",
    "-H", "Content-Type: application/json",
    "-d", '{"project_name":"admin"}',
], capture_output=True, text=True)

print("Response:", result.stdout)
if result.stderr:
    print("Stderr:", result.stderr)
