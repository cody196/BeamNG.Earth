-- luajit mod/tests/test_gps_forward.lua
-- Reproduce the startup / graph-refresh 360: stock manual AI visits the first path node.
-- Inspect the actual commands sent to the vehicle, not just the contextual road-edge list.
local T = dofile((arg[0]:match('^(.*)[/\\]') or '.') .. '/testlib.lua')
local G = require('beamngEarth/gps')
local now, serial, healthy = 0, 1, true
os.clock = function() return now end
function vec3(x, y, z) return { x = x, y = y, z = z } end
local function road()
  local ns = {}
  for i, id in ipairs({ 'a', 'b', 'c', 'd', 'e', 'f' }) do
    ns[id] = { pos = vec3((i - 1) * 100, 0, 0), links = {} }
    if i > 1 then ns[string.char(96 + i - 1)].links[id] = {} end
  end
  return ns
end
local graph = { buildSerial = 1, nodes = road() }
map = { getMap = function() return graph end, objects = {} }
package.loaded['beamngEarth/navgraph'] = { applies = function() return serial end }
local queue, drives, mode, brake, traffic = {}, {}, 'disabled', 0, 0
local veh = { x = 40 }
function veh:getID() return 7 end
veh.getId = veh.getID
function veh:getPosition() return vec3(self.x, 0, 0) end
function veh:getDirectionVector() return vec3(1, 0, 0) end
function veh:getVelocity() return vec3(20, 0, 0) end
function veh:queueLuaCommand(cmd) queue[#queue + 1] = cmd end
local playerVeh = veh
function getPlayerVehicle() return playerVeh end
scenetree = { findObjectById = function(id) if id == 7 then return veh end end }
local env = setmetatable({
  ai = {
    setMode = function(m)
      mode = m
      if m == 'disabled' then brake = 0 end
      if m == 'traffic' then traffic = traffic + 1 end
    end,
    driveUsingPath = function(args)
      mode = 'manual'
      drives[#drives + 1] = args.path
      local first = graph.nodes[args.path[1]]
      T.check(first and first.pos.x > veh.x, 'every issued path starts ahead of the car, never behind it')
    end,
  },
  input = { event = function(key, v) if key == 'brake' then brake = v end end },
  mapmgr = { requestMap = function() end },
}, { __index = _G })
local function flush()
  local q = queue; queue = {}
  for _, cmd in ipairs(q) do setfenv(assert(loadstring(cmd)), env)() end
end
local plannerIds = { 'b', 'c', 'd', 'e', 'f' }
core_groundMarkers = { routePlanner = {}, setPath = function(target)
  if not target then return end
  local path = {}
  for _, id in ipairs(plannerIds) do path[#path + 1] = { wp = id } end
  core_groundMarkers.routePlanner.path = path
end }
local response
beamngEarth_core = {
  serverHealthy = function() return healthy end,
  requestRoute = function()
    response = { points = { { 0, 0 }, { 0, 1000 } }, dist = 1000, dur = 100 }
    return true
  end,
  takeRoute = function() local r = response; response = nil; return r end,
}
local anchor = { geodeticToEnu = function(_, lat, lon) return lon, lat, 0 end }
local function tick()
  now = now + 1.1
  G.update(anchor, { x = veh.x, y = 0, lat = 0, lon = veh.x, vx = 20, vy = 0 })
  flush()
end
local function replace(newNodes)
  local keep = G.beforeGraph(graph.nodes)
  graph = { buildSerial = graph.buildSerial + 1, nodes = newNodes }
  G.afterGraph(keep, newNodes)
  serial = serial + 1 -- navgraph counts the successful apply after afterGraph
  G.onVehicleMapmgrUpdate(7)
  flush()
end
G.setDestination(0, 1000, 'forward test')
G.setAutodrive(true)
G.onVehicleMapmgrUpdate(7)
tick(); tick()
T.check(#drives == 1 and drives[1][1] == 'b', 'enable between a and b: drive toward b, no loop back to a')

veh.x = 140
local ns = road(); ns.e.links = {} -- the graph window no longer reaches f
replace(ns)
T.check(#drives == 2 and drives[2][1] == 'c', 'a trimmed graph at b-c does not send the car back to b')
plannerIds = { 'c', 'd', 'e' }
tick()
T.check(drives[#drives][1] == 'c' and drives[#drives][2] == 'd', 'full refreshed route starts ahead too')

veh.x = 250
ns = road(); ns.d.links = {}
replace(ns)
T.check(#drives[#drives] == 1 and drives[#drives][1] == 'd', 'one remaining forward target is usable without a backwards anchor')
plannerIds = { 'd' }
tick()
T.check(#drives[#drives] == 1 and drives[#drives][1] == 'd', 'single-target route also works through the regular planner')

ns = road(); ns.c.links = {} -- only c remains connected on the current route, behind the car
local before = #drives
replace(ns)
T.check(#drives == before and mode == 'disabled' and brake == 0.5 and traffic == 0,
  'no forward path: brake instead of targeting the passed node or entering traffic mode')
plannerIds = { 'c' }
tick()
T.check(#drives == before and brake == 0.5 and G.status().autodrivePaused == 'navigation',
  'an unusable planner result keeps braking until a forward path arrives')
healthy = false; tick()
T.check(mode == 'disabled' and brake == 0.5, 'server outage keeps direct braking without returning to a stock AI mode')
healthy = true

plannerIds = { 'd', 'e', 'f' }
replace(road()); tick()
T.check(#drives == before + 1 and drives[#drives][1] == 'd' and brake == 0 and mode == 'manual',
  'fresh forward path releases the brake and resumes automatically')
T.check(not G.status().autodrivePaused and G.status().name == 'forward test', 'same destination, navigation wait cleared')

ns = road(); ns.c.links = {}
replace(ns)
G.setAutodrive(false); flush()
T.check(brake == 0 and mode == 'disabled', 'manual off releases the temporary navigation brake')
plannerIds = { 'c' }
G.setAutodrive(true); tick()
T.check(brake == 0.5, 'navigation wait can be entered again')
playerVeh = { getID = function() return 8 end, queueLuaCommand = function() end }
tick()
T.check(not G.autodrive() and brake == 0, 'switching vehicles cancels autodrive and releases the old vehicle brake')
G.clear()
T.done('test_gps_forward')
