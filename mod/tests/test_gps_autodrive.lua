-- End-to-end GPS/vehicle-bridge sequencing with streamed maps, a fake clock and stock AI path semantics.
local dir = (arg[0]:match('^(.*)[/\\]') or '.')
local T = dofile(dir .. '/testlib.lua')
local G = require('beamngEarth/gps')
local A = dofile(dir .. '/../beamng_earth/lua/vehicle/extensions/beamngEarthAutodrive.lua')
local N = require('beamngEarth/navgraph')
local now, serial, ready, healthy, paused = 0, 1, true, true, false
os.clock = function() return now end
N.applies = function() return serial end
function vec3(x,y,z) return {x=x,y=y,z=z or 0} end
local logs={}
function log(level,tag,text) logs[#logs+1]=tag..' '..text end
local messages = {}
function ui_message(text) messages[#messages+1] = text end
simTimeAuthority = {getPause=function() return paused end}
local pos, vel, direction = vec3(40,0,0), vec3(33,0,0), vec3(1,0,0)
local nodes, vehicleMaps = {}, {}
local gmMap = {nodes=nodes,buildSerial=serial}
map = {getMap=function() return gmMap end,objects={[77]={damage=0}}}
local commands, starts, additions, stops, requests = {}, 0, 0, 0, 0
local manualPath, currentRoute, aiMap
local function copy(xs) local a={}; for i,x in ipairs(xs) do a[i]=x end; return a end
local lastRequest, reply, returnRoute, routeFail = nil, nil, true, false
local graphRefreshes=0
beamngEarth_core = {
  serverHealthy=function() return healthy end,
  autodriveReady=function() return ready end,
  requestAutodriveRefresh=function() graphRefreshes=graphRefreshes+1; return true end,
  requestRoute=function(id)
    requests=requests+1; lastRequest=id
    if returnRoute then
      reply=routeFail and {error='no route'} or {points={{0,pos.x},{0,6000}},dist=6000-pos.x,dur=200}
    end
    return true
  end,
  takeRoute=function(id) if id==lastRequest and reply then local r=reply; reply=nil; return r end end,
}
local veh = {getPosition=function() return pos end,getVelocity=function() return vel end,
  getDirectionVector=function() return direction end,getId=function() return 77 end,
  queueLuaCommand=function(_,code)
    commands[#commands+1]=code
    local f,err=loadstring(code); assert(f,err); f()
  end}
function getPlayerVehicle() return veh end
local function installGraph(first,last,broken)
  nodes={}
  local data={graph={},positions={},radius={}}
  for x=first,last,100 do
    local id='n'..x
    nodes[id]={pos=vec3(x,0,0),radius=3.7,links={}}
    data.graph[id]={}
    data.positions[id],data.radius[id]=nodes[id].pos,3.7
  end
  for x=first,last-100,100 do
    if x~=broken then
      local a,b='n'..x,'n'..(x+100)
      local e={oneWay=true,inNode=a}
      nodes[a].links[b]=e
      data.graph[a][b],data.graph[b][a]=e,e
    end
  end
  gmMap.nodes,gmMap.buildSerial=nodes,serial
  vehicleMaps[serial]=data
end
installGraph(0,700)
mapmgr={mapData=vehicleMaps[serial],setMap=function(s) mapmgr.mapData=vehicleMaps[s] end}
input={event=function() end}
obj={queueGameEngineLua=function(_,code) assert(loadstring(code))() end,
  getPosition=function() return pos end,getDirectionVector=function() return direction end,
  getVelocity=function() return vel end}
ai={mode='disabled',setMode=function(mode)
    ai.mode,currentRoute,manualPath=mode,nil,nil
    if mode=='stop' then stops=stops+1 end
  end,
  driveUsingPath=function(p)
    starts=starts+1; ai.mode,currentRoute,aiMap,manualPath='manual',nil,nil,p.path
  end,
  setPath=function(ids) additions=additions+1; manualPath=ids end}
extensions={load=function() return true end,beamngEarthAutodrive=A}
local function frame()
  if aiMap~=mapmgr.mapData then currentRoute=nil end
  aiMap=mapmgr.mapData
  if manualPath then
    if currentRoute then
      if currentRoute[#currentRoute]==manualPath[1] then
        for i=2,#manualPath do currentRoute[#currentRoute+1]=manualPath[i] end
      end
    else currentRoute=manualPath end
    manualPath=nil
  end
  A.updateGFX()
end
local function settle() frame(); frame() end
local emptyPath=false
core_groundMarkers={routePlanner={path={},calcDistance=function() end},setPath=function(target)
  local path={}
  if target and not emptyPath then
    local tg=target[#target] or target
    local order={}
    for id,n in pairs(nodes) do if n.pos.x>pos.x and n.pos.x<=tg.x+50 then order[#order+1]=id end end
    table.sort(order,function(a,b) return nodes[a].pos.x<nodes[b].pos.x end)
    for _,id in ipairs(order) do path[#path+1]={wp=id,pos=nodes[id].pos} end
  end
  core_groundMarkers.routePlanner.path=path
end}
local anchor={geodeticToEnu=function(_,lat,lon) return lon,lat,0 end}
local function tick(seconds,skipFrames)
  now=now+(seconds or 1.1)
  G.update(anchor,{x=pos.x,y=pos.y,lat=pos.y,lon=pos.x})
  if not skipFrames then settle() end
end
G.setDestination(0,6000,'Highway')
paused=true
tick(); tick()
T.check(requests==1 and G.route() and not G.status().planning and starts==0,
  'a waypoint plans and publishes its route while the map is paused, before Autodrive is pressed')
G.setAutodrive(true)
tick()
T.check(starts==0, 'planning while paused does not start the driving AI')
paused=false
tick(); tick()
T.check(starts==1 and currentRoute and currentRoute[1]=='n100' and currentRoute[2]=='n200',
  'the first AI target is ahead of the car, not the rear endpoint of its road edge')
local initialStarts=starts
for i=1,5 do pos.x=pos.x+20; tick() end
T.check(starts==initialStarts and requests==1, 'normal highway travel does not restart AI or reroute')

-- Graph apply, then GPS arrow update, BEFORE the next vehicle frame: this was a repeated reset.
local keep=G.beforeGraph(nodes)
serial=serial+1; installGraph(100,1200)
G.afterGraph(keep,nodes)
tick(nil,true); settle()
T.check(starts==initialStarts and additions>=1 and currentRoute[1]=='n200' and currentRoute[#currentRoute]=='n1200',
  'a streamed graph restores and extends the highway route without resetting speed controls')

-- Delayed terrain alone is not a reason to brake on already loaded road.
healthy=false; tick()
T.check(ai.mode=='manual' and starts==initialStarts, 'continue on loaded road when only a terrain request is late')
ready=false; tick()
T.check(ai.mode=='stop' and G.status().autoWaiting=='server', 'disconnect/resync holds the car')
ready,healthy=true,true; tick()
T.check(ai.mode=='manual', 'the world becoming ready resumes GPS driving')

-- No usable edge ahead: never switch the player's car to free-roaming traffic.
keep=G.beforeGraph(nodes)
serial=serial+1; installGraph(100,1200,100)
G.afterGraph(keep,nodes); settle(); tick()
T.check(ai.mode=='stop' and G.status().autodrive, 'a disappearing forward edge holds while retaining Autodrive intent')
T.check(not table.concat(commands,'\n'):find('setMode("traffic")',1,true), 'no traffic-mode fallback')
serial=serial+1; installGraph(100,1400); tick()
T.check(ai.mode=='manual' and currentRoute[1]=='n200', 'newly loaded drivable road automatically releases the hold')

-- An empty arrows result must leave the existing, valid route running.
emptyPath=true
keep=G.beforeGraph(nodes); serial=serial+1; installGraph(100,1400); G.afterGraph(keep,nodes); tick()
T.check(ai.mode=='manual', 'an empty planner result preserves the already validated route')
emptyPath=false
local beforeStops=stops
vel=vec3(0,0,0)
for i=1,10 do tick() end
T.check(stops==beforeStops and G.status().autoRecoveries==0, 'a short traffic stop does not reset AI')
paused=true; tick(60); paused=false; tick()
T.check(G.status().autoRecoveries==0, 'time spent paused is excluded from stuck recovery')

-- A circle can remain within the old off-route tolerance and never fall below 1 m/s.
vel=vec3(5,0,0); returnRoute=false
for i=1,50 do
  pos.x,pos.y=150+8*math.cos(i*0.7),8*math.sin(i*0.7)
  tick()
  if G.status().autoRecoveries>0 then break end
end
T.check(G.status().autoRecoveries==1 and ai.mode=='stop' and G.status().planning,
  'moving in circles triggers a controlled stop and a new route request')
-- Reply with a fresh route, heading east along the available road again.
pos.x,pos.y=150,0; returnRoute=true
reply={points={{0,150},{0,6000}},dist=5850,dur=180}
tick()
T.check(ai.mode=='manual' and currentRoute[1]=='n200', 'a fresh GPS route resumes after loop recovery')
pos.x=180; tick()
T.check(G.status().autoRecoveries==0, 'real forward progress clears recovery attempts')

-- Repeated unresolvable stalls are bounded; the car must not spin and restart forever.
returnRoute,routeFail,vel=true,true,vec3(0,0,0)
for i=1,220 do tick() end
T.check(not G.autodrive() and ai.mode=='disabled' and messages[#messages]:find('unable to find',1,true),
  'repeated failed recovery hands control back with an explanation')
G.clear()

-- A failed initial OSRM request must not hand the nearby graph's destination fallback to AI.
local startsBefore=starts
returnRoute,routeFail=true,true
G.setDestination(0,6000,'Unavailable route')
G.setAutodrive(true)
tick(); tick()
T.check(starts==startsBefore and ai.mode=='stop' and G.status().routeError,
  'a route failure holds the car instead of driving an unrelated nearest-destination path')
routeFail=false
for i=1,25 do tick() end
T.check(G.route() and ai.mode=='manual' and currentRoute[1]=='n200',
  'a failed initial route retries and starts forward when a valid route becomes available')
G.clear()

-- Replacing a destination in the paused map must clear old arrows and publish the new route.
paused=true
G.setDestination(0,8000,'Changed waypoint')
T.check(#core_groundMarkers.routePlanner.path==0, 'choosing a new destination immediately clears stale arrows')
tick(); tick()
T.check(G.route() and not G.status().planning and not G.autodrive(),
  'a second waypoint also completes planning in the paused map with Autodrive off')
G.clear()

-- The presentation planner can snap an intermediate GPS point onto a connected exit/overpass.
-- Autodrive must follow the planned highway even when the arrows' graph path is wrong.
paused=false
pos,vel,direction=vec3(40,0,0),vec3(33,0,0),vec3(1,0,0)
serial=serial+1; installGraph(0,1400)
local data=vehicleMaps[serial]
nodes.ramp={pos=vec3(250,35,2),radius=3,links={}}
nodes.bridge={pos=vec3(400,0,9),radius=3,links={}}
data.graph.ramp,data.graph.bridge={},{}
for _,id in ipairs({'ramp','bridge'}) do data.positions[id]=nodes[id].pos end
for _,pair in ipairs({{'n200','ramp'},{'ramp','bridge'}}) do
  local a,b=pair[1],pair[2]
  local e={oneWay=true,inNode=a}
  nodes[a].links[b]=e; data.graph[a][b],data.graph[b][a]=e,e
end
core_groundMarkers.setPath=function(target)
  local path={}
  if target then
    for _,id in ipairs({'n100','n200','ramp','bridge'}) do path[#path+1]={wp=id,pos=nodes[id].pos} end
  end
  core_groundMarkers.routePlanner.path=path
end
G.setDestination(0,6000,'Highway beyond the bridge'); G.setAutodrive(true)
tick(); tick()
T.check(ai.mode=='manual' and currentRoute[#currentRoute]=='n1400'
  and not table.concat(currentRoute):find('ramp'),
  'wrong bridge/exit snapping in ground markers cannot redirect Autodrive')
local startsOnHighway=starts
for x=140,940,100 do pos.x=x; tick() end
T.check(starts==startsOnHighway and currentRoute[#currentRoute]=='n1400' and G.status().remaining>4000,
  'pass the exit and bridge without a reroute or false arrival')

-- Stock AI has no notion of the remote GPS destination. Hold before it can finish a temporary path.
pos.x=1380
frame()
T.check(ai.mode=='stop' and G.autodrive() and G.status().remaining>4000,
  'reaching a temporary streamed endpoint holds while retaining the real destination')
tick()
T.check(ai.mode=='stop','the same short path cannot repeatedly restart and finish')
serial=serial+1; installGraph(1300,2100); tick()
T.check(ai.mode=='manual' and currentRoute[#currentRoute]=='n2100',
  'loading more mainline road automatically resumes toward the original destination')
G.clear()

pos.x,pos.y=40,0
G.setDestination(0,60,'Destination across an interchange')
tick()
reply={points={{0,40},{0,200},{200,200},{200,60},{0,60}},dist=700,dur=60}
tick()
T.check(G.status() and G.status().remaining>600,
  'passing within arrival radius in XY does not finish a route that still goes around an interchange')
G.clear()

-- Restart with a newly loaded stretch between the endpoint guard and the old
-- 120 m gate. Requiring 120 m here left a stationary car unable to advance.
pos,vel,direction=vec3(940,0,0),vec3(0,0,0),vec3(1,0,0)
serial=serial+1; installGraph(900,1000)
G.setDestination(0,6000,'Short continuation'); G.setAutodrive(true)
tick(); tick()
T.check(ai.mode=='manual' and currentRoute[#currentRoute]=='n1000',
  'a safe sixty-metre continuation can restart a stopped car')
pos.x=980; frame(); tick()
T.check(ai.mode=='stop' and G.status().autoLastReject
  and G.status().autoLastReject:find('remaining=',1,true),
  'endpoint hold carries the vehicle reason and remaining distance back to GPS')
local refreshBefore,requestsBefore=graphRefreshes,requests
for i=1,22 do tick() end
T.check(graphRefreshes>refreshBefore and requests>requestsBefore and G.autodrive(),
  'a stationary loading hold refreshes road data and replans without requiring movement')
local beforeRestart=requests
G.setAutodrive(false); G.setAutodrive(true); tick()
T.check(requests>beforeRestart,
  'restarting a blocked drive requests a route from the current position instead of reusing the stale route')
serial=serial+1; installGraph(900,1400); tick(); tick()
T.check(ai.mode=='manual' and currentRoute[#currentRoute]=='n1400',
  'fresh road data releases a persistent hold after a restart')
T.check(table.concat(logs,'\n'):find('heartbeat',1,true)
  and table.concat(logs,'\n'):find('graph_refresh',1,true)
  and table.concat(logs,'\n'):find('vehicle_reject',1,true),
  'default diagnostics record heartbeat, stationary refresh and the vehicle rejection')
local logCount=#logs
for i=1,50 do frame() end
T.check(#logs==logCount,'vehicle heartbeat is rate limited rather than printed every graphics frame')
G.clear()

-- Keep extending across 20 km and 100 map replacements, not just the first streaming window.
pos,vel=vec3(40,0,0),vec3(33,0,0)
serial=serial+1; installGraph(0,800)
G.setDestination(0,40000,'Long highway'); G.setAutodrive(true)
tick()
reply={points={{0,40},{0,40000}},dist=39960,dur=1200}
tick()
local longStarts,longRequests=starts,requests
local drove=true
for step=1,200 do
  pos.x=40+step*100
  if step%2==0 then
    local saved=G.beforeGraph(nodes)
    serial=serial+1; installGraph(step*100-100,step*100+800)
    G.afterGraph(saved,nodes)
  end
  tick(3.1)
  drove=drove and ai.mode=='manual' and G.autodrive() and G.status().autoWaiting==nil
end
T.check(drove and starts==longStarts and requests==longRequests,
  'twenty kilometres of streamed highway continue without false endpoints, repeated starts or reroutes')
G.clear()
T.done('test_gps_autodrive')
