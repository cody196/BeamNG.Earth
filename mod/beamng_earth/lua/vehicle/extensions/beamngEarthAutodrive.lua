-- Keep GPS driving across streamed maps. Vehicle extension hooks run AFTER ai.updateGFX: a new map
-- has already cleared the stock AI route, so setPath restores it without resetting the speed/gearbox
-- controls. Ordinary additions use the stock path-extension API. Only an actual reroute restarts AI.
local M = {}
local active, pending, appliedMap, appliedPath = false, nil, nil, nil
local appliedFinal = false
local commandId = 0
M.DEBUG = true
local mapSerial, lastLog = nil, -math.huge

local function debugEvent(event, detail, force)
  if not M.DEBUG or not log then return end
  local now=os.clock()
  if not force and now-lastLog<10 then return end
  lastLog=now
  local p=obj:getPosition()
  local v=obj.getVelocity and obj:getVelocity()
  local speed=v and math.sqrt(v.x*v.x+v.y*v.y) or 0
  log('I','beamngEarthAutodrive',string.format('vehicle_%s command=%d map=%s mode=%s pos=%.1f,%.1f,%.1f speed=%.1f nodes=%d end=%s final=%s %s',
    event,commandId,tostring(mapSerial),tostring(ai.mode),p.x,p.y,p.z or 0,speed,
    appliedPath and #appliedPath or 0,tostring(appliedPath and appliedPath[#appliedPath]),tostring(appliedFinal),detail or ''))
end

local function copy(ids, first)
  local out = {}
  for i = first or 1, #ids do out[#out + 1] = ids[i] end
  return out
end

-- GE keeps the edge under the car for connectivity checks. Stock manual AI instead builds
-- ego.pos -> path[1] -> path[2]: giving it the rear endpoint makes it turn around. Recheck
-- against the vehicle's current position when the command is consumed (it may have moved).
function M.forwardPath(ids, data, pos, dir)
  local positions, radii = data.positions or {}, data.radius or {}
  local best, distance = nil, math.huge
  local heading = math.sqrt(dir.x * dir.x + dir.y * dir.y)
  if heading < 0.1 then return nil end
  for i = 1, #ids - 1 do
    local a, b = positions[ids[i]], positions[ids[i + 1]]
    if a and b then
      local dx, dy = b.x - a.x, b.y - a.y
      local length = math.sqrt(dx * dx + dy * dy)
      if length > 0.1 and (dx * dir.x + dy * dir.y) / (length * heading) > 0.5 then
        local t = ((pos.x - a.x) * dx + (pos.y - a.y) * dy) / (length * length)
        local f = math.max(0, math.min(1, t))
        local x, y = a.x + f * dx - pos.x, a.y + f * dy - pos.y
        local d = x * x + y * y
        local radius = math.max(8, math.min(16, math.max(radii[ids[i]] or 0, radii[ids[i+1]] or 0) + 2))
        local sameDeck = not (pos.z and a.z and b.z) or math.abs(pos.z - (a.z + f * (b.z - a.z))) <= 5
        if sameDeck and t < 1 and d <= radius * radius and d < distance then
          best, distance = t < 0 and i or i + 1, d
        end
      end
    end
  end
  return best and copy(ids, best) or nil
end

-- Pure: the suffix to append, {} when already covered, nil when the route actually changes.
function M.extension(old, new)
  if not old or not new or #new < 2 then return nil end
  for first = 1, #old do
    if old[first] == new[1] then
      local count = math.min(#old - first + 1, #new)
      local same = true
      for j = 1, count do if old[first + j - 1] ~= new[j] then same = false; break end end
      if same then
        if count == #new then return {} end
        local out = { old[#old] }
        for j = count + 1, #new do out[#out + 1] = new[j] end
        return out
      end
    end
  end
end

local function valid(ids, data)
  local graph = data and data.graph
  if not graph or not ids or #ids < 2 then return false end
  local seen = {}
  for _, id in ipairs(ids) do
    if seen[id] then return false end
    seen[id] = true
  end
  for i = 1, #ids - 1 do
    local a, b = ids[i], ids[i + 1]
    local e = graph[a] and graph[a][b]
    if not e or (e.oneWay and e.inNode ~= nil and e.inNode ~= a) then return false end
  end
  return true
end

local function reject(reason)
  reason = reason or 'map changed'
  debugEvent('reject',reason,true)
  active, pending, appliedPath, appliedMap = false, nil, nil, nil
  ai.setMode('stop')
  if log then log('W', 'beamngEarthAutodrive', 'Path rejected: ' .. (reason or 'map changed')) end
  obj:queueGameEngineLua("require('beamngEarth/gps').onAutodriveRejected(" .. commandId .. "," .. string.format('%q',reason) .. ")")
end

function M.setPath(ids, serial, id, speed, aggression, final)
  commandId = id or commandId
  mapSerial = serial
  pending = { ids = copy(ids), speed = speed, aggression = aggression or 0.3, final = final }
  active = true
  -- This reads the map mailbox published by map.reset, before the next AI update. Never guess
  -- that a four-second timeout means the vehicle has the graph; validate its actual copy below.
  if serial ~= nil then mapmgr.setMap(serial) end
end

function M.pause()
  if active or ai.mode~='stop' then debugEvent('hold','GE requested a hold',true) end
  active, pending, appliedPath, appliedMap = false, nil, nil, nil
  if ai.mode ~= 'stop' then ai.setMode('stop') end
end

function M.stop()
  debugEvent('disabled','GE released control',true)
  active, pending, appliedPath, appliedMap = false, nil, nil, nil
  ai.setMode('disabled')
  input.event('throttle', 0, 1)
  input.event('brake', 0, 1)
  input.event('steering', 0, 1)
  input.event('parkingbrake', 0, 1)
end

function M.updateGFX()
  if not active then return end
  local data = mapmgr.mapData
  if not pending then
    debugEvent('heartbeat')
    -- A foreign reset also invalidates the route. GE will send a current, trimmed path on
    -- rejection; an old full list could start behind the car or contain nodes already unloaded.
    if appliedMap and appliedMap ~= data then reject(); return end
    if appliedPath and not appliedFinal then
      local pos, dir = obj:getPosition(), obj:getDirectionVector()
      local remaining = M.forwardPath(appliedPath, data, pos, dir)
      local length, previous = 0, pos
      if remaining then
        for _, id in ipairs(remaining) do
          local p = data.positions[id]
          length = length + math.sqrt((p.x-previous.x)^2+(p.y-previous.y)^2)
          previous = p
        end
      else
        local p = data.positions[appliedPath[#appliedPath]]
        length = p and math.sqrt((p.x-pos.x)^2+(p.y-pos.y)^2) or math.huge
      end
      local v = obj.getVelocity and obj:getVelocity()
      local speed = v and math.sqrt(v.x*v.x+v.y*v.y) or 0
      -- Stop *before* stock AI treats this streamed endpoint as the destination and emits
      -- 'Route done'. GE retains the GPS destination and resumes when more road matches it.
      if length < math.max(25, speed*1.5) then
        reject(string.format('waiting for more road on the GPS route (remaining=%.1f speed=%.1f)',length,speed))
      end
    end
    return
  end
  local nextPath = pending
  local action = 'keep'
  pending = nil
  if not valid(nextPath.ids, data) then reject('missing, reversed or repeated road edge'); return end
  local function forward()
    local ids = M.forwardPath(nextPath.ids, data, obj:getPosition(), obj:getDirectionVector())
    if not ids then reject('no forward route on the road beneath the car') end
    return ids
  end
  if ai.mode ~= 'manual' or not appliedPath then
    action = 'start'
    local ids = forward()
    if not ids then return end
    ai.driveUsingPath({ path = ids, driveInLane = 'on', avoidCars = 'on',
      routeSpeedMode = nextPath.speed and 'set' or 'legal', routeSpeed = nextPath.speed,
      aggression = nextPath.aggression })
    appliedPath = nextPath.ids
  elseif appliedMap ~= data then
    action = 'restore_map'
    -- ai.updateGFX discarded currentRoute for the changed map; its controls are still warm.
    local ids = forward()
    if not ids then return end
    ai.setPath(ids)
    appliedPath = nextPath.ids
  else
    local suffix = M.extension(appliedPath, nextPath.ids)
    if suffix == nil or (nextPath.final and appliedPath[#appliedPath] ~= nextPath.ids[#nextPath.ids]) then
      action = 'replace_route'
      local ids = forward()
      if not ids then return end
      ai.driveUsingPath({ path = ids, driveInLane = 'on', avoidCars = 'on',
        routeSpeedMode = nextPath.speed and 'set' or 'legal', routeSpeed = nextPath.speed,
        aggression = nextPath.aggression })
      appliedPath = nextPath.ids
    elseif #suffix > 1 then
      action = 'extend'
      ai.setPath(suffix)
      -- Keep a separate copy: stock AI retains and mutates the table passed to driveUsingPath
      -- and setPath as it extends/prunes its route.
      local joined = {}
      for _, node in ipairs(appliedPath) do joined[#joined + 1] = node end
      for i = 2, #suffix do joined[#joined + 1] = suffix[i] end
      appliedPath = joined
    end
  end
  appliedMap = data
  appliedFinal = nextPath.final == true and appliedPath[#appliedPath] == nextPath.ids[#nextPath.ids]
  debugEvent(action,nil,action=='start' or action=='replace_route' or action=='restore_map')
end

function M.onReset()
  if active then reject() end
end

return M
