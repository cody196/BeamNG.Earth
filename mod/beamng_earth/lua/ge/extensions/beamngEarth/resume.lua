-- Alternate checkpoints: an interrupted write leaves the previous save intact.
-- Geographic coordinates and true heading survive origin rebases.
local M = {}
M.FILES = { '/settings/beamngEarthResume1.json', '/settings/beamngEarthResume2.json' }
local current, slot, elapsed, loaded = nil, nil, 0, false

-- Check the actual game mode, not just the level name (missions can run in freeroam levels).
function M.singleplayerFreeroam()
  if require('beamngEarth/beammp').inSession() then return false end
  local gs = rawget(_G, 'core_gamestate')
  if not gs or not gs.state or gs.state.state ~= 'freeroam' then return false end
  local fr = rawget(_G, 'freeroam_freeroam')
  if fr and fr.state and fr.state.freeroamActive == false then return false end
  local career = rawget(_G, 'career_career')
  if career and career.isActive and career.isActive() then return false end
  local missions = rawget(_G, 'gameplay_missions_missionManager')
  return not (missions and missions.getForegroundMissionId and missions.getForegroundMissionId())
end

local function finite(v)
  return type(v) == 'number' and v == v and math.abs(v) < math.huge
end

function M.valid(p)
  return type(p) == 'table' and p.version == 1
    and finite(p.sequence) and p.sequence >= 1 and p.sequence % 1 == 0
    and finite(p.lat) and math.abs(p.lat) <= 90
    and finite(p.lon) and math.abs(p.lon) <= 180
    and finite(p.height) and finite(p.heading) and p.heading >= 0 and p.heading < 360
end

local function read(path)
  local fn = rawget(_G, 'jsonReadFile')
  if not fn then return nil end
  local ok, p = pcall(fn, path)
  return ok and M.valid(p) and p or nil
end

function M.load()
  current, slot, elapsed, loaded = nil, nil, 0, true
  for i, path in ipairs(M.FILES) do
    local p = read(path)
    if p and (not current or p.sequence > current.sequence) then current, slot = p, i end
  end
  return current
end

function M.capture(anchor, pos, dir)
  if not anchor or not pos or not dir then return nil end
  if not (finite(pos.x) and finite(pos.y) and finite(pos.z)
    and finite(dir.x) and finite(dir.y)) or dir.x * dir.x + dir.y * dir.y < 1e-6 then return nil end
  local lat, lon, height = anchor:enuToGeodetic(pos.x, pos.y, pos.z)
  local nx, ny = anchor:northAt(pos.x, pos.y)
  local heading = math.deg(math.atan2(dir.x, dir.y) - math.atan2(nx, ny)) % 360
  return { version = 1, sequence = 1, lat = lat, lon = lon, height = height, heading = heading }
end

function M.direction(anchor, x, y, heading)
  local nx, ny = anchor:northAt(x, y)
  local h = math.rad(heading)
  return nx * math.cos(h) + ny * math.sin(h), ny * math.cos(h) - nx * math.sin(h)
end

function M.save(p)
  if not M.valid(p) then return false end
  if not loaded then M.load() end
  local write = rawget(_G, 'jsonWriteFile')
  if not write then return false end
  local out = { version = 1, sequence = (current and current.sequence or 0) + 1,
    lat = p.lat, lon = p.lon, height = p.height, heading = p.heading, savedAt = os.time() }
  local nextSlot = slot == 1 and 2 or 1
  local ok, result = pcall(write, M.FILES[nextSlot], out, true)
  local check = ok and result ~= false and read(M.FILES[nextSlot]) or nil
  if not check or check.sequence ~= out.sequence or math.abs(check.lat - out.lat) > 1e-7
    or math.abs(check.lon - out.lon) > 1e-7 or math.abs(check.height - out.height) > 1e-4
    or math.abs(check.heading - out.heading) > 1e-4 then
    if rawget(_G, 'log') then log('W', 'beamngEarth', 'Position autosave failed; keeping the previous checkpoint') end
    return false
  end
  current, slot = check, nextSlot
  return true
end

-- Invalid/loading poses reset the timer, so a temporary spawn never replaces a good save.
function M.tick(dt, interval, pose, force)
  if not pose then elapsed = 0; return false end
  elapsed = elapsed + math.max(0, dt or 0)
  if not force and elapsed < (interval or 10) then return false end
  elapsed = 0
  return M.save(pose)
end

return M
