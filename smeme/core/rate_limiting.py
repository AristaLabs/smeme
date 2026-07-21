"""Rate limiting configuration using slowapi."""

from slowapi import Limiter
from slowapi.util import get_remote_address

# Create limiter instance with IP-based key function
# Uses in-memory storage (suitable for single-instance deployment)
limiter = Limiter(key_func=get_remote_address)

# Rate limit strings for auth endpoints
# Format: "X per Y" where X is count, Y is period (minute, hour, day)
RATE_LIMIT_LOGIN = "5/15 minutes"  # 5 attempts per 15 minutes
RATE_LIMIT_REGISTER = "10/hour"  # 10 registrations per hour per IP
RATE_LIMIT_FORGOT_PASSWORD = "3/hour"  # 3 reset requests per hour
RATE_LIMIT_RESET_PASSWORD = "5/hour"  # 5 reset attempts per hour
RATE_LIMIT_TEAMS_WAITLIST = "5/hour"  # public waitlist signups per IP
