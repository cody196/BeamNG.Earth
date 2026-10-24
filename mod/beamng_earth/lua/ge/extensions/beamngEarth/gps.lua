-- GPS to a place picked on the world map (the user, 2026-10-14: "get the game's GPS system to work with this", then
-- "have the server plan out the whole route so it can work with much longer distances"). The destination is kept
-- as latitude / longitude (it outlives anchors and rebases). The server plans the whole road route (routing.py:
-- OSRM on OpenStreetMap); the map draws it, and the game's own route arrows (core_groundMarkers.setPath: arrows on
-- the road, the navigation app, the minimap's line) follow it on our AI road graph (navgraph.lua), which only
-- covers ~1 km around the player: the arrows go to the farthest point of the planned route ahead (up to LOOKAHEAD_M)
-- that the local graph reaches, set again as the player advances or the graph moves on. Leaving the route by more
-- than OFF_ROUTE_M plans it again from where the player is. Without a planned route (offline): steered toward the
-- destination through the graph node nearest it. Within ARRIVE_M: arrived, cleared.
local M = {}
local routepath = require('beamngEarth/routepath')

M.CHECK_S = 1.0
M.ARRIVE_M = 40         -- this close (horizontally): arrived
M.FINAL_M = 60          -- a graph node this close to the destination: the arrows end at the destination itself
M.ON_GRAPH_M = 25       -- a route point this close to a graph node is reachable on the local graph
M.LOOKAHEAD_M = 1500    -- how far along the route the arrows may reach
M.SAMPLE_M = 40         -- route points tried for the arrows' target at least this far apart
M.RETARGET_M = 150      -- the arrows' target is moved on in steps of this much route
M.VIA_M = 250           -- the arrows' path is pinned to the route by a waypoint this often (else the stock planner takes
                        -- its own shortest way to the target: Fells Point 2026-10-14, a loop round a block)
M.OFF_ROUTE_M = 120     -- farther from the route: planned again ...
M.REROUTE_S = 20        -- ... at most this often
-- Past the local graph's edge the arrows go on along the planned route itself (the user, 2026-10-14, a Cannonball run:
-- "the in game arrows would keep ending and I'd have to wait a while before they continue": the graph only covers the
-- terrain block, which lags a fast car): the stock planner's path gets the route's next TAIL_M appended, a point every
-- TAIL_STEP_M on the ground below it.
M.TAIL_M = 2000
M.TAIL_STEP_M = 25
-- Autodrive (the user, 2026-10-14: "get the car to auto drive along a gps route"; also a repeatable drive for the
-- performance recordings): the player's car's own AI (vehicle ai.driveUsingPath) drives the graph part of the arrows'
-- path, in its lane, minding traffic, at the legal speed. The vehicle extension restores routes after map changes
-- and appends newly loaded road without resetting the AI's speed/gearbox controls.
M.AUTO_STALL_S = 45    -- allow traffic lights/queues before attempting recovery
M.AUTO_LOOP_S = 20     -- moving this long without advancing along the route: recover, even above walking speed
M.AUTO_PROGRESS_M = 10
M.AUTO_LOOP_TRAVEL_M = 60
M.AUTO_RECOVERY_LIMIT = 3
M.AUTO_AGGRESSION = 0.3
M.AUTO_RESUME_M = 60  -- enough usable road to restart, including a short newly loaded extension
M.AUTO_HOLD_S = 8     -- a route-loading hold gets a fresh graph before waiting for the traffic watchdog
M.DEBUG = true        -- state changes and a ten-second heartbeat in beamng.log; TRACE adds every path
-- Safety: the AI brakes to a stop while the world server is away (no new ground or roads: an autodrive left on through
-- server restarts drove off the loaded world and wrecked the car, 2026-10-14) and goes on when it is back; a car
-- damaged this much ends the autodrive.
M.AUTO_DAMAGE = 20000

local dest = nil        -- { lat, lon, name }
local route = nil       -- { points = {{lat, lon}...}, dist, dur, version } | false (no route: steering) | nil (none yet)
local routeVersion = 0
local routeError = nil
local pendingId, nextId = nil, 0
local lastRequest = -math.huge
local enu = nil         -- { anchor, x = {}, y = {}, cum = {} } of the route in the current anchor's frame
local progress = 1      -- index of the route segment the player is on
local routedTo = nil    -- the node id (or 'final') the current arrows go to
local lastCheck = -math.huge
local info = nil        -- { dist, bearing, remaining, eta } at the last check
local auto = false      -- autodrive on
local autoPath = nil    -- the node ids last given to the AI
local autoSerial = nil  -- the graph (navgraph applies) they were taken from
local autoFinal = false -- only the true GPS destination, never a temporary streamed endpoint
local stillSince = nil
local paused = false    -- the AI holds the car (world server away)
local vehGraph = {}     -- vehicle id -> the game's map buildSerial when its mapmgr last took the graph
local targetS = nil     -- the route distance of the arrows' target
local commandId = 0
local waiting = nil     -- 'route', 'graph', 'server' or nil
local recovering = false
local watch = nil       -- route progress and distance travelled, rather than speed alone
local recoveries = 0
local holdSince, matchInfo, lastReject = nil, nil, nil
local lastHeartbeat, lastRefresh = -math.huge, -math.huge
local restartRoute, blockedOnStop = false, false
local roadHint = nil   -- preserve the known carriageway while stopped at a temporary endpoint

local function debugEvent(event, detail)
  if M.DEBUG and log then log('I', 'beamngEarthAutodrive', event .. ' ' .. (detail or '')) end
end

