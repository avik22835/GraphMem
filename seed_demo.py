"""
Seed two demo conversations into GraphMem production DB.
Run: $env:GROQ_API_KEY="gsk_..." ; $env:GRAPHMEM_API_KEY="gm_sk_..." ; python seed_demo.py

Outputs two conversation IDs — copy them into playground.html.
"""

import os
import time
import requests
from groq import Groq

API_KEY = os.environ.get("GRAPHMEM_API_KEY", "")
ALB     = os.environ.get("GRAPHMEM_ALB", "http://graphmem-alb-1377576243.us-east-1.elb.amazonaws.com")
SLEEP   = 12  # seconds between Groq calls → ~5 RPM, keeps TPM well under 8K limit

groq_client = Groq(api_key=os.environ["GROQ_API_KEY"])
HEADERS = {"X-API-Key": API_KEY, "Content-Type": "application/json"}

SYSTEM = (
    "You are a knowledgeable AI assistant helping a developer. "
    "Give helpful, practical answers in 2-4 sentences. Be direct and conversational."
)


# ── API helpers ───────────────────────────────────────────────────────────────

def create_conv() -> str:
    r = requests.post(f"{ALB}/conversations", headers=HEADERS, json={})
    r.raise_for_status()
    cid = r.json()["conversation_id"]
    print(f"  created conversation: {cid}")
    return cid


def add_node(conv_id: str, prompt: str, response: str) -> str:
    r = requests.post(f"{ALB}/memory/prompt", headers=HEADERS,
                      json={"conversation_id": conv_id, "content": prompt})
    r.raise_for_status()
    mid = r.json()["memory_id"]

    r = requests.post(f"{ALB}/memory/{mid}/response", headers=HEADERS,
                      json={"conversation_id": conv_id, "content": response})
    r.raise_for_status()
    return mid


def groq_reply(history: list, prompt: str) -> str:
    messages = [{"role": "system", "content": SYSTEM}]
    messages += history[-6:]    # keep last 3 turns — limits input tokens for 8K TPM cap
    messages.append({"role": "user", "content": prompt})
    resp = groq_client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=messages,
        max_tokens=150,
    )
    return resp.choices[0].message.content.strip()


# ── Seeder ────────────────────────────────────────────────────────────────────

def seed(label: str, prompts: list[str]) -> str:
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    conv_id = create_conv()
    history = []

    for i, prompt in enumerate(prompts, 1):
        print(f"  [{i:02d}/50] {prompt[:70]}...")
        response = groq_reply(history, prompt)
        add_node(conv_id, prompt, response)
        history.append({"role": "user",      "content": prompt})
        history.append({"role": "assistant", "content": response})
        if i < len(prompts):
            time.sleep(SLEEP)

    print(f"\n  DONE — conv_id: {conv_id}")
    return conv_id


# ── Conversation 1: multi-topic (cooking → travel → coding) ──────────────────

CONV1 = [
    # Cooking (1–12)
    "What's the best way to caramelize onions without burning them?",
    "I tried medium-low heat for 30 minutes but they still came out pale. What am I missing?",
    "Should I add a pinch of baking soda to speed it up?",
    "What dishes work best with caramelized onions?",
    "I want to make French onion soup this weekend — what's the key to a good broth?",
    "Can I use vegetable broth instead of beef broth to make it vegetarian?",
    "What cheese melts best on top of French onion soup?",
    "Gruyère is expensive — any budget substitute that still works well?",
    "How do I make proper homemade croutons for the soup?",
    "Can I prepare the soup a day ahead and reheat it?",
    "What wine pairs well with French onion soup?",
    "What's the difference between a roux and a slurry for thickening soups?",
    # Travel (13–28)
    "Switching gears — I'm planning a solo trip to Southeast Asia next month. Three weeks total.",
    "Should I do Thailand–Vietnam or Thailand–Cambodia–Laos?",
    "Which route is easier for a first-time solo traveler?",
    "How do I handle visas for Thailand and Vietnam?",
    "Best way to get between cities — bus, train, or domestic flights?",
    "Is it safe to use local SIM cards for data?",
    "What's a realistic daily budget for Southeast Asia including accommodation?",
    "I prefer boutique guesthouses over hostels — does that change the budget significantly?",
    "I'm going in October — is that a bad time weather-wise?",
    "Is the October monsoon season a deal-breaker or manageable?",
    "What are some underrated spots in Northern Thailand besides Chiang Mai?",
    "Any tips on respecting local customs as a Western tourist?",
    "What travel insurance do you recommend for Southeast Asia?",
    "How far in advance should I book accommodation in popular spots?",
    "Ok, I think I have enough travel info. Let me shift to something I'm working on.",
    "I'm building a REST API with FastAPI and need help designing the authentication system.",
    # Coding (29–50)
    "Should I use JWT tokens or session-based auth for a stateless API?",
    "My API serves both a web frontend and mobile clients — does that change the recommendation?",
    "What's the difference between access tokens and refresh tokens?",
    "How long should access tokens be valid — is 15 minutes too short?",
    "Where should I store the refresh token — httpOnly cookie or localStorage?",
    "Can you sketch a simple FastAPI dependency to verify JWT tokens?",
    "What library do you recommend for JWT in Python — PyJWT or python-jose?",
    "How do I handle token rotation when the client uses the refresh token?",
    "Should I rate-limit the token refresh endpoint?",
    "What's the best way to revoke tokens before they expire?",
    "I want to add Google OAuth2 social login — how complex is that to add on top?",
    "Can FastAPI handle OAuth2 flows natively or do I need something like Authlib?",
    "What's the difference between authorization_code flow and implicit flow?",
    "Is PKCE required for my mobile app client?",
    "How do I protect against CSRF attacks in my stateless API?",
    "My team wants to support API key auth alongside JWT. Can both coexist on the same endpoint?",
    "How do I structure FastAPI dependency injection so both auth methods work?",
    "Best way to store API keys in Postgres — bcrypt hash?",
    "Should I prefix API keys with something like 'gm_sk_' for easier identification in logs?",
    "Any final security tips before I start implementing?",
    "Thanks — a lot of ground covered today from caramelized onions to OAuth2!",
    "One last thing: what's your single most important piece of advice for building secure APIs?",
]

