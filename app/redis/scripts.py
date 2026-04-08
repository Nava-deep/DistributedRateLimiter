FIXED_WINDOW_LUA = """
local limit = tonumber(ARGV[1])
local window_ms = tonumber(ARGV[2])

local now = redis.call("TIME")
local now_ms = now[1] * 1000 + math.floor(now[2] / 1000)
local window_start = now_ms - (now_ms % window_ms)
local key = KEYS[1] .. ":" .. window_start

local count = redis.call("INCR", key)
if count == 1 then
  redis.call("PEXPIRE", key, window_ms + 1000)
end

local reset_at_ms = window_start + window_ms
local remaining = 0
local allowed = 0

if count <= limit then
  allowed = 1
  remaining = limit - count
end

local retry_ms = math.max(0, reset_at_ms - now_ms)
return {allowed, limit, remaining, reset_at_ms, retry_ms, count}
"""


SLIDING_WINDOW_LOG_LUA = """
local limit = tonumber(ARGV[1])
local window_ms = tonumber(ARGV[2])
local member = ARGV[3]

local now = redis.call("TIME")
local now_ms = now[1] * 1000 + math.floor(now[2] / 1000)
local cutoff = now_ms - window_ms

redis.call("ZREMRANGEBYSCORE", KEYS[1], 0, cutoff)
local count = redis.call("ZCARD", KEYS[1])
local allowed = 0
local remaining = 0

if count < limit then
  redis.call("ZADD", KEYS[1], now_ms, member)
  redis.call("PEXPIRE", KEYS[1], window_ms + 1000)
  count = count + 1
  allowed = 1
  remaining = limit - count
end

local oldest = redis.call("ZRANGE", KEYS[1], 0, 0, "WITHSCORES")
local reset_at_ms = now_ms + window_ms
if oldest[2] ~= nil then
  reset_at_ms = tonumber(oldest[2]) + window_ms
end

local retry_ms = math.max(0, reset_at_ms - now_ms)
return {allowed, limit, remaining, reset_at_ms, retry_ms, count}
"""


TOKEN_BUCKET_LUA = """
local capacity = tonumber(ARGV[1])
local refill_per_ms = tonumber(ARGV[2])
local requested = tonumber(ARGV[3])
local ttl_ms = tonumber(ARGV[4])

local now = redis.call("TIME")
local now_ms = now[1] * 1000 + math.floor(now[2] / 1000)

local current = redis.call("HMGET", KEYS[1], "tokens", "last_refill_ms")
local tokens = tonumber(current[1])
local last_refill_ms = tonumber(current[2])

if tokens == nil then
  tokens = capacity
end

if last_refill_ms == nil then
  last_refill_ms = now_ms
end

if now_ms > last_refill_ms then
  local elapsed = now_ms - last_refill_ms
  tokens = math.min(capacity, tokens + (elapsed * refill_per_ms))
  last_refill_ms = now_ms
end

local allowed = 0
local remaining = math.floor(tokens)
local retry_ms = 0

if tokens >= requested then
  tokens = tokens - requested
  allowed = 1
  remaining = math.floor(tokens)
else
  retry_ms = math.ceil((requested - tokens) / refill_per_ms)
end

local refill_to_full_ms = math.ceil((capacity - tokens) / refill_per_ms)
local reset_at_ms = now_ms + refill_to_full_ms

redis.call("HMSET", KEYS[1], "tokens", tokens, "last_refill_ms", last_refill_ms)
redis.call("PEXPIRE", KEYS[1], ttl_ms)

return {allowed, capacity, remaining, reset_at_ms, retry_ms, tokens}
"""
