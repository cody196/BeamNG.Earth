-- Keep GPS driving across streamed maps. Vehicle extension hooks run AFTER ai.updateGFX: a new map
-- has already cleared the stock AI route, so setPath restores it without resetting the speed/gearbox
-- controls. Ordinary additions use the stock path-extension API. Only an actual reroute restarts AI.
local M = {}
local active, pending, appliedMap, appliedPath = false, nil, nil, nil
local commandId = 0

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
  for i = 1, #ids - 1 do
    local a, b = ids[i], ids[i + 1]
    local e = graph[a] and graph[a][b]
    if not e or (e.oneWay and e.inNode ~= nil and e.inNode ~= a) then return false end
  end
  return true
end

local function reject()
  active, pending, appliedPath, appliedMap = false, nil, nil, nil
  ai.setMode('stop')
  obj:queueGameEngineLua("require('beamngEarth/gps').onAutodriveRejected(" .. commandId .. ")")
end

function M.setPath(ids, serial, id, speed, aggression, final)
  commandId = id or commandId
  pending = { ids = ids, speed = speed, aggression = aggression or 0.3, final = final }
  active = true
  -- This reads the map mailbox published by map.reset, before the next AI update. Never guess
  -- that a four-second timeout means the vehicle has the graph; validate its actual copy below.
  if serial ~= nil then mapmgr.setMap(serial) end
end

function M.pause()
  active, pending, appliedPath, appliedMap = false, nil, nil, nil
  if ai.mode ~= 'stop' then ai.setMode('stop') end
end

function M.stop()
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
    -- A foreign reset also invalidates the route. GE will send a current, trimmed path on
    -- rejection; an old full list could start behind the car or contain nodes already unloaded.
    if appliedMap and appliedMap ~= data then reject() end
    return
  end
  local nextPath = pending
  pending = nil
  if not valid(nextPath.ids, data) then reject(); return end
  if ai.mode ~= 'manual' or not appliedPath then
    ai.driveUsingPath({ path = nextPath.ids, driveInLane = 'on', avoidCars = 'on',
      routeSpeedMode = nextPath.speed and 'set' or 'legal', routeSpeed = nextPath.speed,
      aggression = nextPath.aggression })
    appliedPath = nextPath.ids
  elseif appliedMap ~= data then
    -- ai.updateGFX discarded currentRoute for the changed map; its controls are still warm.
    ai.setPath(nextPath.ids)
    appliedPath = nextPath.ids
  else
    local suffix = M.extension(appliedPath, nextPath.ids)
    if suffix == nil or (nextPath.final and appliedPath[#appliedPath] ~= nextPath.ids[#nextPath.ids]) then
      ai.driveUsingPath({ path = nextPath.ids, driveInLane = 'on', avoidCars = 'on',
        routeSpeedMode = nextPath.speed and 'set' or 'legal', routeSpeed = nextPath.speed,
        aggression = nextPath.aggression })
      appliedPath = nextPath.ids
    elseif #suffix > 1 then
      ai.setPath(suffix)
      -- Keep the complete route until the next GE update trims it: another request can arrive
      -- before AI consumes this suffix. The extension hook applies at most one request per frame.
      local joined = {}
      for _, node in ipairs(appliedPath) do joined[#joined + 1] = node end
      for i = 2, #suffix do joined[#joined + 1] = suffix[i] end
      appliedPath = joined
    end
  end
  appliedMap = data
end

function M.onReset()
  if active then reject() end
end

return M