# ── Conversation 2: SaaS app build (auth → payments → frontend → backend) ─────

CONV2 = [
    # Auth (1–12)
    "I'm building a SaaS app with FastAPI backend and React frontend. Starting with auth — what approach?",
    "I'm leaning toward AWS Cognito since we're already on AWS. Is it worth the added complexity?",
    "How does USER_SRP_AUTH differ from USER_PASSWORD_AUTH in Cognito?",
    "For a web app, which Cognito auth flow is more secure?",
    "How do I verify Cognito JWT tokens in FastAPI without calling Cognito on every request?",
    "What's the format of the Cognito JWKS endpoint and how do I cache it efficiently?",
    "Should I pull user metadata from JWT claims or make a separate Cognito API call?",
    "How do I handle token expiry — force re-login or silently refresh in the background?",
    "Can I add custom attributes to Cognito users, like a subscription_tier field?",
    "How do I handle a user whose account gets disabled mid-session?",
    "What's the cleanest way to implement role-based access control on top of Cognito?",
    "Should I store extra user data in my own Postgres users table or rely entirely on Cognito attributes?",
    # Payments (13–25)
    "Auth is settled. Let's talk Stripe subscriptions — where do I start?",
    "What's the difference between Stripe Checkout and a custom form with Stripe Elements?",
    "For monthly/annual plans, should I model them with Stripe Products and Prices?",
    "Should the subscription creation flow be driven from the frontend or the backend?",
    "Can you show me how to create a Stripe checkout session in Python?",
    "After the user pays, Stripe redirects to my success URL. How do I confirm payment server-side?",
    "Why is polling the session status bad — what should I use instead?",
    "How do I set up Stripe webhooks in FastAPI to receive payment events?",
    "Which webhook events matter most for a subscription SaaS?",
    "How do I verify the Stripe webhook signature to prevent spoofed events?",
    "What happens if my webhook endpoint is down when Stripe fires an event?",
    "How do I handle failed payments and dunning — retries, grace period, cancellation?",
    "How should I model subscription state in my Postgres database?",
    # Frontend (26–37)
    "Payments figured out. Frontend now — Redux or Zustand for state management?",
    "My app has complex nested dashboard state. Does that change your recommendation?",
    "How should I structure my React project — feature folders or type folders?",
    "React Query or SWR for data fetching?",
    "How does React Query handle cache invalidation after a mutation?",
    "I need a sortable, filterable, paginated data table — should I use TanStack Table?",
    "Should I use shadcn/ui or build UI components from scratch?",
    "How do I implement protected routes in React Router v6?",
    "Best way to handle auth token storage and auto-refresh in the React client?",
    "How do I globally intercept 401 responses and redirect to login?",
    "How do I lazy load route components for better performance?",
    "Vite or Next.js for a SaaS dashboard? I don't need SSR.",
    # Backend / Main logic (38–50)
    "Frontend is clear. Core backend now — should business logic live in route handlers or a service layer?",
    "How do I design a service layer in FastAPI — plain Python classes or something else?",
    "How do I handle database transactions that span multiple service calls in asyncpg?",
    "Background tasks — Celery, ARQ, or FastAPI BackgroundTasks?",
    "I need transactional emails — welcome, invoice, password reset. What service integrates best with FastAPI?",
    "How do I implement feature flags to roll out features to specific users only?",
    "What caching strategy for expensive DB queries — Redis with what invalidation approach?",
    "How do I structure dev/staging/prod environment configs in FastAPI with Pydantic Settings?",
    "Best practice for writing integration tests that hit a real database in FastAPI?",
    "How do I set up CI/CD for FastAPI + React on AWS ECS with GitHub Actions?",
    "What observability stack do you recommend — CloudWatch, Datadog, or OpenTelemetry?",
    "How do I achieve zero-downtime deployments on ECS?",
    "This has been incredibly useful — I feel like I have a complete architecture blueprint. Thank you!",
]


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("GraphMem Demo Seed Script")
    print(f"  ALB : {ALB}")
    print(f"  sleep: {SLEEP}s between Groq calls (~{60 // SLEEP} RPM, <8K TPM)")
    print(f"  total: ~{(len(CONV1) + len(CONV2)) * SLEEP // 60} minutes estimated\n")

    conv1_id = seed("Conv 1 — multi-topic: cooking → travel → coding", CONV1)
    conv2_id = seed("Conv 2 — SaaS app build: auth → payments → frontend → backend", CONV2)

    print("\n" + "="*60)
    print("SEED COMPLETE — paste these into playground.html:")
    print(f'  CONV1_ID = "{conv1_id}"  # multi-topic')
    print(f'  CONV2_ID = "{conv2_id}"  # saas app build')
    print("="*60)
