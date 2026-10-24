-- LuaJIT: the real vehicle bridge against a model of the stock AI's map reset and setPath semantics.
local dir = (arg[0]:match('^(.*)[/\\]') or '.')
local T = dofile(dir .. '/testlib.lua')
local A = dofile(dir .. '/../beamng_earth/lua/vehicle/extensions/beamngEarthAutodrive.lua')
local G = require('beamngEarth/gps')
local function same(a, b) return table.concat(a or {}, ',') == table.concat(b or {}, ',') end
local function copy(a) local out = {}; for i, v in ipairs(a) do out[i] = v end; return out end

T.check(same(A.extension({'a','b','c'}, {'b','c','d'}), {'c','d'}), 'append from the old final node')
T.check(same(A.extension({'a','b','c'}, {'b','c'}), {}), 'already covered: no restart')
T.check(same(A.extension({'a','b','c'}, {'a','b'}), {}), 'a shorter target does not shorten the active path')
T.check(A.extension({'a','b','c'}, {'b','x','c'}) == nil, 'a genuinely changed turn needs a replacement')

local function graph(last)
  local data = {graph = {}, positions = {}}
  for i = 1, #last do data.graph[last[i]] = {}; data.positions[last[i]] = {x = i * 100, y = 0, z = 0} end
  for i = 1, #last - 1 do
    local e = {oneWay = true, inNode = last[i]}
    data.graph[last[i]][last[i+1]], data.graph[last[i+1]][last[i]] = e, e
  end
  return data
end
local maps = { [1] = graph({'a','b','c','d','e'}), [2] = graph({'b','c','d','e','f'}) }
local serial, aiMap, currentRoute, manualPath = 1, nil, nil, nil
local starts, restores, stops, disabled, rejects = 0, 0, 0, 0, 0
local inputs = {}
local position, direction = {x=150,y=0,z=0}, {x=1,y=0,z=0}
mapmgr = { mapData = maps[1], setMap = function(s) serial = s; mapmgr.mapData = maps[s] end }
input = { event = function(k, value) inputs[k] = value end }
obj = { queueGameEngineLua = function() rejects = rejects + 1 end,
  getPosition=function() return position end, getDirectionVector=function() return direction end }
ai = { mode = 'disabled',
  driveUsingPath = function(p)
    starts = starts + 1
    ai.mode, currentRoute, aiMap, manualPath = 'manual', nil, nil, p.path
    T.check(p.driveInLane == 'on' and p.avoidCars == 'on' and p.routeSpeedMode == 'legal', 'keep stock lane/traffic/legal-speed control')
  end,
  setPath = function(ids) restores = restores + 1; manualPath = ids end,
  setMode = function(mode)
    ai.mode, currentRoute, manualPath = mode, nil, nil
    if mode == 'stop' then stops = stops + 1 elseif mode == 'disabled' then disabled = disabled + 1 end
  end }
