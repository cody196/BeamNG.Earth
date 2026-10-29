-- luajit mod/tests/test_gps_rebase.lua
-- Exercise the two Lua VMs separately: queued vehicle commands, delayed GE acknowledgements,
-- an old map after a 15 km origin move, a delayed replacement map and a fresh route on resume.
local T = dofile((arg[0]:match('^(.*)[/\\]') or '.') .. '/testlib.lua')
local G = require('beamngEarth/gps')
local now, healthy, appliedAnchor, appliedSerial, applies = 0, true, 1, 1, 1
os.clock = function() return now end
function vec3(x, y, z) return { x = x, y = y, z = z } end
local function anchor(offset)
  return { geodeticToEnu = function(_, lat, lon) return lon + offset, lat, 0 end }
end
local oldAnchor, newAnchor = anchor(15000), anchor(0)
local activeAnchor = oldAnchor
local function nodes(offset)
  return { a = { pos = vec3(offset, 0, 0), links = { b = {} } },
    b = { pos = vec3(offset + 100, 0, 0), links = { c = {} } },
    c = { pos = vec3(offset + 1000, 0, 0), links = {} } }
end
local gm = { buildSerial = 1, nodes = nodes(15000) }
map = { getMap = function() return gm end, objects = { [7] = { damage = 0 } } }
package.loaded['beamngEarth/navgraph'] = {
  applies = function() return applies end,
  appliedFor = function(aid)
    if aid == appliedAnchor and gm.buildSerial == appliedSerial then return appliedSerial end
  end,
}
local mailbox = { buildSerial = 1, graphData = {}, edgeKdTree = {}, maxRadius = 5, nodeAliases = {} }
local sent, queued, callbacks, drives, imports = {}, {}, {}, {}, 0
local controls = { brake = 0, parkingbrake = 0 }
local mode = 'manual'
local veh = { id = 7, pos = vec3(15020, 0, 0), vel = vec3(30, 0, 0) }
function veh:getID() return self.id end
veh.getId = veh.getID
function veh:getPosition() return self.pos end
function veh:getVelocity() return self.vel end
function veh:getDirectionVector() return vec3(1, 0, 0) end
function veh:queueLuaCommand(cmd) sent[#sent + 1] = cmd; queued[#queued + 1] = cmd end
local playerVeh = veh
function getPlayerVehicle() return playerVeh end
scenetree = { findObjectById = function(id) if id == 7 then return veh end end }
local vehicleEnv = setmetatable({
  ai = {
    setMode = function(m)
      mode = m
      if m == 'disabled' then controls.brake, controls.parkingbrake, controls.throttle, controls.steering = 0, 0, 0, 0 end
    end,
    driveUsingPath = function(path) mode = 'manual'; drives[#drives + 1] = path end,
  },
  obj = {
    queueGameEngineLua = function(_, cmd) callbacks[#callbacks + 1] = cmd end,
    getLastMailbox = function() return mailbox end,
  },
  lpack = { decode = function(m) return m end },
  mapmgr = { setMap = function() imports = imports + 1 end, requestMap = function() end },
  input = { event = function(key, value) controls[key] = value end },
}, { __index = _G })
local function runVehicle()
  local q = queued; queued = {}
  for _, cmd in ipairs(q) do setfenv(assert(loadstring(cmd)), vehicleEnv)() end
end
local function runGE()
  local q = callbacks; callbacks = {}
  for _, cmd in ipairs(q) do assert(loadstring(cmd))() end
end
local response
beamngEarth_core = {
  serverHealthy = function() return healthy end,
  requestRoute = function()
    response = { points = { { 0, 0 }, { 0, 1000 } }, dist = 1000, dur = 100 }
    return true
  end,
  takeRoute = function() local r = response; response = nil; return r end,
  onAutodriveRebasePaused = G.onRebasePaused,
  onAutodriveRebaseMap = G.onRebaseMap,
}
local plans, brokenPath = 0, false
core_groundMarkers = {
  routePlanner = {},
  setPath = function(target)
    if not target then return end
    plans = plans + 1
    core_groundMarkers.routePlanner.path = brokenPath and { { wp = 'missing' } } or { { wp = 'b' }, { wp = 'c' } }
  end,
}
local function tick(dt)
  now = now + dt
  G.updateRebase(dt)
  local p = veh.pos
  G.update(activeAnchor, { x = p.x, y = p.y, lat = 0, lon = 20, vx = 30, vy = 0 })
end
local function flush() runVehicle(); runGE() end
G.setDestination(0, 1000, 'test destination')
G.setAutodrive(true)
G.onVehicleMapmgrUpdate(7)
tick(1); tick(1); flush()
T.check(#drives == 1 and drives[1].path[1] == 'b' and drives[1].path[2] == 'c', 'initial route targets the road ahead, not the passed start node')
local routeVersion = G.status().routeVersion
local plansBefore = plans

T.check(not G.prepareRebase(2), 'vehicle move must wait for the disable acknowledgement')
T.check(G.status().autodrive and G.status().autodrivePaused == 'rebase', 'pause preserves the autodrive choice')
T.check(G.beforeGraph(gm.nodes) == nil, 'old graph continuity cannot carry a path through a rebase')
local n = #sent
G.afterGraph({ ids = { 'a', 'b' }, full = 2 }, gm.nodes)
T.check(#sent == n, 'graph update cannot restart AI during the hold')
G.onRebasePaused(99, 1); G.onRebasePaused(7, 0)
T.check(not G.prepareRebase(2) and #sent == n, 'wrong vehicle / old token ignored, disable not spammed')
runVehicle()
T.check(mode == 'disabled' and controls.brake == 0 and veh.vel.x == 30, 'AI disabled with neutral inputs and momentum intact')
T.check(not G.prepareRebase(2), 'command execution alone: still waiting for its GE callback')
runGE()
T.check(G.prepareRebase(2), 'confirmed disabled: core may now move the vehicle')
G.finishRebase(newAnchor, 2)
activeAnchor, veh.pos = newAnchor, vec3(20, 0, 0)
for _ = 1, 20 do tick(0) end
T.check(G.status().autodrivePaused == 'rebase' and #sent == n, 'paused simulation consumes no coast time')
tick(0.4); flush()
T.check(controls.brake == 0 and #drives == 1 and plans == plansBefore, 'coast while the map still has old coordinates')
tick(0.2); flush()
T.check(controls.brake > 0 and controls.brake < 0.7 and mode == 'disabled', 'slow graph: gradual braking without old AI steering')
tick(5); flush()
T.check(#drives == 1 and plans == plansBefore and controls.brake == 0.7, 'no timeout bypass into the old map, even past GRAPH_WAIT_S')
veh.vel = vec3(0, 0, 0)
tick(0.1); flush()
T.check(controls.parkingbrake == 1, 'held at rest while waiting for navigation')
veh.vel = vec3(30, 0, 0)

-- A GE map update and its stock hook are not proof that the vehicle imported the new map.
gm.buildSerial, gm.nodes, appliedAnchor, appliedSerial, applies = 2, nodes(0), 2, 2, 2
G.onVehicleMapmgrUpdate(7)
tick(0.1); flush()
T.check(imports == 0 and #drives == 1, 'old vehicle mailbox cannot acknowledge the replacement graph')
local decode = vehicleEnv.lpack.decode
vehicleEnv.lpack.decode = function() error('incomplete mailbox') end
tick(1.1)
local ok = pcall(runVehicle)
runGE()
T.check(ok and imports == 0 and #drives == 1, 'undecodable mailbox keeps the hold without failing vehicle Lua')
vehicleEnv.lpack.decode = decode
mailbox = { buildSerial = 2, graphData = {}, edgeKdTree = {}, maxRadius = 5 } -- malformed
tick(1.1); flush()
T.check(imports == 0 and #drives == 1, 'incomplete mailbox cannot release the hold')
mailbox.nodeAliases = {}
tick(1.1); runVehicle()
T.check(imports == 1 and #drives == 1, 'vehicle imports the correct graph before acknowledging it')
runGE()
tick(0.1); flush()
T.check(#drives == 2 and mode == 'manual' and not G.status().autodrivePaused, 'fresh route resumes promptly after the acknowledgement')
T.check(controls.brake == 0 and controls.parkingbrake == 0, 'resume clears fallback brakes')
T.check(drives[2].path[1] == 'b' and drives[2].path[2] == 'c', 'resume follows the current edge forward without revisiting its start')
T.check(G.status().name == 'test destination' and G.status().routeVersion == routeVersion, 'destination and long route survive the pause')

-- Back-to-back graph updates: the acknowledgement for serial 3 arrives after GE has serial 4.
T.check(not G.prepareRebase(3), 'next rebase starts a fresh hold')
flush()
G.finishRebase(newAnchor, 3)
gm.buildSerial, appliedAnchor, appliedSerial, mailbox.buildSerial = 3, 3, 3, 3
tick(0.1); runVehicle()
gm.buildSerial, appliedSerial, mailbox.buildSerial = 4, 4, 4
runGE(); tick(0.1)
T.check(#drives == 2 and G.status().autodrivePaused, 'an obsolete graph acknowledgement cannot resume')
flush()
brokenPath = true
tick(0.1); flush()
T.check(#drives == 2 and G.status().autodrivePaused, 'correct graph but invalid route: remain held')
brokenPath = false
tick(0.11); flush()
T.check(#drives == 3 and not G.status().autodrivePaused, 'retry a fresh usable route without the normal one-second delay')

-- A discarded preparation resumes in the unchanged anchor; no phantom wait for its abandoned target.
G.prepareRebase(4); flush()
G.cancelRebasePreparation(newAnchor, 3)
tick(0.1); flush(); tick(0.1); flush()
T.check(#drives == 4 and not G.status().autodrivePaused, 'discarded rebase rejoins the current graph')

-- Server loss, manual cancellation, vehicle changes and level teardown cannot auto-resume later.
G.prepareRebase(4); flush(); G.finishRebase(newAnchor, 4)
healthy = false
tick(0.1); flush()
T.check(controls.brake >= 0.3, 'server loss brakes immediately, even inside the coast window')
gm.buildSerial, appliedAnchor, appliedSerial, mailbox.buildSerial = 5, 4, 5, 5
tick(0.1); flush(); tick(0.1); flush()
T.check(#drives == 4, 'ready graph cannot resume while the server is unhealthy')
G.setAutodrive(false); flush()
healthy = true
tick(2); flush()
T.check(not G.autodrive() and #drives == 4 and controls.brake == 0, 'manual off cancels automatic resume and releases braking')

G.setAutodrive(true); G.prepareRebase(5); runVehicle()
G.setAutodrive(false); G.setAutodrive(true); G.prepareRebase(5)
runGE()
T.check(not G.prepareRebase(5), 'old pause acknowledgement cannot unlock a new hold after off/on')
flush()
playerVeh = { getID = function() return 8 end, queueLuaCommand = function() end }
tick(0.1); runVehicle()
T.check(not G.autodrive() and controls.brake == 0, 'vehicle switch cancels resume and releases the original vehicle')
playerVeh = veh

G.setAutodrive(true); G.prepareRebase(6); flush()
G.finishRebase(newAnchor, 6); tick(1); flush()
G.reset(); flush()
T.check(not G.autodrive() and controls.brake == 0, 'level teardown releases the hold')
G.setAutodrive(true); G.prepareRebase(7); flush()
map.objects[7].damage = G.AUTO_DAMAGE + 1
tick(0.1); flush()
T.check(not G.autodrive(), 'damage stops autodrive during a rebase pause')
map.objects[7].damage = 0

G.setAutodrive(true); G.prepareRebase(8)
tick(G.REBASE_ACK_S)
T.check(not G.autodrive() and G.prepareRebase(8), 'missing pause acknowledgement turns autodrive off without blocking rebases forever')
flush(); tick(1); flush()
T.check(not G.autodrive(), 'late callbacks after acknowledgement timeout do not restart autodrive')
G.clear()
T.done('test_gps_rebase')