-- Pure: the id and position {x, y, z} of the node in `nodes` (map.getMap().nodes: id -> { pos = {x, y, z} })
-- nearest (tx, ty), and its distance; nil when there are none.
function M.pickNode(nodes, tx, ty)
  local best, bd, bp = nil, math.huge, nil
  for id, n in pairs(nodes or {}) do
    local p = n.pos
    if p then
      local dx, dy = p.x - tx, p.y - ty
      local d = dx * dx + dy * dy
      if d < bd then best, bd, bp = id, d, p end
    end
  end
  if not best then return nil end
  return best, bp, math.sqrt(bd)
end

-- Pure: the segments {ax, ay, bx, by, z} of the graph's edges (each once).
function M.edgeSegments(nodes)
  local segs, seen = {}, {}
  for id, n in pairs(nodes or {}) do
    local a = n.pos
    for other, _ in pairs(n.links or {}) do
      local key = tostring(id) < tostring(other) and (tostring(id) .. '|' .. tostring(other)) or (tostring(other) .. '|' .. tostring(id))
      local o = nodes[other]
      if a and o and o.pos and not seen[key] then
        seen[key] = true
        segs[#segs + 1] = { a.x, a.y, o.pos.x, o.pos.y, (a.z + o.pos.z) / 2 }
      end
    end
  end
  return segs
end

-- Pure: the distance from (px, py) to the nearest segment of segs, and that segment's z.
function M.nearestEdge(segs, px, py)
  local bd, bz = math.huge, 0
  for _, s in ipairs(segs) do
    local ax, ay, bx, by = s[1], s[2], s[3], s[4]
    local dx, dy = bx - ax, by - ay
    local L2 = dx * dx + dy * dy
    local t = L2 > 0 and math.max(0, math.min(1, ((px - ax) * dx + (py - ay) * dy) / L2)) or 0
    local qx, qy = ax + t * dx - px, ay + t * dy - py
    local d = qx * qx + qy * qy
    if d < bd then bd, bz = d, s[5] end
  end
  return math.sqrt(bd), bz
end

-- Pure: the compass bearing (deg, 0 = north) from (x0, y0) to (x1, y1) in the east / north frame.
function M.bearing(x0, y0, x1, y1)
  return (math.deg(math.atan2(x1 - x0, y1 - y0)) + 360) % 360
end

-- Pure: the segment of polyline (xs, ys) nearest (px, py), searched over indices [i0, i1): its index i (segment
-- i -> i + 1), the fraction t along it and the distance.
function M.nearestSegment(xs, ys, px, py, i0, i1)
  local bi, bt, bd = 1, 0, math.huge
  for i = math.max(1, i0 or 1), math.min(#xs - 1, (i1 or #xs) - 1) do
    local ax, ay, bx, by = xs[i], ys[i], xs[i + 1], ys[i + 1]
    local dx, dy = bx - ax, by - ay
    local L2 = dx * dx + dy * dy
    local t = L2 > 0 and math.max(0, math.min(1, ((px - ax) * dx + (py - ay) * dy) / L2)) or 0
    local qx, qy = ax + t * dx - px, ay + t * dy - py
    local d = qx * qx + qy * qy
    if d < bd then bi, bt, bd = i, t, d end
  end
  return bi, bt, math.sqrt(bd)
end

local function clearArrows()
  local gm = rawget(_G, 'core_groundMarkers')
  if gm and gm.setPath then pcall(gm.setPath, nil) end
  routedTo = nil
end

local function core() return rawget(_G, 'beamngEarth_core') end

-- Pure: the compass bearing (degrees, 0 north, clockwise) of a direction (x east, y north), or nil when it is ~vertical.
function M.compass(dx, dy)
  if not dx or not dy or dx * dx + dy * dy < 0.01 then return nil end
  return math.floor((math.deg(math.atan2(dx, dy)) + 360) % 360 + 0.5) % 360
end

local function playerVeh()
  local get = rawget(_G, 'getPlayerVehicle')
  return get and get(0) or nil
end

local function requestRoute(player)
  local c = core()
  if not c or not c.requestRoute or not dest or not player or not player.lat then return end
  nextId = nextId + 1
  -- the car's heading: the route starts on the carriageway it drives on, the way it drives (without it OSRM began
  -- divided boulevards on the other carriageway, the car turned round to follow, left the route and was routed
  -- back again, over and over: Timisoara 2026-10-15)
  local veh = playerVeh()
  local d = veh and veh.getDirectionVector and veh:getDirectionVector()
  local b = d and M.compass(d.x, d.y)
  if c.requestRoute(nextId, player.lat, player.lon, dest.lat, dest.lon, b) then
    pendingId, lastRequest = nextId, os.clock()
    debugEvent('route_request', string.format('id=%d from=%.6f,%.6f to=%.6f,%.6f bearing=%s',
      nextId, player.lat, player.lon, dest.lat, dest.lon, tostring(b)))
    return true
  end
end

function M.setDestination(lat, lon, name)
  lat, lon = tonumber(lat), tonumber(lon)
  if not lat or not lon then return false end
  dest = { lat = lat, lon = lon, name = name }
  route, routeError, pendingId, enu, progress, info = nil, nil, nil, nil, 1, nil
  routedTo, lastCheck, lastRequest, targetS = nil, -math.huge, -math.huge, nil
  watch, recoveries, recovering = nil, 0, false
  holdSince, matchInfo, lastReject, roadHint, restartRoute, blockedOnStop = nil, nil, nil, nil, false, false
  debugEvent('destination', string.format('lat=%.6f lon=%.6f',lat,lon))
  clearArrows()
  if auto then
    autoPath, autoSerial = nil, nil
    local veh = playerVeh()
    if veh then veh:queueLuaCommand(M.pauseCommand()) end
  end
  return true
end

function M.clear()
  if auto then M.setAutodrive(false) end
  dest, route, routeError, pendingId, enu, info = nil, nil, nil, nil, nil, nil
  clearArrows()
end

function M.status()
  if not dest then return nil end
  return { lat = dest.lat, lon = dest.lon, name = dest.name, dist = info and info.dist, bearing = info and info.bearing,
           remaining = info and info.remaining, eta = info and info.eta, routeVersion = route and route.version or 0,
           progress = progress, planning = pendingId ~= nil, routeError = routeError, pendingId = pendingId,
           autodrive = auto, autoNodes = autoPath and #autoPath or nil, off = info and info.off, arrows = routedTo,
           autoWaiting = waiting, autoRecoveries = recoveries, autoMatch = matchInfo,
           autoHoldSeconds = holdSince and math.max(0,os.clock()-holdSince), autoLastReject = lastReject }
end

-- The planned route for the map: { version, points = {{lat, lon}...}, dist, dur } or nil.
function M.route()
  if not route then return nil end
  return { version = route.version, points = route.points, dist = route.dist, dur = route.dur }
end

local function toEnu(anchor)
  if enu and enu.anchor == anchor then return enu end
  local xs, ys, cum = {}, {}, { 0 }
  for i, p in ipairs(route.points) do
    xs[i], ys[i] = anchor:geodeticToEnu(p[1], p[2], 0)
    if i > 1 then cum[i] = cum[i - 1] + math.sqrt((xs[i] - xs[i - 1]) ^ 2 + (ys[i] - ys[i - 1]) ^ 2) end
  end
  enu = { anchor = anchor, x = xs, y = ys, cum = cum }
  progress = 1
  return enu
end

-- The arrows' target on the planned route: the farthest sampled route point within LOOKAHEAD_M that lies on the local
-- graph (within ON_GRAPH_M of one of its edges); the stock route planner snaps it to the road.
-- the graph's applies count: the game's node table stays the same table when a new graph goes in
local function graphSerial()
  local ok, ng = pcall(require, 'beamngEarth/navgraph')
  return ok and ng.applies and ng.applies() or 0
end

local segCache = { nodes = nil, serial = nil, segs = {} }
local function routeTarget(e, nodes, i, t)
  local serial = graphSerial()
  if segCache.nodes ~= nodes or segCache.serial ~= serial then
    segCache = { nodes = nodes, serial = serial, segs = M.edgeSegments(nodes) }
  end
  local segs = segCache.segs
  local n = #e.x
  local s0 = e.cum[i] + t * (e.cum[i + 1] - e.cum[i])
  local best = nil
  local via, lastVia, misses = {}, s0, 0
  -- sample along the route every SAMPLE_M from the player's spot (the simplified route's vertices can be far apart)
  local s = s0
  local k = i
  while s - s0 <= M.LOOKAHEAD_M do
    s = math.min(s + M.SAMPLE_M, e.cum[n])
    while k < n - 1 and e.cum[k + 1] < s do k = k + 1 end
    local seg = e.cum[k + 1] - e.cum[k]
    local f = seg > 0 and (s - e.cum[k]) / seg or 0
    local x = e.x[k] + f * (e.x[k + 1] - e.x[k])
    local y = e.y[k] + f * (e.y[k + 1] - e.y[k])
    local d, z = M.nearestEdge(segs, x, y)
    local final = s >= e.cum[n] - 1e-6
    if d <= M.ON_GRAPH_M then
      best = { s = s, x = x, y = y, z = z, final = final }
      misses = 0
      if s - lastVia >= M.VIA_M then via[#via + 1] = best; lastVia = s end
    elseif best then
      misses = misses + 1                -- the route left the graph (a short gap, a junction's offset: not yet)
      if misses >= 3 then break end
    end
    if final then break end
  end
  if best then
    if via[#via] == best then via[#via] = nil end
    best.via = via
  end
  return best
end

-- Pure: points {x, y} every step along polyline e (x, y, cum) from distance s0 to s1 (both ends included).
function M.routeSlice(e, s0, s1, step)
  local n = #e.x
  s1 = math.min(s1, e.cum[n])
  local out, k, s = {}, 1, s0
  while true do
    while k < n - 1 and e.cum[k + 1] < s do k = k + 1 end
    local seg = e.cum[k + 1] - e.cum[k]
    local f = seg > 0 and math.max(0, math.min(1, (s - e.cum[k]) / seg)) or 0
    out[#out + 1] = { e.x[k] + f * (e.x[k + 1] - e.x[k]), e.y[k] + f * (e.y[k + 1] - e.y[k]) }
    if s >= s1 then break end
    s = math.min(s + step, s1)
  end
  return out
end

-- The planner's path (core_groundMarkers.routePlanner.path, {pos, distToTarget, wp, fixed}) goes on along the
-- route from s0: no node of it fixed (a fixed node behind the car would make the planner re-plan back to it).
local function appendTail(gm, e, s0, z0)
  local rp = gm.routePlanner
  if not rp or type(rp.path) ~= 'table' or #rp.path == 0 or not rp.calcDistance then return end
  local ray = rawget(_G, 'castRayStatic')
  local z = z0
  local pts = M.routeSlice(e, s0, s0 + M.TAIL_M, M.TAIL_STEP_M)
  for _, wp in ipairs(rp.path) do wp.fixed = nil end
  for j = 2, #pts do
    local x, y = pts[j][1], pts[j][2]
    if ray then
      local ok, d = pcall(ray, vec3(x, y, z + 60), vec3(0, 0, -1), 200)
      if ok and d and d < 200 then z = z + 60 - d end
    end
    rp.path[#rp.path + 1] = { pos = vec3(x, y, z) }
  end
  rp:calcDistance()
end

-- Pure: the graph node ids of a planner path ({wp = id | nil}...): its graph stretch, ids in order, repeats dropped.
function M.pathNodes(path)
  local out, seen = {}, {}
  for _, p in ipairs(path or {}) do
    if p.wp ~= nil then
      -- Independent point-to-point legs can overlap around an intermediate waypoint.
      -- Erase the closed detour at the shared node, preserving the connected continuation.
      local previous = seen[p.wp]
      if previous then
        for i = #out, previous + 1, -1 do seen[out[i]], out[i] = nil, nil end
      else
        out[#out + 1], seen[p.wp] = p.wp, #out + 1
      end
    end
  end
  return out
end

-- Tests only (tools/autodrive_perf.py --ai-mph): drive at this speed (m/s) instead of the legal one.
M.speedOverride = nil

-- Pure: the vehicle Lua that sets its AI on a path of node ids (nil: off).
function M.aiCommand(ids, aggression)
  if not ids then return 'ai.setMode("disabled")' end
  local q = {}
  for i, id in ipairs(ids) do q[i] = string.format('%q', tostring(id)) end
  local speed = tonumber(M.speedOverride)
  local mode = speed and string.format('routeSpeedMode = "set", routeSpeed = %.2f, ', speed) or 'routeSpeedMode = "legal", '
  return 'ai.driveUsingPath({path = {' .. table.concat(q, ',') .. '}, driveInLane = "on", ' .. mode
    .. 'avoidCars = "on", aggression = ' .. string.format('%.2f', aggression or M.AUTO_AGGRESSION) .. '})'
end

local function currentMapSerial()
  local m = rawget(_G, 'map')
  local gm = m and m.getMap and m.getMap()
  return gm and gm.buildSerial
end

function M.pauseCommand()
  return 'if extensions.beamngEarthAutodrive then extensions.beamngEarthAutodrive.pause() else ai.setMode("stop") end'
end

function M.autoCommand(ids, final)
  if not ids then
    return 'if extensions.beamngEarthAutodrive then extensions.beamngEarthAutodrive.stop() else ai.setMode("disabled") end'
  end
  local q = {}
  for i, id in ipairs(ids) do q[i] = string.format('%q', tostring(id)) end
  commandId = commandId + 1
  return 'extensions.load("beamngEarthAutodrive") extensions.beamngEarthAutodrive.setPath({' .. table.concat(q, ',')
    .. '},' .. tostring(currentMapSerial()) .. ',' .. commandId .. ',' .. tostring(tonumber(M.speedOverride))
    .. ',' .. tostring(M.AUTO_AGGRESSION) .. ',' .. tostring(final == true) .. ')'
end

function M.onAutodriveRejected(id, reason)
  if not auto or id ~= commandId then return end
  roadHint = autoPath or roadHint
  lastReject, holdSince = reason or 'vehicle graph rejected', holdSince or os.clock()
  debugEvent('vehicle_reject', 'command=' .. id .. ' reason=' .. lastReject)
  autoPath, autoSerial, routedTo, waiting = nil, nil, nil, 'graph'
  lastCheck = -math.huge
end

-- Pure: the edge data between nodes a and b, or nil. The game keeps each edge on one of its nodes only once a
-- graph is loaded (map.lua convertToSingleSided): a path's step read as no edge half the time, and every rebuild
-- of the graph cut the AI's path to a node behind the car (Lauterbrunnen 2026-10-15).
function M.edge(nodes, a, b)
  local na, nb = nodes[a], nodes[b]
  if not (na and nb) then return nil end
  return (na.links and na.links[b]) or (nb.links and nb.links[a]) or nil
end

-- Pure: may the edge between a and b be driven from a to b (a one-way edge runs from its inNode)?
local function drivable(e, a)
  return not (type(e) == 'table' and e.oneWay and e.inNode ~= nil and e.inNode ~= a)
end

-- Pure: the forward road edge under the car, within 8 m (or its wider lane radius), on the same deck.
function M.edgeUnder(nodes, px, py, hx, hy, pz)
  local best, bd = nil, math.huge
  local nearest, nearestD, selected = nil, math.huge, nil
  local function try(from, to, e)
    local a, b = nodes[from] and nodes[from].pos, nodes[to] and nodes[to].pos
    if not (a and b) or not drivable(e, from) then return end
    local dx, dy = b.x - a.x, b.y - a.y
    local L = math.sqrt(dx * dx + dy * dy)
    if L > 0.1 and (dx * hx + dy * hy) / L > 0.5 then
      local t = math.max(0, math.min(1, ((px - a.x) * dx + (py - a.y) * dy) / (L * L)))
      local qx, qy = a.x + t * dx - px, a.y + t * dy - py
      local d = math.sqrt(qx * qx + qy * qy)
      local radius = math.max(nodes[from].radius or 0, nodes[to].radius or 0)
      local width = math.max(8, math.min(16, radius + 2))
      local dz = pz and a.z and b.z and pz-(a.z+t*(b.z-a.z)) or 0
      local reason = math.abs(dz)>5 and 'height' or d>=width and 'lateral' or 'ok'
      local diag = {from=from,to=to,lateral=d,heightError=dz,width=width,reason=reason}
      if d<nearestD then nearest,nearestD=diag,d end
      -- Parallel roads on different decks can share XY at an interchange.
      if reason=='ok' and d < bd then best, bd, selected = { from, to }, d, diag end
    end
  end
  for id, n in pairs(nodes or {}) do
    for other, e in pairs(n.links or {}) do
      try(id, other, e)
      try(other, id, e)
    end
  end
  if best then return best[1], best[2], selected end
  return nil,nil,nearest
end

function M.edgeOnPath(ids, nodes, p, d)
  local own = {}
  for _, id in ipairs(ids or {}) do
    if nodes[id] then own[id]={pos=nodes[id].pos,radius=nodes[id].radius,links={}} end
  end
  for i=1,#(ids or {})-1 do
    local a,b=ids[i],ids[i+1]
    if own[a] and own[b] then own[a].links[b]=M.edge(nodes,a,b) end
  end
  return M.edgeUnder(own,p.x,p.y,d.x,d.y,p.z)
end

function M.startPath(ids, nodes, p, d)
  local hl = math.sqrt(d.x * d.x + d.y * d.y)
  if hl <= 0.1 then return {} end
  -- Capture both results: a non-final function argument only returns its first value in Lua.
  local a, b = M.edgeOnPath(ids, nodes, p, {x=d.x/hl,y=d.y/hl})
  if not a then a, b = M.edgeUnder(nodes, p.x, p.y, d.x / hl, d.y / hl, p.z) end
  if not a then return {} end
  return M.joinStart(ids, a, b, nodes)
end

-- Pure: the connected route including the edge (a -> b) under the car. Keep this rear support
-- node for graph validation; the vehicle bridge removes passed nodes from actual AI targets.
-- The forward endpoint b must remain so a turn just ahead is not cut across.
function M.joinStart(ids, a, b, nodes)
  if not a or #ids == 0 then return ids end
  if not b then return {} end
  -- Drop graph points already passed, including a planner's detour back to an earlier node.
  for i = 1, #ids - 1 do
    if ids[i] == a and ids[i + 1] == b then
      local out = {}
      for j = i, #ids do out[#out + 1] = ids[j] end
      return out
    end
  end
  local out = {}
  if ids[1] == b then
    out[1] = a
  else
    local e = nodes and M.edge(nodes, b, ids[1])
    -- A path which cannot continue from the car's forward edge must be replanned, not chased backwards.
    if not e or not drivable(e, b) then return {} end
    out[1], out[2] = a, b
  end
  for _, id in ipairs(ids) do out[#out + 1] = id end
  return out
end

-- (debug) the AI's new paths: M.TRACE = true logs each with the car's position and its first nodes'
function M.trace(kind, ids, nodes, p)
  if not M.TRACE then return end
  local parts = {}
  for i = 1, math.min(5, #ids) do
    local n = nodes and nodes[ids[i]]
    parts[i] = n and string.format('%s(%.0f,%.0f)', tostring(ids[i]), n.pos.x, n.pos.y) or tostring(ids[i]) .. '(?)'
  end
  log('I', 'beamngEarth', string.format('gps %s at (%.0f,%.0f) t=%.1f: %d nodes %s', kind, p.x, p.y, os.clock(), #ids,
    table.concat(parts, ' ')))
end

-- Map receipt diagnostics. Path safety is enforced against the vehicle's actual graph by its bridge,
-- rather than trusting the GE serial observed when a delayed receipt hook arrives.
function M.onVehicleMapmgrUpdate(id)
  local m = rawget(_G, 'map')
  local gm = m and m.getMap and m.getMap()
  if id then vehGraph[id] = gm and gm.buildSerial end
end

function M.vehicleHasGraph(veh)
  local m = rawget(_G, 'map')
  local gm = m and m.getMap and m.getMap()
  local serial = gm and gm.buildSerial
  if serial == nil or not (veh and veh.getId) then return true end
  return vehGraph[veh:getId()] == serial
end

local function holdRoute(veh, reason)
  if waiting ~= reason or autoPath then
    debugEvent('hold', 'reason=' .. reason .. ' graph=' .. tostring(graphSerial()))
    veh:queueLuaCommand(M.pauseCommand())
  end
  roadHint, holdSince = autoPath or roadHint, holdSince or os.clock()
  autoPath, autoSerial, waiting = nil, nil, reason
end

local function driveRoutePath(result, nodes)
  local veh = playerVeh()
  if not veh or recovering or paused then return end
  local ids = result and result.ids or {}
  -- Validate once more before handing off; streamed graph changes must not leave a missing edge.
  local valid = M.validFrom(ids, 1, { nodes })
  if #valid < #ids then
    ids, routedTo = valid, nil
    M.pathCuts = (M.pathCuts or 0) + 1
  end
  if #ids < 2 then
    -- A transient empty arrows path must not replace a usable driving route or start roaming.
    local old = autoPath and M.startPath(autoPath, nodes, veh:getPosition(), veh:getDirectionVector()) or {}
    old = M.validFrom(old, 1, { nodes })
    if #old < 2 then holdRoute(veh, 'route') end
    routedTo = nil
    return
  end
  local final = result and result.final and #valid == #result.ids or false
  local v = veh.getVelocity and veh:getVelocity()
  local speed = v and math.sqrt(v.x*v.x+v.y*v.y) or 0
  -- Match the vehicle's endpoint guard with extra room. The old fixed 120 m
  -- minimum could hold forever when a valid streamed extension was shorter.
  local resumeLength = math.max(M.AUTO_RESUME_M, speed*1.5+20)
  if not autoPath and not final and (not result or result.length < resumeLength) then
    holdRoute(veh, 'route')
    return
  end
  if autoPath and not final then
    local old = M.validFrom(M.startPath(autoPath, nodes, veh:getPosition(), veh:getDirectionVector()), 1, { nodes })
    local same = #old > #ids
    for i = 1, #ids do if old[i] ~= ids[i] then same = false; break end end
    if same then ids = old end -- a momentarily shorter local target is not a new destination
  end
  veh:queueLuaCommand(M.autoCommand(ids, final))
  if waiting then debugEvent('resume', string.format('graph=%s nodes=%d length=%.1f final=%s',
    tostring(graphSerial()),#ids,result.length,tostring(final))) end
  M.trace('path', ids, nodes, veh:getPosition())
  autoPath, autoSerial, autoFinal, waiting = ids, graphSerial(), final, nil
  roadHint, holdSince = ids, nil
end

local matchCache = {}
local function matchedRoute(e, nodes, here)
  local veh = playerVeh()
  if not veh or not nodes then return nil end
  local p, d = veh:getPosition(), veh:getDirectionVector()
  local a, b, roadDiag
  if autoPath or roadHint then
    -- At a split, keep the known road under the car instead of snapping to an adjacent ramp.
    a,b,roadDiag=M.edgeOnPath(autoPath or roadHint,nodes,p,d)
  end
  if not a then a,b,roadDiag=M.edgeUnder(nodes,p.x,p.y,d.x,d.y,p.z) end
  local serial=graphSerial()
  if matchCache.nodes~=nodes or matchCache.serial~=serial then
    matchCache={nodes=nodes,serial=serial,adj=routepath.graph(nodes)}
  end
  local result, diag = routepath.plan(nodes,matchCache.adj,e,here,M.LOOKAHEAD_M,a,b,p)
  matchInfo = diag
  if matchInfo then matchInfo.road = roadDiag end
  return result
end

-- Pure: the index k of the path edge (ids[k] -> ids[k+1]) nearest (px, py) in nodes (positions), or nil.
function M.pathIndexAt(ids, nodes, px, py)
  local best, bd = nil, math.huge
  for k = 1, #ids - 1 do
    local a, b = nodes[ids[k]], nodes[ids[k + 1]]
    a, b = a and a.pos, b and b.pos
    if a and b then
      local dx, dy = b.x - a.x, b.y - a.y
      local L2 = dx * dx + dy * dy
      local t = L2 > 0 and math.max(0, math.min(1, ((px - a.x) * dx + (py - a.y) * dy) / L2)) or 0
      local qx, qy = a.x + t * dx - px, a.y + t * dy - py
      local d = qx * qx + qy * qy
      if d < bd then best, bd = k, d end
    end
  end
  return best
end

-- Pure: ids[k ..] as far as each step is an edge in every one of the graphs (lists of nodes tables).
function M.validFrom(ids, k, graphs)
  if not ids or not ids[k] then return {} end
  local out = { ids[k] }
  for i = k, #ids - 1 do
    for _, nodes in ipairs(graphs) do
      local e = M.edge(nodes, ids[i], ids[i + 1])
      if not e or not drivable(e, ids[i]) then return out end
    end
    out[#out + 1] = ids[i + 1]
  end
  return out
end

-- The road graph is about to be applied anew (navgraph.lua, before map.reset): what the AI's path needs to stay valid.
-- The stock AI keeps its path's node ids across the map change and crashed on a step that was no longer an edge
-- ('edgeData' nil in ai.lua planAhead: the vehicle's Lua disabled, the car stopped for good; I-70 2026-10-15).
function M.beforeGraph(oldNodes)
  if not auto or paused or not autoPath or not oldNodes then return nil end
  local veh = playerVeh()
  if not veh then return nil end
  local p = veh:getPosition()
  local ids = M.startPath(autoPath, oldNodes, p, veh:getDirectionVector())
  ids = M.validFrom(ids, 1, { oldNodes })
  return { ids = ids, full = #ids }
end

-- ... and applied: load the vehicle's map and restore its remaining GPS path together. Even an unchanged
-- list needs restoring: stock ai.updateGFX discards currentRoute when mapmgr replaces its mapData object.
function M.afterGraph(keep, newNodes)
  local veh = playerVeh()
  if not keep or not veh or not newNodes then return end
  local ids = M.validFrom(keep.ids, 1, { newNodes })
  local p = veh:getPosition()
  M.trace('keep', ids, newNodes, p)
  if #ids >= 2 then
    autoFinal = autoFinal and #ids == keep.full
    veh:queueLuaCommand(M.autoCommand(ids, autoFinal))
    autoPath, autoSerial, waiting = ids, graphSerial() + 1, nil
    roadHint, holdSince = ids, nil
  else
    holdRoute(veh, 'route')
  end
  if #ids < keep.full then routedTo = nil end
  M.graphKeeps = (M.graphKeeps or 0) + 1
end

local arrowsSerial = nil
-- target: a vec3, or a list of them (waypoints along the route, then the target)
local function setArrows(key, target, tail, nodes)
  local serial = graphSerial()
  if key == routedTo and serial == arrowsSerial then return end
  local gm = rawget(_G, 'core_groundMarkers')
  if not gm or not gm.setPath then return end
  if pcall(gm.setPath, target, { clearPathOnReachingTarget = false }) then
    routedTo, arrowsSerial = key, serial
    -- Ground markers are presentation only. Their point-to-point snapping can select the
    -- crossing bridge or an exit; the driving path is matched independently to the server route.
    if tail then pcall(appendTail, gm, tail.e, tail.s, tail.z) end
    return true
  end
end

function M.setAutodrive(on)
  on = on and true or false
  if on == auto then return auto end
  if not on then blockedOnStop = waiting ~= nil or stillSince ~= nil end
  restartRoute = on and blockedOnStop
  auto = on
  debugEvent(on and 'enabled' or 'disabled', 'restartRoute=' .. tostring(restartRoute))
  autoPath, autoSerial, stillSince, paused = nil, nil, nil, false
  autoFinal = false
  waiting, watch, recoveries, recovering = nil, nil, 0, false
  holdSince, lastHeartbeat = nil, -math.huge
  if on then
    local veh = playerVeh()
    if veh then veh:queueLuaCommand(M.pauseCommand()) end
    waiting = 'route'
    holdSince = os.clock()
    routedTo = nil                       -- the arrows (and the AI's path) set again at the next check
    lastCheck = -math.huge
  else
    local veh = playerVeh()
    if veh then veh:queueLuaCommand(M.autoCommand(nil)) end
  end
  return auto
end
function M.autodrive() return auto end

local function damage(veh)
  local m = rawget(_G, 'map')
  local o = m and m.objects and m.objects[veh:getId()]
  return o and tonumber(o.damage) or 0
end

-- Retry a path after a graph rejection/hold; brake for a disconnected world, end for severe damage.
local function autoKeep(nodes, now)
  if not auto then return end
  local veh = playerVeh()
  if not veh then return end
  if damage(veh) > M.AUTO_DAMAGE then
    debugEvent('damage_stop','damage=' .. tostring(damage(veh)))
    M.setAutodrive(false)
    if ui_message then pcall(ui_message, 'Autodrive off: the car is damaged', 6, 'beamngEarthGps') end
    return
  end
  local c = core()
  local ready = c and (c.autodriveReady or c.serverHealthy)
  local healthy = not ready or ready()
  if not healthy then
    if not paused then holdRoute(veh, 'server') end
    paused, stillSince = true, nil
    return
  elseif paused then
    debugEvent('server_ready','resuming route validation')
    paused, routedTo = false, nil         -- back: the path given again
  end
  local v = veh.getVelocity and veh:getVelocity()
  local speed = v and math.sqrt(v.x * v.x + v.y * v.y) or 0
  if speed < 1 then stillSince = stillSince or now else stillSince = nil end
  if waiting or (autoPath and autoSerial ~= graphSerial()) then
    routedTo = nil
  end
end

-- Detect a loop by route progress AND distance driven. Speed alone cannot distinguish a circle from a drive.
-- Recovery holds the car while a route from its current position/heading is requested; failures are bounded.
local function watchProgress(here, player, now)
  if not auto or paused or recovering then return end
  if not watch then watch = { best = here, since = now, travel = 0, x = player.x, y = player.y } end
  local moved = math.sqrt((player.x - watch.x) ^ 2 + (player.y - watch.y) ^ 2)
  watch.x, watch.y = player.x, player.y
  watch.travel = watch.travel + moved
  if here >= watch.best + M.AUTO_PROGRESS_M then
    watch.best, watch.since, watch.travel, recoveries = here, now, 0, 0
  end
  local loop = now - watch.since >= M.AUTO_LOOP_S and watch.travel >= M.AUTO_LOOP_TRAVEL_M
  local stuck = stillSince and now - stillSince >= M.AUTO_STALL_S
  local held = waiting and holdSince and now-holdSince >= M.AUTO_HOLD_S
  -- Streaming normally rebuilds only after movement. Request a fresh graph while stationary
  -- too: a graph made before road data finished loading otherwise never repairs itself.
  if held and now-lastRefresh >= M.REROUTE_S then
    local c=core()
    if c and c.requestAutodriveRefresh and c.requestAutodriveRefresh() then
      lastRefresh=now
      debugEvent('graph_refresh','reason=' .. tostring(waiting))
    end
  end
  if pendingId or not (loop or stuck or held) or (held and now-lastRequest<M.REROUTE_S) then return end
  recoveries = recoveries + 1
  if recoveries > M.AUTO_RECOVERY_LIMIT then
    debugEvent('recovery_failed','attempts=' .. recoveries .. ' reason=' .. tostring(lastReject or (matchInfo and matchInfo.reason)))
    M.setAutodrive(false)
    if ui_message then pcall(ui_message, 'Autodrive off: unable to find a drivable route from here', 8, 'beamngEarthGps') end
    return
  end
  local veh = playerVeh()
  debugEvent('recovery', 'attempt=' .. recoveries .. ' reason=' .. (loop and 'loop' or held and 'route_hold' or 'stalled'))
  if veh then holdRoute(veh, 'route') end
  routedTo, stillSince, watch = nil, nil, nil
  holdSince = now
  recovering = requestRoute(player) == true
end

local function heartbeat(player, now)
  if not auto or now-lastHeartbeat<10 then return end
  lastHeartbeat=now
  local veh=playerVeh()
  local p=veh and veh:getPosition() or player
  local v=veh and veh.getVelocity and veh:getVelocity()
  local d=veh and veh:getDirectionVector() or {}
  local speed=v and math.sqrt(v.x*v.x+v.y*v.y) or 0
  local m=matchInfo or {}
  local rd=m.road or {}
  debugEvent('heartbeat',string.format('route=%s graph=%s command=%d pos=%.1f,%.1f,%.1f speed=%.1f remaining=%.1f off=%.1f wait=%s hold=%.1f pending=%s recoveries=%d match=%s edge=%s>%s end=%s nodes=%d length=%.1f startOff=%.1f visited=%d blocked[corridor=%d direction=%d horizon=%d] heading=%.2f,%.2f map=%s roadReason=%s roadHeightError=%.2f roadLateral=%.2f reject=%s',
    tostring(route and route.version),tostring(graphSerial()),commandId,p.x,p.y,p.z or 0,speed,
    info and info.remaining or -1,info and info.off or -1,tostring(waiting),holdSince and now-holdSince or 0,
    tostring(pendingId),recoveries,tostring(m.reason),tostring(m.start),tostring(m.next),tostring(m.endpoint),
    m.nodes or 0,m.length or 0,m.startOff or -1,m.visited or 0,m.corridor or 0,m.direction or 0,m.horizon or 0,
    d.x or 0,d.y or 0,tostring(currentMapSerial()),tostring(rd.reason),rd.heightError or 0,rd.lateral or -1,tostring(lastReject)))
end

local function refreshLead()
  local veh = playerVeh()
  local v = veh and veh.getVelocity and veh:getVelocity()
  local speed = v and math.sqrt(v.x * v.x + v.y * v.y) or 0
  -- Extend before braking for the temporary endpoint: stopping distance plus three update intervals.
  return math.max(2 * M.RETARGET_M, speed * speed / 5 + 3 * M.CHECK_S * speed + 80)
end

-- Every frame (anchor: the current geodesy anchor; player: {x, y, lat, lon}): the route kept to the destination.
function M.update(anchor, player)
  if not dest or not anchor or not player then return end
  local now = os.clock()
  if now - lastCheck < M.CHECK_S then return end
  lastCheck = now
  if auto and restartRoute then
    restartRoute, blockedOnStop = false, false
    enu, progress, matchInfo = nil, 1, nil
    local c=core()
    if c and c.requestAutodriveRefresh and c.requestAutodriveRefresh() then lastRefresh=now end
    -- Replace even an outstanding stale request; its old response cannot start the car.
    recovering = requestRoute(player) == true
  end
  -- the planned route: asked once (and on re-routes), taken when it arrives
  if pendingId then
    local c = core()
    local r = c and c.takeRoute and c.takeRoute(pendingId)
    if r then
      pendingId = nil
      if r.points and #r.points >= 2 and (tonumber(r.dist) or 0) >= 1 then
        routeVersion = routeVersion + 1
        route = { points = r.points, dist = r.dist, dur = r.dur, version = routeVersion }
        routeError, enu, routedTo, targetS, watch, recovering = nil, nil, nil, nil, nil, false
        debugEvent('route_ready',string.format('version=%d points=%d distance=%.1f',routeVersion,#r.points,r.dist))
      else
        routeError = r.error or 'no route'
        debugEvent('route_failed',tostring(routeError))
        recovering = false
        if not route then route = false end
      end
    elseif now - lastRequest > 30 then
      debugEvent('route_timeout','id=' .. tostring(pendingId))
      pendingId = nil                      -- no answer: try again below
      recovering = false
    end
  elseif route == nil or (route == false and now - lastRequest > M.REROUTE_S) then
    requestRoute(player)
  end

  -- The map/menu may pause physics. Route requests and replies must still run so choosing
  -- a waypoint displays the route before Autodrive (which closes the map) is pressed.
  -- Only driving/arrival/progress detection is suspended; pause time is never a stall.
  local sta = rawget(_G, 'simTimeAuthority')
  if sta and sta.getPause and sta.getPause() then
    stillSince, watch = nil, nil
    if holdSince then holdSince=now end
    return
  end

  local tx, ty = anchor:geodeticToEnu(dest.lat, dest.lon, 0)
  local dx, dy = tx - player.x, ty - player.y
  local dist = math.sqrt(dx * dx + dy * dy)
  info = { dist = dist, bearing = M.bearing(player.x, player.y, tx, ty), remaining = dist }
  if route == false and dist < M.ARRIVE_M then
    if ui_message then pcall(ui_message, 'Arrived: ' .. (dest.name or 'destination'), 5, 'beamngEarthGps') end
    M.clear()
    return
  end
  local m = rawget(_G, 'map') and map.getMap and map.getMap()
  local nodes = m and m.nodes
  autoKeep(nodes, now)

  if route then
    local e = toEnu(anchor)
    local n = #e.x
    local i, t, off = M.nearestSegment(e.x, e.y, player.x, player.y, progress - 5, progress + 400)
    if off > M.OFF_ROUTE_M then i, t, off = M.nearestSegment(e.x, e.y, player.x, player.y, 1, n) end
    progress = i
    local remaining = e.cum[n] - (e.cum[i] + t * (e.cum[i + 1] - e.cum[i]))
    if dist < M.ARRIVE_M and remaining < M.ARRIVE_M then
      if ui_message then pcall(ui_message, 'Arrived: ' .. (dest.name or 'destination'), 5, 'beamngEarthGps') end
      M.clear()
      return
    end
    info.remaining = remaining + off
    info.off = off
    if route.dist and route.dist > 0 and route.dur then info.eta = route.dur * remaining / route.dist end
    if off > M.OFF_ROUTE_M and not pendingId and now - lastRequest > M.REROUTE_S then requestRoute(player) end
    local here = e.cum[i] + t * (e.cum[i + 1] - e.cum[i])
    watchProgress(here, player, now)
    if auto and not paused and not recovering then
      local ok, err = pcall(function() driveRoutePath(matchedRoute(e, nodes, here), nodes) end)
      if not ok then
        local veh = playerVeh()
        if veh then holdRoute(veh, 'route') end
        if log then log('W', 'beamngEarth', 'Autodrive route match: ' .. tostring(err)) end
      end
    end
    heartbeat(player,now)
    local tg = nodes and routeTarget(e, nodes, i, t)
    if tg then
      -- set again only when the target moved on by a good stretch (each setPath re-plans the arrows)
      -- only forward (the farthest point on the graph flickered between two 150 m steps, every second a new path
      -- and the AI re-planning: Fells Point 2026-10-14), unless the old target is about reached
      local keep = targetS and type(routedTo) == 'string' and routedTo:sub(1, 1) == 'r'
        and tg.s < targetS + M.RETARGET_M and targetS > here + refreshLead()
      local key = tg.final and 'final' or (keep and routedTo) or ('r' .. math.floor(tg.s / M.RETARGET_M))
      local wps = {}
      for _, w in ipairs(tg.via or {}) do wps[#wps + 1] = vec3(w.x, w.y, w.z) end
      wps[#wps + 1] = vec3(tg.x, tg.y, tg.z)
      if setArrows(key, wps, not tg.final and { e = e, s = tg.s, z = tg.z } or nil, nodes) then targetS = tg.s end
      return
    end
  end
  -- no planned route (yet, or offline), or none of it on the local graph: toward the destination
  -- With a planned route, a disconnected local graph is a loading gap. A nearest-destination
  -- fallback can pick the other carriageway or a dead end and send the car round in circles.
  if auto then
    local veh = playerVeh()
    if veh and not autoPath then holdRoute(veh, 'route') end
    heartbeat(player,now)
    routedTo = nil
    return
  end
  local id, pos, nd = M.pickNode(nodes, tx, ty)
  if not id then return end
  local final = nd <= M.FINAL_M
  setArrows(final and 'final' or id, final and vec3(tx, ty, pos.z) or vec3(pos.x, pos.y, pos.z), nil, nodes)
end

-- The level ended: the arrows went with it (the destination and its route stay for the next level start).
function M.reset()
  if auto then M.setAutodrive(false) end
  routedTo, info, lastCheck, enu, progress = nil, nil, -math.huge, nil, 1
  targetS, watch, vehGraph = nil, nil, {}
end

return M