local function frame()
  -- Stock ai.updateGFX clears currentRoute on a new map, then newManualPath consumes setPath.
  if aiMap ~= mapmgr.mapData then currentRoute = nil end
  aiMap = mapmgr.mapData
  if manualPath then
    if currentRoute then
      if currentRoute[#currentRoute] == manualPath[1] then
        for i = 2, #manualPath do currentRoute[#currentRoute+1] = manualPath[i] end
      end
    else currentRoute = manualPath end
    manualPath = nil
  end
  A.updateGFX()
end
local function settle() frame(); frame() end
A.setPath({'a','b','c'}, 1, 1); settle()
T.check(starts == 1 and same(currentRoute, {'b','c'}), 'initial activation starts the driver once, aiming forward')
A.setPath({'b','c','d'}, 1, 2); settle()
T.check(starts == 1 and restores == 1 and same(currentRoute, {'b','c','d'}), 'extend while preserving controls')
A.setPath({'b','c'}, 1, 3); settle()
T.check(starts == 1 and restores == 1 and currentRoute[#currentRoute] == 'd', 'shorter visibility does not introduce a stopping endpoint')

-- Two GE requests before the next vehicle frame must coalesce into a FULL remaining route.
A.setPath({'b','c','d','e'}, 2, 4)
A.setPath({'b','c','d','e','f'}, 2, 5)
settle()
T.check(starts == 1 and restores == 2 and same(currentRoute, {'c','d','e','f'}),
  'a streamed map restores and extends without losing the road between the car and the old endpoint')
A.setPath({'b','c','d','e','f'}, 2, 6); settle()
T.check(starts == 1 and restores == 2, 'repeated arrow refreshes do not reset or resend the AI path')

-- The geometry can change between GE planning and command execution. Reject against the actual copy.
A.setPath({'b','missing','f'}, 2, 7); settle()
T.check(ai.mode == 'stop' and rejects == 1 and starts == 1, 'missing edges stop and request a fresh GPS path')
A.setPath({'c','b'}, 2, 8); settle()
T.check(ai.mode == 'stop' and rejects == 2, 'one-way direction is checked in the vehicle too')
A.setPath({'b','c','d'}, 2, 9); settle()
T.check(ai.mode == 'manual' and starts == 2, 'a valid road becoming available resumes driving')
A.pause(); settle()
T.check(ai.mode == 'stop', 'an explicit loading/recovery hold stays stopped')
A.setPath({'b','c','d'}, 2, 10); settle()
A.stop(); settle()
T.check(ai.mode == 'disabled' and disabled == 1 and inputs.throttle == 0 and inputs.brake == 0
  and inputs.steering == 0 and inputs.parkingbrake == 0, 'turning off clears bridge ownership and AI inputs')
A.setPath({'b','c','d','e'}, 2, 11); settle()
local before = starts
A.setPath({'b','c'}, 2, 12, nil, nil, true); settle()
T.check(starts == before + 1 and same(currentRoute, {'c'}), 'a genuine final destination may shorten the route')
maps[2].graph.b.e = {oneWay=true,inNode='b'}
A.setPath({'b','e','f'}, 2, 13); settle()
T.check(starts == before + 2 and same(currentRoute, {'e','f'}), 'a changed turn replaces the route once')
mapmgr.mapData = graph({'b','c','d','e','f'})
settle()
T.check(ai.mode == 'stop' and rejects == 3, 'an unexpected map change requests a freshly trimmed route')
A.stop()

-- A node path is a list of targets, NOT a polyline with an implicit rear support point.
-- Stock ai.lua planAhead creates ego.pos first; buildNextRoute then visits path[1].
local straight = graph({'a','b','c','d','e'})
T.check(same(A.forwardPath({'a','b','c','d'}, straight, {x=250,y=0,z=0}, direction), {'c','d'}),
  'delayed commands skip all nodes the car has already passed')
T.check(same(A.forwardPath({'a','b','c'}, straight, {x=200,y=0,z=0}, direction), {'c'}),
  'a car exactly on a node targets the next node')
T.check(A.forwardPath({'a','b','c'}, straight, {x=150,y=0,z=10}, direction)==nil,
  'do not start on a different overpass deck')
T.check(A.forwardPath({'a','b','c'}, straight, position, {x=-1,y=0})==nil,
  'a stale heading cannot command a U-turn')
local turn = graph({'a','b','c'})
turn.positions.c={x=200,y=100,z=0}
T.check(same(A.forwardPath({'a','b','c'}, turn, position, direction), {'b','c'}),
  'preserve the junction ahead when the route turns, rather than cutting the corner')

-- Mimic stock AI's in-place cleanup, then extend again. Its array must not own our history.
mapmgr.mapData=maps[1]
A.setPath({'a','b','c','d'},1,20); settle()
table.remove(currentRoute,1)
local startsBefore, restoresBefore=starts,restores
A.setPath({'a','b','c','d','e'},1,21); settle()
T.check(starts==startsBefore and restores==restoresBefore+1 and same(currentRoute,{'c','d','e'}),
  'stock AI pruning its own array cannot mutate the bridge comparison path')
local rejectBefore=rejects
maps[1].graph.c.a={}
A.setPath({'a','b','c','a','b'},1,22); settle()
T.check(ai.mode=='stop' and rejects==rejectBefore+1, 'a closed route loop is rejected before driving')
A.stop()

-- Exercise the real GPS call path, not just joinStart with already-separated arguments.
local nodes = {
  a = {pos={x=0,y=0,z=0},links={b={oneWay=true,inNode='a'}}},
  b = {pos={x=100,y=0,z=0},links={c={oneWay=true,inNode='b'}}},
  c = {pos={x=200,y=0,z=0},links={}},
  under = {pos={x=0,y=0,z=-10},links={under2={}}},
  under2 = {pos={x=200,y=0,z=-10},links={}},
}
T.check(same(G.startPath({'b','c'}, nodes, {x=40,y=1,z=0}, {x=1,y=0}), {'a','b','c'}),
  'the production path preparation captures both edgeUnder results')
T.check(same(G.startPath({'a','b','c'}, nodes, {x=140,y=1,z=0}, {x=1,y=0}), {'b','c'}), 'passed nodes are trimmed')
T.check(#G.startPath({'a','b','c'}, nodes, {x=40,y=1,z=0}, {x=-1,y=0}) == 0, 'do not chase a route backwards on a divided highway')
local a,b = G.edgeUnder(nodes, 40, 0, 1, 0, -10)
T.check(a == 'under' and b == 'under2', 'overpass matching uses deck height')
T.check(#G.joinStart({'a','c'}, 'a','b', nodes) == 0, 'an unreachable start requests replanning instead of a U-turn')
T.check(#G.validFrom({'a','b','c'},1,{nodes}) == 3 and #G.validFrom({'c','b'},1,{nodes}) == 1, 'legal directed edges only')
nodes.ramp1={pos={x=100,y=1,z=0},links={ramp2={oneWay=true,inNode='ramp1'}}}
nodes.ramp2={pos={x=200,y=1,z=0},links={}}
T.check(same(G.startPath({'a','b','c'},nodes,{x=140,y=1,z=0},{x=1,y=0}),{'b','c'}),
  'graph restoration stays on the known mainline even when a parallel ramp centreline is closer')
T.done('test_autodrive')
